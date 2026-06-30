"""Memory management LangChain tools for the Pick AI Shopping Guide.

Provides a factory function ``create_memory_tools()`` that returns a list of
5 LangChain ``@tool``-decorated functions allowing the agent to manage user
profile memories (view, delete, update, clear, and temporary ignore).

Usage::

    from src.agent.tools.memory_tools import create_memory_tools

    handler = MemoryControlHandler(neo4j_client)
    tools = create_memory_tools(handler, neo4j_client)
    # tools is a list of 5 LangChain BaseTool instances
"""

import logging
from typing import Any

from langchain.tools import tool

from src.storage.models import (
    AreaPreference,
    BudgetPreference,
    ConstraintPreference,
    CuisinePreference,
    DietaryPreference,
    ScenePreference,
    TastePreference,
    AnyProfile,
)

logger = logging.getLogger("pick.tools.memory")

# ── Profile type string-to-class mapping ─────────────────────────────────

_TYPE_MAP: dict[str, type[AnyProfile]] = {
    "TastePreference": TastePreference,
    "DietaryPreference": DietaryPreference,
    "BudgetPreference": BudgetPreference,
    "CuisinePreference": CuisinePreference,
    "AreaPreference": AreaPreference,
    "ScenePreference": ScenePreference,
    "ConstraintPreference": ConstraintPreference,
}


def create_memory_tools(memory_control_handler: Any, neo4j_client: Any) -> list:
    """Return a list of 5 LangChain ``@tool``-decorated functions.

    Each tool captures ``memory_control_handler`` in its closure and
    delegates the actual work to the handler's synchronous public API.

    Args:
        memory_control_handler: A ``MemoryControlHandler`` instance
            providing synchronous CRUD and ignore methods.
        neo4j_client: A ``Neo4jClient`` instance (held for consistency;
            the handler wraps it internally).

    Returns:
        A list of 5 ``langchain_core.tools.BaseTool`` instances.
    """
    handler = memory_control_handler

    # ── Tool 1: View preferences ───────────────────────────────────────

    @tool
    def view_my_preferences(user_id: str) -> str:
        """查看当前用户的所有已知偏好和画像信息。

        当用户询问「你知道我什么偏好」「记得我什么」「我的画像」时调用。
        返回格式化后的偏好列表文本。

        Args:
            user_id: 用户 ID（字符串形式）
        """
        result = handler.view_memories(user_id)
        return result

    # ── Tool 2: Delete a preference ────────────────────────────────────

    @tool
    def delete_preference(user_id: str, profile_id: str) -> str:
        """删除用户指定的一条偏好/画像记录。

        当用户说「忘掉」「删掉」「去掉」「不要记」某条具体偏好时调用。
        需要提供 profile_id（从 view_my_preferences 的返回中获取）。

        Args:
            user_id: 用户 ID
            profile_id: 要删除的偏好记录的 Neo4j elementId
        """
        ok = handler.delete_memory(user_id, profile_id)
        if ok:
            return "好的，已更新。"
        return "删除失败，请重试。"

    # ── Tool 3: Update (revise) a preference ───────────────────────────

    @tool
    def update_preference(
        user_id: str,
        old_profile_id: str,
        preference_type: str,
        property_name: str,
        new_value: str,
    ) -> str:
        """修改用户的一条已有偏好记录。

        当用户说「其实是」「应该是」「改成」（修改已有偏好）时调用。
        需要提供 old_profile_id、偏好类型（如 TastePreference）、属性名和新的值。

        Args:
            user_id: 用户 ID
            old_profile_id: 要修改的旧记录的 Neo4j elementId
            preference_type: 偏好类型名（如 TastePreference、BudgetPreference 等）
            property_name: 要修改的属性名（如 value、cuisine、area 等）
            new_value: 新的属性值（字符串形式，BudgetPreference 的 range 会自动转 int）
        """
        cls = _TYPE_MAP.get(preference_type)
        if cls is None:
            logger.warning(
                "Unknown preference_type '%s' for user %s",
                preference_type,
                user_id,
            )
            return f"未知偏好类型: {preference_type}，请使用正确的类型名称。"

        # Build the kwargs dict, converting BudgetPreference int fields
        kwargs: dict[str, Any] = {property_name: new_value}
        if preference_type == "BudgetPreference" and property_name in (
            "range_min",
            "range_max",
        ):
            try:
                kwargs[property_name] = int(new_value)
            except (ValueError, TypeError):
                return f"金额 '{new_value}' 格式无效，请输入数字。"

        try:
            new_profile = cls(**kwargs)  # type: ignore[call-arg]
        except TypeError as exc:
            logger.warning(
                "Failed to create %s with %s=%s: %s",
                preference_type,
                property_name,
                new_value,
                exc,
            )
            return f"创建偏好对象失败：{exc}"

        ok = handler.revise_memory(user_id, old_profile_id, new_profile)
        if ok:
            return "好的，已更新。"
        return "修改失败，请重试。"

    # ── Tool 4: Clear all preferences ──────────────────────────────────

    @tool
    def clear_all_preferences(user_id: str) -> str:
        """清除用户的所有偏好和画像记录。

        当用户说「忘掉所有偏好」「清除所有记忆」时调用。
        会删除该用户保存在 Neo4j 中的所有 Profile 节点。

        Args:
            user_id: 用户 ID
        """
        ok = handler.clear_all_memories(user_id)
        if ok:
            return "已清除所有偏好记忆。"
        return "清除失败，请重试。"

    # ── Tool 5: Temporary ignore ───────────────────────────────────────

    @tool
    def temporary_ignore_preferences(user_id: str, session_id: str) -> str:
        """临时忽略用户的历史偏好，本次对话不做个性化推荐。

        当用户说「这次不用管我的偏好」「临时忽略」时调用。
        仅在当前 session 有效，服务重启后失效。

        Args:
            user_id: 用户 ID
            session_id: 当前会话 ID（用于标记临时忽略的范围）
        """
        handler.set_temporary_ignore(user_id, session_id)
        return "好的，本轮推荐将不考虑你的历史偏好。"

    return [
        view_my_preferences,
        delete_preference,
        update_preference,
        clear_all_preferences,
        temporary_ignore_preferences,
    ]
