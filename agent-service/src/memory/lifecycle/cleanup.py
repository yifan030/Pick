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

# ── Confidence decay ──────────────────────────────────────────────────

DECAY_INTERVAL_DAYS = 30        # profiles not reinforced for 30 days start decaying
DECAY_RATE = 0.1                # each decay cycle reduces confidence by 10% (×0.9)
DECAY_MIN_CONFIDENCE = 0.3      # delete profiles whose confidence drops below this


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
                pid = getattr(p, "id", None)
                if pid:
                    try:
                        self._neo4j.delete_profile(pid)
                        deleted += 1
                    except Exception:
                        logger.exception("Failed to delete expired profile %s", pid)
                else:
                    deleted += 1  # Counted but not deletable (no id)
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
                pid = getattr(p, "id", None)
                if pid:
                    try:
                        self._neo4j.delete_profile(pid)
                        removed += 1
                    except Exception:
                        logger.exception("Failed to delete bloated profile %s", pid)
                else:
                    removed += 1  # Counted but not deletable (no id)
        return removed

    # ── Confidence decay ───────────────────────────────────────────────

    def decay_stale_profiles(self, user_id: str) -> dict:
        """Apply time-based confidence decay to profiles not reinforced recently.

        Profiles whose last activity (``last_reinforced_at``, falling back to
        ``updated_at``, then ``created_at``) is older than
        :data:`DECAY_INTERVAL_DAYS` have their confidence multiplied by
        ``(1 - DECAY_RATE)``.  Profiles that drop below
        :data:`DECAY_MIN_CONFIDENCE` are deleted.

        Hard constraints (``is_hard=True``) and profiles created less than
        :data:`DECAY_INTERVAL_DAYS` ago are always skipped.

        Returns a dict with keys ``decayed`` (count of profiles whose
        confidence was lowered) and ``deleted`` (count deleted for dropping
        below the minimum threshold).
        """
        now = int(time.time())
        cutoff = now - DECAY_INTERVAL_DAYS * 86400

        try:
            profiles = self._neo4j.read_profiles(user_id)
        except Exception:
            logger.exception("Failed to read profiles for decay check")
            return {"decayed": 0, "deleted": 0}

        decayed = 0
        deleted = 0

        for p in profiles:
            # Hard constraints never decay
            if getattr(p, "is_hard", False) is True:
                continue

            # Determine last active timestamp
            last_active = (
                getattr(p, "last_reinforced_at", None)
                or getattr(p, "updated_at", None)
                or getattr(p, "created_at", 0)
            )

            # Skip profiles that are still within the observation window
            if last_active is None or last_active >= cutoff:
                continue

            # Apply multiplicative decay
            old_conf = p.confidence
            new_conf = round(old_conf * (1.0 - DECAY_RATE), 4)

            if new_conf < DECAY_MIN_CONFIDENCE:
                # Confidence too low — delete the profile atom
                logger.info(
                    "Decay: deleting %s for user=%s (confidence %.2f → %.2f, below %.2f)",
                    p.node_type(), user_id, old_conf, new_conf, DECAY_MIN_CONFIDENCE,
                )
                if getattr(p, "id", None):
                    try:
                        self._neo4j.delete_profile(p.id)
                        deleted += 1
                    except Exception:
                        logger.exception("Failed to delete decayed profile %s", getattr(p, "id", "?"))
                else:
                    deleted += 1  # counted but not deletable (no elementId)
            else:
                # Update confidence in Neo4j
                logger.debug(
                    "Decay: %s for user=%s confidence %.2f → %.2f",
                    p.node_type(), user_id, old_conf, new_conf,
                )
                if getattr(p, "id", None):
                    try:
                        self._neo4j.update_profile(p.id, {"confidence": new_conf})
                        decayed += 1
                    except Exception:
                        logger.exception("Failed to update decayed profile %s", getattr(p, "id", "?"))
                else:
                    decayed += 1  # counted but not updatable (no elementId)

        if decayed or deleted:
            logger.info(
                "Decay complete for user=%s: %d decayed, %d deleted",
                user_id, decayed, deleted,
            )

        return {"decayed": decayed, "deleted": deleted}
