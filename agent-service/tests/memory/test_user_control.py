"""Tests for MemoryControlHandler."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory.control.handler import MemoryControlHandler
from src.storage.models import (
    AreaPreference,
    BudgetPreference,
    ConstraintPreference,
    CuisinePreference,
    DietaryPreference,
    ScenePreference,
    TastePreference,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def mock_neo4j():
    """Create an AsyncMock Neo4jClient with async profile methods."""
    neo4j = MagicMock()
    neo4j.read_profiles = AsyncMock()
    neo4j.delete_profile = AsyncMock()
    neo4j.write_profile = AsyncMock(return_value="new_profile_id")
    neo4j.delete_all_profiles = AsyncMock()
    return neo4j


@pytest.fixture
def handler(mock_neo4j):
    """Create a MemoryControlHandler backed by a mock Neo4jClient."""
    return MemoryControlHandler(neo4j_client=mock_neo4j)


# ── Helper: sample profiles ─────────────────────────────────────────────


def _all_profile_types() -> list:
    """Return one profile of each type for testing."""
    return [
        TastePreference(property="spicy", value="avoid", confidence=0.9, reinforce_count=5),
        DietaryPreference(constraint="清真", type="religious"),
        BudgetPreference(range_min=50, range_max=100),
        CuisinePreference(cuisine="川渝火锅", confidence=0.85, weight=0.9),
        AreaPreference(area="春熙路"),
        ScenePreference(scene="朋友聚餐"),
        ConstraintPreference(constraint="不要辣", confidence=0.8),
    ]


# ── ViewMemories ─────────────────────────────────────────────────────────


class TestViewMemories:
    """Tests for ``MemoryControlHandler.view_memories()``."""

    def test_view_all_types(self, handler, mock_neo4j):
        """All profile types should be rendered with appropriate emoji and labels."""
        profiles = _all_profile_types()
        mock_neo4j.read_profiles.return_value = profiles

        result = handler.view_memories("u1")

        assert "不吃辣" in result
        assert "清真" in result
        assert "人均50-100元" in result
        assert "川渝火锅" in result
        assert "春熙路" in result
        assert "朋友聚餐" in result
        assert "不要辣" in result

    def test_view_no_memories(self, handler, mock_neo4j):
        """Empty profile list should return a user-friendly no-data message."""
        mock_neo4j.read_profiles.return_value = []

        result = handler.view_memories("u1")

        assert "还没有记录" in result
        assert "📝" in result

    def test_exclude_low_confidence(self, handler, mock_neo4j):
        """Profiles with confidence < 0.3 should be excluded from output."""
        profiles = [
            TastePreference(property="spicy", value="avoid", confidence=0.2),
            CuisinePreference(cuisine="川菜", confidence=0.9),
        ]
        mock_neo4j.read_profiles.return_value = profiles

        result = handler.view_memories("u1")

        assert "川菜" in result
        assert "不吃辣" not in result  # confidence 0.2 < 0.3

    def test_confidence_boundary_included(self, handler, mock_neo4j):
        """Confidence exactly 0.3 should be included (>= threshold)."""
        profiles = [
            CuisinePreference(cuisine="粤菜", confidence=0.3),
        ]
        mock_neo4j.read_profiles.return_value = profiles

        result = handler.view_memories("u1")

        assert "粤菜" in result

    def test_taste_preference_formats(self, handler, mock_neo4j):
        """TastePreference should use correct emoji and Chinese labels."""
        mock_neo4j.read_profiles.return_value = [
            TastePreference(property="spicy", value="like", confidence=0.95),
            TastePreference(property="spicy", value="avoid", confidence=0.8),
        ]

        result = handler.view_memories("u1")

        assert "喜欢辣" in result
        assert "不吃辣" in result

    def test_hard_constraint_no_confidence_tag(self, handler, mock_neo4j):
        """Hard constraints (DietaryPreference) should omit confidence tags."""
        mock_neo4j.read_profiles.return_value = [
            DietaryPreference(constraint="清真", type="religious"),
        ]

        result = handler.view_memories("u1")

        assert "🕌" in result
        # Hard constraints should not show confidence tag
        assert "信心指数" not in result

    def test_format_consistency(self, handler, mock_neo4j):
        """Multiple calls with the same data should produce identical output."""
        profiles = _all_profile_types()
        mock_neo4j.read_profiles.return_value = profiles

        r1 = handler.view_memories("u1")
        r2 = handler.view_memories("u1")

        assert r1 == r2


# ── DeleteMemory ─────────────────────────────────────────────────────────


class TestDeleteMemory:
    """Tests for ``MemoryControlHandler.delete_memory()``."""

    def test_delete_success(self, handler, mock_neo4j):
        """Successful deletion should return True and call Neo4j."""
        result = handler.delete_memory("u1", "profile_123")

        assert result is True
        mock_neo4j.delete_profile.assert_called_once_with("profile_123")

    def test_delete_failure(self, handler, mock_neo4j):
        """Exception from Neo4j should return False."""
        mock_neo4j.delete_profile.side_effect = Exception("Neo4j error")

        result = handler.delete_memory("u1", "invalid_id")

        assert result is False
        mock_neo4j.delete_profile.assert_called_once_with("invalid_id")

    def test_delete_empty_profile_id(self, handler, mock_neo4j):
        """Deleting with an empty profile id should return False."""
        mock_neo4j.delete_profile.side_effect = Exception("Invalid elementId")

        result = handler.delete_memory("u1", "")

        assert result is False

    def test_delete_logs_warning_on_failure(self, handler, mock_neo4j, caplog):
        """Failure should log a warning message."""
        mock_neo4j.delete_profile.side_effect = ValueError("bad id")

        handler.delete_memory("u1", "bad")

        assert any(
            "Failed to delete profile" in record.message
            for record in caplog.records
            if record.levelname == "WARNING"
        )


# ── ReviseMemory ─────────────────────────────────────────────────────────


class TestReviseMemory:
    """Tests for ``MemoryControlHandler.revise_memory()``."""

    def test_revise_success(self, handler, mock_neo4j):
        """Revise should delete old profile and write new one."""
        new_profile = CuisinePreference(cuisine="粤菜", confidence=0.8)

        result = handler.revise_memory("u1", "old_1", new_profile)

        assert result is True
        mock_neo4j.delete_profile.assert_called_once_with("old_1")
        mock_neo4j.write_profile.assert_called_once_with("u1", new_profile)

    def test_revise_delete_failure(self, handler, mock_neo4j):
        """If delete fails, write should not be called and returns False."""
        mock_neo4j.delete_profile.side_effect = Exception("Delete failed")
        new_profile = CuisinePreference(cuisine="粤菜", confidence=0.8)

        result = handler.revise_memory("u1", "old_1", new_profile)

        assert result is False
        mock_neo4j.delete_profile.assert_called_once_with("old_1")
        mock_neo4j.write_profile.assert_not_called()

    def test_revise_write_failure(self, handler, mock_neo4j):
        """If write fails after successful delete, returns False."""
        mock_neo4j.write_profile.side_effect = Exception("Write failed")
        new_profile = CuisinePreference(cuisine="粤菜", confidence=0.8)

        result = handler.revise_memory("u1", "old_1", new_profile)

        assert result is False
        mock_neo4j.delete_profile.assert_called_once_with("old_1")
        mock_neo4j.write_profile.assert_called_once_with("u1", new_profile)


# ── ClearAllMemories ─────────────────────────────────────────────────────


class TestClearAllMemories:
    """Tests for ``MemoryControlHandler.clear_all_memories()``."""

    def test_clear_success(self, handler, mock_neo4j):
        """Successful clear should return True and call Neo4j."""
        result = handler.clear_all_memories("u1")

        assert result is True
        mock_neo4j.delete_all_profiles.assert_called_once_with("u1")

    def test_clear_failure(self, handler, mock_neo4j):
        """Exception from Neo4j should return False."""
        mock_neo4j.delete_all_profiles.side_effect = Exception("DB error")

        result = handler.clear_all_memories("u1")

        assert result is False
        mock_neo4j.delete_all_profiles.assert_called_once_with("u1")

    def test_clear_different_users(self, handler, mock_neo4j):
        """Clearing one user should not affect other users."""
        handler.clear_all_memories("u1")
        handler.clear_all_memories("u2")

        assert mock_neo4j.delete_all_profiles.call_count == 2
        mock_neo4j.delete_all_profiles.assert_any_call("u1")
        mock_neo4j.delete_all_profiles.assert_any_call("u2")


# ── Temporary Ignore ─────────────────────────────────────────────────────


class TestTemporaryIgnore:
    """Tests for temporary session-level ignore functionality."""

    def test_set_and_check(self, handler):
        """A session marked for ignore should be detected."""
        handler.set_temporary_ignore("u1", "sess_1")

        assert handler.is_temporary_ignore("u1", "sess_1") is True

    def test_not_ignored_by_default(self, handler):
        """Unmarked sessions should not be flagged as ignored."""
        assert handler.is_temporary_ignore("u1", "unknown_session") is False

    def test_user_isolation(self, handler):
        """Ignore flag should be scoped per (user_id, session_id)."""
        handler.set_temporary_ignore("u1", "sess_1")

        assert handler.is_temporary_ignore("u2", "sess_1") is False

    def test_session_isolation(self, handler):
        """Different sessions for same user should be independent."""
        handler.set_temporary_ignore("u1", "sess_1")

        assert handler.is_temporary_ignore("u1", "sess_2") is False

    def test_clear_ignore_not_supported_directly(self, handler):
        """Setting ignore is idempotent (no remove yet — OK for coverage)."""
        handler.set_temporary_ignore("u1", "sess_1")
        handler.set_temporary_ignore("u1", "sess_1")  # twice — no crash

        assert handler.is_temporary_ignore("u1", "sess_1") is True


# ── Integration-style Edge Cases ─────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and error handling."""

    def test_neo4j_read_failure(self, handler, mock_neo4j):
        """If Neo4j read_profiles raises, the error propagates."""
        mock_neo4j.read_profiles.side_effect = RuntimeError("Neo4j down")

        with pytest.raises(RuntimeError, match="Neo4j down"):
            handler.view_memories("u1")

    def test_unknown_profile_type_fallback(self, handler, mock_neo4j):
        """An unrecognised profile type should not crash the formatter."""

        # Simulate a profile with an unexpected node_type
        class FakeProfile:
            confidence = 0.9

            def node_type(self):
                return "UnknownType"

            def __str__(self):
                return "fake data"

        mock_neo4j.read_profiles.return_value = [FakeProfile()]  # type: ignore[list-item]

        # Should not raise, falls back to generic format
        result = handler.view_memories("u1")
        assert "UnknownType" in result

    def test_taste_property_not_in_map(self, handler, mock_neo4j):
        """TastePreference with an unmapped property should fall through."""
        mock_neo4j.read_profiles.return_value = [
            TastePreference(property="umami", value="like", confidence=0.8),
        ]

        result = handler.view_memories("u1")

        assert "umami" in result

    def test_budget_single_value(self, handler, mock_neo4j):
        """BudgetPreference with min==max should still display correctly."""
        mock_neo4j.read_profiles.return_value = [
            BudgetPreference(range_min=80, range_max=80),
        ]

        result = handler.view_memories("u1")

        assert "人均80-80元" in result
