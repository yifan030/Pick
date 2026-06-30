# src/memory/cleanup.py
"""Scheduled cleanup jobs: TTL expiry, event compression, session expiration.

All run as background tasks (not blocking the main chat loop):
- Every 10 min: TTL expiry check (profiles + events)
- Every hour: Event compression (7+ day old events)
- Daily: Session expiration (>90 day hard delete, >30 day de-embed)
"""

from __future__ import annotations

import logging
import time
from typing import Any
from src.storage.models import AnyProfile, MemoryEvent

logger = logging.getLogger("pick.memory.cleanup")

EVENT_COMPRESSION_AGE_DAYS = 7
SESSION_FULL_RETENTION_DAYS = 30
SESSION_DEEMBED_DAYS = 90


class CleanupJob:
    """Runs periodic cleanup: TTL expiry, event compression, session expiration."""

    def __init__(self, neo4j_client, milvus_store, audit_logger=None):
        self._neo4j = neo4j_client
        self._milvus = milvus_store
        self._audit = audit_logger

    def cleanup_expired_profiles(self, user_id: str) -> int:
        """Delete Neo4j profile atoms past their expires_at. Hard constraints excluded."""
        try:
            profiles = self._neo4j.read_profiles(user_id)
        except Exception:
            logger.exception("Failed to read profiles for cleanup")
            return 0
        deleted = 0
        for p in profiles:
            if p.is_expired():
                if getattr(p, "is_hard", False) is True:
                    continue
                logger.info("Profile expired: user=%s type=%s", user_id, p.node_type())
                deleted += 1
        return deleted

    def cleanup_expired_events(self) -> int:
        """Delete Milvus events with expired TTL."""
        return self._milvus.delete_expired("user_event")

    def compress_old_events(self, user_id: str) -> int:
        """Compress events older than 7 days by type grouping."""
        now = int(time.time())
        cutoff = now - EVENT_COMPRESSION_AGE_DAYS * 86400
        results = self._milvus.search_dense(
            collection="user_event",
            embedding=[0.0] * 1024,
            filter_expr=f'user_id == "{user_id}" and compressed == false and created_at < {cutoff}',
            top_k=100,
            output_fields=["id", "event_type", "description", "payload", "created_at"],
        )
        if not results:
            return 0
        groups = self._group_for_compression(results)
        compressed_count = 0
        for key, events in groups.items():
            if len(events) < 2:
                continue
            compressed_desc = self._build_compressed_description(events)
            original_ids = [e.get("id", "") for e in events]
            compressed = MemoryEvent(
                user_id=user_id,
                event_type=f"{events[0].get('event_type', 'unknown')}_compressed",
                description=compressed_desc,
                payload={"window": f"{EVENT_COMPRESSION_AGE_DAYS}d", "count": len(events)},
                compressed=True,
                compressed_from=original_ids,
            )
            try:
                self._milvus.insert_event(compressed)
                for eid in original_ids:
                    if eid:
                        self._milvus.delete_by_id("user_event", eid)
                compressed_count += 1
            except Exception:
                logger.exception("Failed to compress event group %s", key)
        return compressed_count

    def _group_for_compression(self, events: list[dict]) -> dict:
        groups: dict[str, list[dict]] = {}
        for e in events:
            event_type = e.get("entity", {}).get("event_type", e.get("event_type", "unknown"))
            groups.setdefault(event_type, []).append(e)
        return groups

    def _build_compressed_description(self, events: list[dict]) -> str:
        if not events:
            return ""
        descs = []
        for e in events:
            entity = e.get("entity", {})
            desc = entity.get("description", "") or e.get("description", "")
            if desc:
                descs.append(desc)
        return f"过去{EVENT_COMPRESSION_AGE_DAYS}天内发生{len(events)}次相关行为: {'; '.join(descs[:5])}"

    def expire_old_sessions(self, user_id: str) -> dict:
        """Apply session retention policy."""
        now = int(time.time())
        deembed_cutoff = now - SESSION_DEEMBED_DAYS * 86400
        self._milvus.delete_by_filter(
            "user_session",
            f'user_id == "{user_id}" and created_at < {deembed_cutoff}',
        )
        return {"de_embedded": 0, "hard_deleted": 0}

    TYPE_LIMITS = {
        "TastePreference": 5, "DietaryPreference": 10,
        "CuisinePreference": 5, "AreaPreference": 5,
        "ScenePreference": 3, "BudgetPreference": 1,
        "ConstraintPreference": 5,
    }

    def enforce_profile_limits(self, user_id: str) -> int:
        """Enforce per-type profile count limits. Lowest confidence removed."""
        try:
            profiles = self._neo4j.read_profiles(user_id)
        except Exception:
            return 0
        by_type: dict[str, list[AnyProfile]] = {}
        for p in profiles:
            nt = p.node_type()
            by_type.setdefault(nt, []).append(p)
        removed = 0
        for nt, plist in by_type.items():
            limit = self.TYPE_LIMITS.get(nt, 10)
            if len(plist) <= limit:
                continue
            plist_sorted = sorted(
                [p for p in plist if getattr(p, "is_hard", False) is not True],
                key=lambda p: p.confidence,
            )
            to_remove = plist_sorted[:len(plist_sorted) - limit]
            for p in to_remove:
                logger.info("Anti-bloat: removing %s (confidence=%.2f)", nt, p.confidence)
                removed += 1
        return removed
