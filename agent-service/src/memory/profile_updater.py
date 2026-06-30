# src/memory/profile_updater.py
"""Profile Updater: computes and applies delta operations to user profiles.

Flow:
1. Receive existing profiles (pre-filtered for relevance) + current turn context
2. LLM compares new information against existing profiles
3. Outputs delta operations: ADD, REINFORCE, REVISE, DELETE, MERGE, NOCHANGE, EXPIRE
4. Apply deltas to Neo4j (write/update/delete profile atoms)
5. Generate audit log entry via memory_diff
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from src.storage.models import (
    AnyProfile,
    DeltaOperation,
    DELTA_ADD,
    DELTA_REINFORCE,
    DELTA_REVISE,
    DELTA_DELETE,
    DELTA_MERGE,
    DELTA_NOCHANGE,
    DELTA_EXPIRE,
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
)
from src.memory.prompts import PROFILE_UPDATE_PROMPT
from src.memory.feedback_fallback import detect_implicit_feedback

logger = logging.getLogger("pick.memory.profile_updater")

# ── Target type → Python class ────────────────────────────────────────

TYPE_CLASS_MAP: dict[str, type[AnyProfile]] = {
    "TastePreference": TastePreference,
    "DietaryPreference": DietaryPreference,
    "BudgetPreference": BudgetPreference,
    "CuisinePreference": CuisinePreference,
    "AreaPreference": AreaPreference,
    "ScenePreference": ScenePreference,
    "ConstraintPreference": ConstraintPreference,
}

MAX_CONFIDENCE = 0.95
MIN_CONFIDENCE = 0.3
DEFAULT_CONFIDENCE = 0.6


class ProfileUpdater:
    """Computes and applies delta operations to user profile atoms."""

    def __init__(self, model: Any = None, neo4j_client=None):
        """Args:
            model: A LangChain BaseChatModel instance. If None, uses config.get_model().
            neo4j_client: Neo4j storage client with write_profile/update_profile/delete_profile.
        """
        if model is None:
            from src.agent.config import get_extractor_model

            model = get_extractor_model()
        self._model = model
        self._neo4j = neo4j_client

    def compute_delta(
        self,
        user_id: str,
        user_message: str,
        assistant_response: str,
        events: list,
        existing_profiles: list[AnyProfile],
    ) -> list[DeltaOperation]:
        """Compute delta operations by comparing new info against existing profiles.

        Args:
            user_id: The user's ID.
            user_message: The user's query text.
            assistant_response: The agent's response text.
            events: List of MemoryEvent extracted from this turn.
            existing_profiles: Pre-filtered existing profile atoms for this user.

        Returns:
            List of DeltaOperation objects (may be empty).
        """
        if not existing_profiles:
            return self._deltas_from_events_only(user_id, events)

        profiles_text = self._format_profiles(existing_profiles)
        events_text = self._format_events(events)

        # 隐式反馈检测（Kafka 就绪前的降级方案）
        feedback_signals = detect_implicit_feedback(user_message)
        if feedback_signals:
            feedback_lines = []
            for sig in feedback_signals:
                feedback_lines.append(f"反馈: {sig['type']}({sig['detail']})")
            feedback_text = "\n".join(feedback_lines)
            if events_text == "(无)":
                events_text = feedback_text
            else:
                events_text += "\n" + feedback_text

        prompt = PROFILE_UPDATE_PROMPT.format(
            existing_profiles=profiles_text,
            user_message=user_message,
            assistant_response=assistant_response,
            events=events_text,
        )

        try:
            response = self._model.invoke([HumanMessage(content=prompt)])
            content = response.content
            raw = (content if isinstance(content, str) else str(content) if content else "").strip()
        except Exception:
            logger.exception("Profile update LLM call failed")
            return []

        return self._parse_delta_response(raw, user_id)

    def apply_delta(self, user_id: str, deltas: list[DeltaOperation]) -> list[dict]:
        """Execute delta operations against Neo4j. Returns audit entries.

        Args:
            user_id: The user's ID.
            deltas: List of DeltaOperation to apply.

        Returns:
            List of audit dicts (one per applied delta).
        """
        audit_entries = []
        for delta in deltas:
            try:
                entry = self._apply_single(user_id, delta)
                audit_entries.append(entry)
            except Exception:
                logger.exception("Failed to apply delta: %s %s", delta.op, delta.target_id)
        return audit_entries

    def _apply_single(self, user_id: str, delta: DeltaOperation) -> dict:
        """Apply a single delta operation to Neo4j."""
        if delta.op == DELTA_ADD:
            if delta.new_value is not None:
                pid = self._neo4j.write_profile(user_id, delta.new_value)
                delta.target_id = pid

        elif delta.op == DELTA_REINFORCE:
            if delta.target_id is not None and delta.new_value is not None:
                updates = {
                    "confidence": min(delta.new_value.confidence, MAX_CONFIDENCE),
                    "reinforce_count": getattr(delta.new_value, "reinforce_count", 0),
                    "last_reinforced_at": delta.new_value.updated_at,
                }
                self._neo4j.update_profile(delta.target_id, updates)

        elif delta.op == DELTA_REVISE:
            if delta.target_id is not None:
                self._neo4j.update_profile(delta.target_id, {"confidence": MIN_CONFIDENCE})
            if delta.new_value is not None:
                delta.new_value.confidence = DEFAULT_CONFIDENCE
                pid = self._neo4j.write_profile(user_id, delta.new_value)
                delta.target_id = pid

        elif delta.op == DELTA_DELETE:
            if delta.target_id is not None:
                self._neo4j.delete_profile(delta.target_id)

        elif delta.op == DELTA_MERGE:
            if delta.target_id is not None and delta.new_value is not None:
                self._neo4j.delete_profile(delta.target_id)
                pid = self._neo4j.write_profile(user_id, delta.new_value)
                delta.target_id = pid

        # NOCHANGE and EXPIRE are currently no-ops in this layer
        # (EXPIRE handled by CleanupJob scheduled task)

        return delta.to_audit_dict()

    def _parse_delta_response(self, raw: str, user_id: str) -> list[DeltaOperation]:
        """Parse LLM response (one JSON object per line) into DeltaOperation list."""
        deltas = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed delta line: %.100s", line)
                continue

            try:
                op = data.get("op", DELTA_NOCHANGE)
                target_type = data.get("target_type", "")

                old_val = self._dict_to_profile(target_type, data.get("old_value"), user_id)
                new_val = self._dict_to_profile(target_type, data.get("new_value"), user_id)

                if new_val is not None and hasattr(new_val, "confidence"):
                    new_val.confidence = min(new_val.confidence, MAX_CONFIDENCE)

                delta = DeltaOperation(
                    op=op,
                    target_type=target_type,
                    target_id=data.get("target_id"),
                    old_value=old_val,
                    new_value=new_val,
                    reason=data.get("reason", ""),
                )
                deltas.append(delta)
            except Exception:
                logger.exception("Failed to create DeltaOperation from: %.100s", line)

        return deltas

    def _deltas_from_events_only(
        self, user_id: str, events: list
    ) -> list[DeltaOperation]:
        """When no existing profiles, create ADD from constraint/dietary events."""
        deltas = []
        for event in events:
            if event.event_type == "dietary":
                deltas.append(
                    DeltaOperation(
                        op=DELTA_ADD,
                        target_type="DietaryPreference",
                        new_value=DietaryPreference(
                            user_id=user_id,
                            constraint=event.payload.get("constraint", ""),
                            type=event.payload.get("type", ""),
                            confidence=1.0,
                        ),
                        reason=f"从对话中提取: {event.description}",
                    )
                )
            elif event.event_type == "constraint":
                deltas.append(
                    DeltaOperation(
                        op=DELTA_ADD,
                        target_type="ConstraintPreference",
                        new_value=ConstraintPreference(
                            user_id=user_id,
                            constraint=event.payload.get("constraint", ""),
                            confidence=DEFAULT_CONFIDENCE,
                        ),
                        reason=f"从对话中提取: {event.description}",
                    )
                )
        return deltas

    def _format_profiles(self, profiles: list[AnyProfile]) -> str:
        """Format existing profiles for the LLM prompt."""
        if not profiles:
            return "(无已有偏好)"
        lines = []
        for p in profiles:
            nt = p.node_type()
            if nt == "TastePreference":
                lines.append(
                    f"- [口味] {p.property}:{p.value} (置信度:{p.confidence}, 提及{p.reinforce_count}次)"
                )
            elif nt == "DietaryPreference":
                lines.append(
                    f"- [饮食约束] {p.constraint} (硬约束, 类型:{p.type}, 置信度:{p.confidence})"
                )
            elif nt == "BudgetPreference":
                lines.append(
                    f"- [预算] {p.range_min}-{p.range_max}元 (置信度:{p.confidence})"
                )
            elif nt == "CuisinePreference":
                lines.append(
                    f"- [菜系] {p.cuisine} (权重:{p.weight}, 置信度:{p.confidence})"
                )
            elif nt == "AreaPreference":
                lines.append(
                    f"- [商圈] {p.area} (权重:{p.weight}, 置信度:{p.confidence})"
                )
            elif nt == "ScenePreference":
                lines.append(
                    f"- [场景] {p.scene} (权重:{p.weight}, 置信度:{p.confidence})"
                )
            elif nt == "ConstraintPreference":
                lines.append(
                    f"- [约束] {p.constraint} (置信度:{p.confidence})"
                )
            else:
                lines.append(
                    f"- [{nt}] (置信度:{p.confidence})"
                )
        return "\n".join(lines)

    def _format_events(self, events: list) -> str:
        """Format extracted events for the LLM prompt."""
        if not events:
            return "(无)"
        lines = []
        for e in events:
            lines.append(f"- [{e.event_type}] {e.description}")
        return "\n".join(lines)

    @staticmethod
    def _dict_to_profile(
        target_type: str, data: dict | None, user_id: str
    ) -> AnyProfile | None:
        """Convert a dict (from LLM output) to a ProfileAtom instance."""
        if data is None or not target_type:
            return None
        cls = TYPE_CLASS_MAP.get(target_type)
        if cls is None:
            logger.warning("Unknown target type: %s", target_type)
            return None
        data["user_id"] = user_id
        from dataclasses import fields as dc_fields

        valid = {f.name for f in dc_fields(cls)}
        filtered = {k: v for k, v in data.items() if k in valid}
        try:
            return cls(**filtered)
        except Exception:
            logger.exception("Failed to construct %s from %s", target_type, data)
            return None
