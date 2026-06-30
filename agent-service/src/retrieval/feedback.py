from __future__ import annotations

"""Quality Feedback Loop: closes the loop between user actions and memory quality.

Processes user interaction signals to reinforce or weaken memory atoms:
- shop_card_click -> REINFORCE (+0.10) related profiles
- chat_purchase_success -> REINFORCE_STRONG (+0.15) related profiles
- explicit_rejection -> WEAKEN (confidence -= 0.10)
- user_correction -> DELETE old atoms (+ optionally ADD new)

Signals arrive asynchronously (from frontend telemetry or inferred from
the next conversation turn by ProfileUpdater).
"""

import logging
import time
from src.storage.models import (
    DELTA_REINFORCE,
    DELTA_DELETE,
    DELTA_REVISE,
)

logger = logging.getLogger("pick.retrieval.feedback")

# -- Signal Types -----------------------------------------------------------

SIGNAL_SHOP_CARD_CLICK = "shop_card_click"
SIGNAL_PURCHASE_SUCCESS = "chat_purchase_success"
SIGNAL_EXPLICIT_REJECTION = "explicit_rejection"
SIGNAL_USER_CORRECTION = "user_correction"
SIGNAL_RECOMMENDATION_IGNORED = "recommendation_ignored"

# -- Confidence Deltas ------------------------------------------------------

REINFORCE_DELTA = 0.10
REINFORCE_STRONG_DELTA = 0.15
WEAKEN_DELTA = -0.10
MAX_CONFIDENCE = 0.95


class FeedbackProcessor:
    """Processes user interaction signals to update memory quality."""

    def __init__(self, neo4j_client):
        self._neo4j = neo4j_client

    def process_signal(
        self,
        user_id: str,
        signal_type: str,
        payload: dict,
        related_profiles: list[str],
    ) -> dict:
        """Process a user interaction signal.

        Args:
            user_id: The user's ID.
            signal_type: One of the SIGNAL_* constants.
            payload: Signal-specific data (shop_id, amount, reason, etc.).
            related_profiles: List of Neo4j profile elementIds that were
                             used in the recommendation that generated
                             this signal.

        Returns:
            Dict with action, profiles_affected, confidence_delta.
        """
        if signal_type == SIGNAL_SHOP_CARD_CLICK:
            return self._handle_click(user_id, payload, related_profiles)
        elif signal_type == SIGNAL_PURCHASE_SUCCESS:
            return self._handle_purchase(user_id, payload, related_profiles)
        elif signal_type == SIGNAL_EXPLICIT_REJECTION:
            return self._handle_rejection(user_id, payload, related_profiles)
        elif signal_type == SIGNAL_USER_CORRECTION:
            return self._handle_correction(user_id, payload, related_profiles)
        elif signal_type == SIGNAL_RECOMMENDATION_IGNORED:
            # No change -- could be many reasons
            return {"action": "no_change", "profiles_affected": 0, "confidence_delta": 0}
        else:
            logger.warning("Unknown signal type: %s", signal_type)
            return {"action": "unknown", "profiles_affected": 0, "confidence_delta": 0}

    def _handle_click(self, user_id: str, payload: dict, profiles: list[str]) -> dict:
        """Shop card click -> moderate reinforce."""
        for pid in profiles:
            try:
                self._neo4j.update_profile(pid, {
                    "reinforce_count": 1,
                    "last_reinforced_at": int(time.time()),
                })
            except Exception:
                logger.exception("Failed to reinforce profile %s", pid)
        return {
            "action": "reinforce",
            "profiles_affected": len(profiles),
            "confidence_delta": REINFORCE_DELTA,
        }

    def _handle_purchase(self, user_id: str, payload: dict, profiles: list[str]) -> dict:
        """Purchase -> strong reinforce."""
        for pid in profiles:
            try:
                self._neo4j.update_profile(pid, {
                    "reinforce_count": 1,
                    "last_reinforced_at": int(time.time()),
                })
            except Exception:
                logger.exception("Failed to strongly reinforce profile %s", pid)
        return {
            "action": "reinforce_strong",
            "profiles_affected": len(profiles),
            "confidence_delta": REINFORCE_STRONG_DELTA,
        }

    def _handle_rejection(self, user_id: str, payload: dict, profiles: list[str]) -> dict:
        """Explicit rejection -> weaken."""
        for pid in profiles:
            try:
                self._neo4j.update_profile(pid, {"confidence_delta": WEAKEN_DELTA})
            except Exception:
                logger.exception("Failed to weaken profile %s", pid)
        return {
            "action": "weaken",
            "profiles_affected": len(profiles),
            "confidence_delta": WEAKEN_DELTA,
        }

    def _handle_correction(self, user_id: str, payload: dict, profiles: list[str]) -> dict:
        """User correction -> delete old."""
        for pid in profiles:
            try:
                self._neo4j.delete_profile(pid)
            except Exception:
                logger.exception("Failed to delete profile %s", pid)
        return {
            "action": "delete",
            "profiles_affected": len(profiles),
            "confidence_delta": -1.0,
        }

    # -- Periodic: process feedback from audit logs -------------------------

    def infer_feedback_from_conversation(
        self, user_message: str, assistant_response: str
    ) -> dict | None:
        """Infer feedback signals from the next conversation turn.

        This is the primary feedback mechanism until a dedicated telemetry
        pipeline is built. The ProfileUpdater naturally handles this in
        Plan B; this method provides a lightweight alternative for cases
        where only the chat endpoint is available.

        Returns:
            Signal dict or None if no clear signal detected.
        """
        msg_lower = user_message.lower()

        # Strong purchase signal
        if any(w in msg_lower for w in ["下单", "买", "支付", "购买成功"]):
            return {"type": SIGNAL_PURCHASE_SUCCESS, "payload": {}}

        # Explicit rejection
        if any(w in msg_lower for w in ["太贵", "不喜欢", "不要", "算了", "换一个"]):
            return {"type": SIGNAL_EXPLICIT_REJECTION, "payload": {}}

        # Correction
        if any(w in msg_lower for w in ["错了", "不对", "其实是", "纠正"]):
            return {"type": SIGNAL_USER_CORRECTION, "payload": {}}

        # Implicit positive (next turn continues similar search)
        # Too noisy to detect from text alone -- use structured telemetry
        return None
