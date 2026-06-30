"""Tests for the memory management LangChain tools."""

from unittest.mock import MagicMock

import pytest

from src.agent.tools.memory_tools import create_memory_tools


class TestMemoryTools:
    """Test suite for the 5 LangChain memory management tools."""

    @pytest.fixture
    def handler(self):
        """Create a mock MemoryControlHandler."""
        return MagicMock()

    @pytest.fixture
    def neo4j(self):
        """Create a mock Neo4jClient."""
        return MagicMock()

    @pytest.fixture
    def tools(self, handler, neo4j):
        """Create the 5 memory tools via factory."""
        return create_memory_tools(handler, neo4j)

    def _find(self, tools, name):
        """Helper: find a tool by its .name attribute."""
        for t in tools:
            if t.name == name:
                return t
        pytest.fail(f"Tool '{name}' not found in tools list")

    # ── view_my_preferences ────────────────────────────────────────────

    def test_view_my_preferences_delegates(self, tools, handler):
        """view_my_preferences should delegate to handler.view_memories."""
        handler.view_memories.return_value = "测试偏好"
        tool = self._find(tools, "view_my_preferences")
        result = tool.func("u123")
        assert "测试偏好" == result
        handler.view_memories.assert_called_once_with("u123")

    def test_view_my_preferences_empty(self, tools, handler):
        """Empty view response should be passed through unchanged."""
        handler.view_memories.return_value = "📝 目前还没有记录您的偏好信息。"
        tool = self._find(tools, "view_my_preferences")
        result = tool.func("u456")
        assert "还没有记录" in result
        handler.view_memories.assert_called_once_with("u456")

    # ── delete_preference ──────────────────────────────────────────────

    def test_delete_preference_success(self, tools, handler):
        """Successful deletion should return confirmation message."""
        handler.delete_memory.return_value = True
        tool = self._find(tools, "delete_preference")
        result = tool.func("u123", "profile_001")
        assert "已更新" in result
        handler.delete_memory.assert_called_once_with("u123", "profile_001")

    def test_delete_preference_failure(self, tools, handler):
        """Failed deletion should return retry message."""
        handler.delete_memory.return_value = False
        tool = self._find(tools, "delete_preference")
        result = tool.func("u123", "invalid_id")
        assert "删除失败" in result
        assert "重试" in result

    # ── clear_all_preferences ──────────────────────────────────────────

    def test_clear_all_preferences_success(self, tools, handler):
        """Successful clear should return confirmation message."""
        handler.clear_all_memories.return_value = True
        tool = self._find(tools, "clear_all_preferences")
        result = tool.func("u123")
        assert "已清除" in result
        handler.clear_all_memories.assert_called_once_with("u123")

    def test_clear_all_preferences_failure(self, tools, handler):
        """Failed clear should return error message."""
        handler.clear_all_memories.return_value = False
        tool = self._find(tools, "clear_all_preferences")
        result = tool.func("u123")
        assert "清除失败" in result

    # ── temporary_ignore_preferences ───────────────────────────────────

    def test_temporary_ignore(self, tools, handler):
        """temporary_ignore should delegate to handler.set_temporary_ignore."""
        tool = self._find(tools, "temporary_ignore_preferences")
        result = tool.func("u123", "sess_xyz")
        assert "不考虑" in result
        handler.set_temporary_ignore.assert_called_once_with("u123", "sess_xyz")

    # ── update_preference ──────────────────────────────────────────────

    def test_update_preference_success(self, tools, handler):
        """Successful update should return confirmation message."""
        handler.revise_memory.return_value = True
        tool = self._find(tools, "update_preference")
        result = tool.func("u123", "old_1", "TastePreference", "value", "like")
        assert "已更新" in result
        handler.revise_memory.assert_called_once()
        args, _ = handler.revise_memory.call_args
        assert args[0] == "u123"
        assert args[1] == "old_1"
        # Verify the new profile is a TastePreference with value="like"
        new_profile = args[2]
        assert new_profile.node_type() == "TastePreference"
        assert new_profile.value == "like"

    def test_update_preference_failure(self, tools, handler):
        """Failed update should return error message."""
        handler.revise_memory.return_value = False
        tool = self._find(tools, "update_preference")
        result = tool.func("u123", "old_1", "TastePreference", "value", "like")
        assert "修改失败" in result

    def test_update_preference_unknown_type(self, tools, handler):
        """Unknown preference_type should return error message."""
        tool = self._find(tools, "update_preference")
        result = tool.func("u123", "old_1", "UnknownType", "value", "x")
        assert "未知偏好类型" in result
        handler.revise_memory.assert_not_called()

    def test_update_preference_budget_int_conversion(self, tools, handler):
        """BudgetPreference range_min should be converted to int."""
        handler.revise_memory.return_value = True
        tool = self._find(tools, "update_preference")
        result = tool.func("u123", "old_2", "BudgetPreference", "range_min", "100")
        assert "已更新" in result
        args, _ = handler.revise_memory.call_args
        new_profile = args[2]
        assert new_profile.range_min == 100
        assert isinstance(new_profile.range_min, int)

    # ── Tool count and names ───────────────────────────────────────────

    def test_all_five_tools_created(self, tools):
        """Factory should return exactly 5 tools with expected names."""
        assert len(tools) == 5
        names = {t.name for t in tools}
        assert names == {
            "view_my_preferences",
            "delete_preference",
            "update_preference",
            "clear_all_preferences",
            "temporary_ignore_preferences",
        }
