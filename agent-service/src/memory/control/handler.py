"""MemoryControlHandler — synchronous user-facing memory management commands.

Provides immediate (non-streaming) CRUD operations for user profile atoms,
allowing users to view, delete, revise, and clear their conversational memory.
Temporary session-level profile-injection ignore is also supported via an
in-memory set (not persisted across restarts).
"""

from __future__ import annotations

import asyncio
import logging

from src.storage.models import (
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    AnyProfile,
)

logger = logging.getLogger("pick.memory.user_control")


class MemoryControlHandler:
    """Synchronous handler for user-facing memory management.

    Wraps the async Neo4jClient with synchronous methods suitable for
    immediate user commands (not streaming). Each public method manages
    its own event loop lifecycle via ``asyncio.run()``.

    Usage::

        handler = MemoryControlHandler(neo4j_client)
        text = handler.view_memories(user_id)
        ok = handler.delete_memory(user_id, profile_id)
    """

    # Class-level set for temporary session-level profile injection ignore.
    # Keyed by ``(user_id, session_id)`` tuples.
    _ignored_sessions: set[tuple[str, str]] = set()

    def __init__(self, neo4j_client):
        self._neo4j = neo4j_client

    # ── Public API ──────────────────────────────────────────────────

    def view_memories(self, user_id: str) -> str:
        """Return all active profiles formatted as Chinese text with emoji labels.

        Profiles with ``confidence < 0.3`` are excluded (both by Neo4j query
        and by an explicit secondary filter in this method).

        Returns a human-readable string ready for display to the user.
        """
        profiles: list[AnyProfile] = asyncio.run(
            self._neo4j.read_profiles(user_id)
        )
        # Secondary safety filter — ensures confidence threshold is met
        profiles = [p for p in profiles if p.confidence >= 0.3]

        if not profiles:
            return "📝 目前还没有记录您的偏好信息。"

        lines: list[str] = ["📋 以下是我对您的了解：\n"]
        for i, profile in enumerate(profiles, 1):
            formatted = self._format_profile(profile)
            confidence_info = self._confidence_tag(profile)
            lines.append(f"{i}. {formatted}{confidence_info}")

        return "\n".join(lines)

    def delete_memory(self, user_id: str, profile_id: str) -> bool:
        """Delete a specific profile atom by its Neo4j elementId.

        Returns ``True`` on success, ``False`` on failure (e.g. invalid id).
        """
        try:
            asyncio.run(self._neo4j.delete_profile(profile_id))
            logger.info("Deleted profile %s for user %s", profile_id, user_id)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to delete profile %s for user %s: %s",
                profile_id, user_id, exc,
            )
            return False

    def revise_memory(
        self,
        user_id: str,
        old_profile_id: str,
        new_profile: AnyProfile,
    ) -> bool:
        """Replace an existing profile atom with a new one.

        Deletes the old profile by its elementId, then writes the new profile.
        Returns ``True`` only if both operations succeed.
        """
        try:
            asyncio.run(self._neo4j.delete_profile(old_profile_id))
            asyncio.run(self._neo4j.write_profile(user_id, new_profile))
            logger.info(
                "Revised profile %s for user %s -> %s",
                old_profile_id,
                user_id,
                new_profile.node_type(),
            )
            return True
        except Exception as exc:
            logger.warning(
                "Failed to revise profile %s for user %s: %s",
                old_profile_id,
                user_id,
                exc,
            )
            return False

    def clear_all_memories(self, user_id: str) -> bool:
        """Delete all profile atoms for the given user.

        Returns ``True`` on success, ``False`` on failure.
        """
        try:
            asyncio.run(self._neo4j.delete_all_profiles(user_id))
            logger.info("Cleared all profiles for user %s", user_id)
            return True
        except Exception as exc:
            logger.warning(
                "Failed to clear profiles for user %s: %s",
                user_id,
                exc,
            )
            return False

    # ── Temporary Ignore ────────────────────────────────────────────

    def set_temporary_ignore(self, user_id: str, session_id: str) -> None:
        """Mark a session to skip Profile injection.

        The ignore flag is held in an **in-memory set** and does not
        persist across application restarts.
        """
        self._ignored_sessions.add((user_id, session_id))
        logger.debug(
            "Temporary ignore set for user %s session %s",
            user_id,
            session_id,
        )

    def is_temporary_ignore(self, user_id: str, session_id: str) -> bool:
        """Check whether a session has been marked for temporary ignore."""
        return (user_id, session_id) in self._ignored_sessions

    # ── Formatting Helpers ──────────────────────────────────────────

    @staticmethod
    def _format_profile(profile: AnyProfile) -> str:
        """Format a single ProfileAtom as Chinese text with emoji label."""
        node_type = profile.node_type()

        if node_type == "TastePreference":
            return _format_taste(profile)
        elif node_type == "DietaryPreference":
            return f"🕌 {profile.constraint}饮食（硬约束）"
        elif node_type == "BudgetPreference":
            return f"💰 人均{profile.range_min}-{profile.range_max}元"
        elif node_type == "CuisinePreference":
            return f"🍳 偏好{profile.cuisine}"
        elif node_type == "AreaPreference":
            return f"📍 常去{profile.area}"
        elif node_type == "ScenePreference":
            return f"🎯 偏好场景：{profile.scene}"
        elif node_type == "ConstraintPreference":
            return f"⚠️ {profile.constraint}"

        # Fallback for any future profile types
        return f"📌 {node_type}: {profile}"

    @staticmethod
    def _confidence_tag(profile: AnyProfile) -> str:
        """Return a short confidence tag for display (omitted for hard
        constraints and high-confidence items)."""
        if getattr(profile, "is_hard", False):
            return ""
        if profile.confidence >= 0.9:
            return ""
        if profile.confidence >= 0.6:
            return "（信心指数：较高）"
        return "（信心指数：一般）"


# ── Taste-specific format helper ────────────────────────────────────────


def _format_taste(profile: TastePreference) -> str:
    """Format a TastePreference with common Chinese taste labels."""
    taste_labels = {
        "spicy": "辣",
        "sweet": "甜",
        "sour": "酸",
        "bitter": "苦",
        "salty": "咸",
    }
    label = taste_labels.get(profile.property, profile.property)
    if profile.value == "avoid":
        return f"🍽️ 不吃{label}"
    elif profile.value == "like":
        return f"🍽️ 喜欢{label}"
    return f"🍽️ {profile.property}={profile.value}"
