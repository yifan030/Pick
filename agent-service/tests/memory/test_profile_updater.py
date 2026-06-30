"""Tests for ProfileUpdater."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from src.memory.profile_updater import ProfileUpdater
from src.storage.models import (
    TastePreference,
    CuisinePreference,
    DietaryPreference,
    DeltaOperation,
    DELTA_ADD,
    DELTA_REINFORCE,
    DELTA_REVISE,
    DELTA_DELETE,
)


@pytest.fixture
def mock_llm():
    model = MagicMock()
    response = MagicMock()
    response.content = (
        '{"op":"REINFORCE","target_type":"CuisinePreference","target_id":"profile_1",'
        '"new_value":{"cuisine":"川渝火锅","confidence":0.85,"reinforce_count":4},'
        '"reason":"用户再次搜索川渝火锅"}\n'
        '{"op":"ADD","target_type":"CuisinePreference",'
        '"new_value":{"cuisine":"粤菜","confidence":0.6,"weight":0.7},'
        '"reason":"用户表示最近爱上吃粤菜"}'
    )
    model.invoke = MagicMock(return_value=response)
    return model


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.write_profile = AsyncMock(return_value="profile_new")
    neo4j.update_profile = AsyncMock()
    neo4j.delete_profile = AsyncMock()
    return neo4j


@pytest.fixture
def updater(mock_llm, mock_neo4j):
    return ProfileUpdater(model=mock_llm, neo4j_client=mock_neo4j)


def test_compute_delta_returns_operations(updater):
    """ProfileUpdater should parse LLM output into DeltaOperation list."""
    existing = [
        CuisinePreference(
            user_id="u1",
            cuisine="川渝火锅",
            confidence=0.75,
            reinforce_count=3,
            weight=0.9,
        )
    ]
    deltas = updater.compute_delta(
        user_id="u1",
        user_message="我想找川渝火锅和粤菜",
        assistant_response="为您推荐...",
        events=[],
        existing_profiles=existing,
    )
    assert len(deltas) == 2
    assert deltas[0].op == DELTA_REINFORCE
    assert deltas[1].op == DELTA_ADD


def test_apply_delta_add(updater, mock_neo4j):
    """apply_delta with ADD should call neo4j.write_profile."""
    delta = DeltaOperation(
        op=DELTA_ADD,
        target_type="CuisinePreference",
        new_value=CuisinePreference(user_id="u1", cuisine="粤菜", confidence=0.6),
        reason="test",
    )
    updater.apply_delta("u1", [delta])
    mock_neo4j.write_profile.assert_called_once()


def test_apply_delta_reinforce(updater, mock_neo4j):
    """apply_delta with REINFORCE should call neo4j.update_profile."""
    delta = DeltaOperation(
        op=DELTA_REINFORCE,
        target_type="CuisinePreference",
        target_id="profile_1",
        new_value=CuisinePreference(user_id="u1", cuisine="火锅", confidence=0.85),
        reason="test",
    )
    updater.apply_delta("u1", [delta])
    mock_neo4j.update_profile.assert_called()


def test_apply_delta_delete(updater, mock_neo4j):
    """apply_delta with DELETE should call neo4j.delete_profile."""
    delta = DeltaOperation(
        op=DELTA_DELETE,
        target_type="ConstraintPreference",
        target_id="profile_old",
        old_value=None,
        reason="用户纠错",
    )
    updater.apply_delta("u1", [delta])
    mock_neo4j.delete_profile.assert_called_with("profile_old")


def test_reinforce_confidence_clamped(updater):
    """Confidence should not exceed 0.95 after REINFORCE."""
    existing = TastePreference(
        user_id="u1", property="spicy", value="avoid", confidence=0.95
    )
    # Mock Lly to output REINFORCE
    updater._model.invoke.return_value.content = (
        '{"op":"REINFORCE","target_type":"TastePreference","target_id":"p1",'
        '"new_value":{"property":"spicy","value":"avoid","confidence":1.05,"reinforce_count":6},'
        '"reason":"test"}'
    )
    deltas = updater.compute_delta("u1", "不吃辣", "好的", [], [existing])
    if deltas:
        for d in deltas:
            if d.op == DELTA_REINFORCE and d.new_value:
                # Confidence should be clamped to 0.95
                assert d.new_value.confidence <= 0.95
