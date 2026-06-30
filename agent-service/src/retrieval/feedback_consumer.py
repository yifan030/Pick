# src/retrieval/feedback_consumer.py
"""Kafka FeedbackConsumer for the user behavior feedback loop.

Consumes from topic ``user.behavior.feedback`` and updates Neo4j
Profile confidence based on user behaviour signals:

- shop_card_click   → REINFORCE (+0.1)
- purchase_success  → REINFORCE_STRONG (+0.15)
- explicit_rejection → WEAKEN (-0.1)

Confidence changes are clamped to [0.0, 0.95].  Profiles that drop
below 0.3 are deleted.  Every feedback event writes an audit entry
to ``data/memory_diff/{user_id}/{YYYY-MM}.jsonl`` with
``agent_role="feedback_loop"``.
"""

from __future__ import annotations

import json
import os
import logging
import asyncio
from datetime import datetime
from typing import Any, Optional

from aiokafka import AIOKafkaConsumer

logger = logging.getLogger("pick.retrieval.feedback_consumer")

# ── Confidence bounds ──────────────────────────────────────────────────

MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.30                    # delete below this threshold

# ── Audit path (mirrors memory/audit.py convention) ────────────────────

_AUDIT_BASE = os.environ.get(
    "MEMORY_AUDIT_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "memory_diff"),
)


class FeedbackConsumer:
    """Consumes user behaviour feedback from Kafka and updates Neo4j profiles."""

    def __init__(
        self,
        neo4j_client: Any,
        bootstrap_servers: str = "localhost:9092",
        topic: str = "user.behavior.feedback",
        group_id: str = "pick-feedback-consumer",
    ):
        self._neo4j = neo4j_client
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._group_id = group_id
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._running = False

    # ── Public API ────────────────────────────────────────────────────

    def parse_message(self, raw: dict) -> dict:
        """Extract canonical fields from a raw Kafka message.

        Returns a dict with keys: user_id, event_type, trace_id, shop_id,
        session_id, timestamp.
        """
        context = raw.get("context") or {}
        return {
            "user_id": raw.get("user_id", ""),
            "event_type": raw.get("event_type", ""),
            "trace_id": raw.get("trace_id"),
            "shop_id": raw.get("shop_id", ""),
            "session_id": context.get("session_id", ""),
            "timestamp": raw.get("timestamp"),
        }

    def get_reinforce_delta(self, event_type: str) -> float:
        """Return the confidence delta for a given event type."""
        if event_type == "shop_card_click":
            return 0.1
        if event_type == "purchase_success":
            return 0.15
        if event_type == "explicit_rejection":
            return -0.1
        return 0.0

    # ── Event processing ──────────────────────────────────────────────

    async def process_event(self, event: dict) -> None:
        """Core logic: resolve trace → update/delete profiles → write audit.

        Skipped silently when trace_id is None (no profiles to update).
        """
        trace_id = event.get("trace_id")
        if trace_id is None:
            logger.debug("Skipping event without trace_id: %s", event.get("event_id"))
            return

        try:
            profiles = await self._neo4j.get_profiles_by_trace(trace_id)
        except Exception:
            logger.exception("Failed to get profiles for trace_id=%s", trace_id)
            return

        if not profiles:
            logger.debug("No profiles found for trace_id=%s", trace_id)
            return

        delta = self.get_reinforce_delta(event["event_type"])
        event_timestamp = event.get("timestamp") or datetime.now().timestamp()
        user_id = event["user_id"]
        affected = 0

        for profile in profiles:
            try:
                current_conf = profile.confidence
                new_conf = max(0.0, min(MAX_CONFIDENCE, current_conf + delta))
                old_rc = getattr(profile, "reinforce_count", 0)

                if new_conf < MIN_CONFIDENCE:
                    await self._neo4j.delete_profile(profile.id)
                    logger.info(
                        "Deleted profile %s (confidence %.2f < %.2f)",
                        profile.id, new_conf, MIN_CONFIDENCE,
                    )
                else:
                    await self._neo4j.update_profile(profile.id, {
                        "confidence": new_conf,
                        "reinforce_count": old_rc + 1,
                        "last_reinforced_at": int(event_timestamp),
                    })
                affected += 1
            except Exception:
                logger.exception(
                    "Failed to process profile %s for event_type=%s",
                    getattr(profile, "id", "?"), event["event_type"],
                )

        self._write_audit(user_id, event, affected, delta)
        logger.debug(
            "Feedback processed: type=%s user=%s affected=%d delta=%.2f",
            event["event_type"], user_id, affected, delta,
        )

    # ── Audit ─────────────────────────────────────────────────────────

    def _write_audit(
        self, user_id: str, event: dict, profiles_affected: int, delta: float,
    ) -> None:
        """Append a JSONL audit entry."""
        now = datetime.now()
        month_str = now.strftime("%Y-%m")
        dir_path = os.path.join(_AUDIT_BASE, user_id)
        try:
            os.makedirs(dir_path, exist_ok=True)
        except OSError:
            logger.exception("Failed to create audit dir %s", dir_path)
            return

        file_path = os.path.join(dir_path, f"{month_str}.jsonl")

        entry = {
            "timestamp": now.isoformat(),
            "user_id": user_id,
            "agent_role": "feedback_loop",
            "event_type": event.get("event_type"),
            "trace_id": event.get("trace_id"),
            "shop_id": event.get("shop_id"),
            "session_id": event.get("session_id"),
            "profiles_affected": profiles_affected,
            "confidence_delta": delta,
        }

        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to write audit log for user=%s", user_id)

    # ── Kafka lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Connect to Kafka and begin listening."""
        self._consumer = AIOKafkaConsumer(
            self._topic,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            value_deserializer=lambda v: json.loads(v.decode("utf-8")),
        )
        await self._consumer.start()
        self._running = True
        logger.info("FeedbackConsumer started on topic=%s group=%s", self._topic, self._group_id)

    async def stop(self) -> None:
        """Gracefully stop the consumer."""
        self._running = False
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        logger.info("FeedbackConsumer stopped.")

    async def consume_loop(self) -> None:
        """Async generator loop that processes every incoming message."""
        if self._consumer is None:
            raise RuntimeError("Consumer not started. Call start() first.")
        async for msg in self._consumer:
            if not self._running:
                break
            try:
                event = self.parse_message(msg.value)
                await self.process_event(event)
            except Exception:
                logger.exception("Unhandled error in consume_loop")
