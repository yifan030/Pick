"""Tests for shared memory data models."""
import json
import time
from dataclasses import asdict
from src.storage.models import (
    ProfileAtom,
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    MemoryEvent,
    SessionSummary,
    AgentCase,
    DeltaOperation,
    ProfileDelta,
    DELTA_ADD,
    DELTA_REINFORCE,
    DELTA_REVISE,
    DELTA_DELETE,
    DELTA_MERGE,
    DELTA_NOCHANGE,
    DELTA_EXPIRE,
)


def test_taste_preference_defaults():
    """TastePreference should have correct defaults."""
    p = TastePreference(
        user_id="u1",
        property="spicy",
        value="like",
    )
    assert p.confidence == 0.6
    assert p.reinforce_count == 0
    assert p.source == "agent"
    assert p.is_hard is False
    assert p.ttl_seconds is None
    assert p.expires_at is None


def test_dietary_preference_is_hard():
    """DietaryPreference is always hard by default."""
    p = DietaryPreference(
        user_id="u1",
        constraint="清真",
        type="religious",
    )
    assert p.is_hard is True
    assert p.confidence == 1.0


def test_memory_event_serialization():
    """MemoryEvent should serialize to dict for Milvus insert."""
    e = MemoryEvent(
        user_id="u1",
        event_type="search",
        description="用户在春熙路搜索火锅",
        payload={"query": "火锅", "area": "春熙路"},
        session_id="sess_abc",
    )
    d = e.to_milvus_dict()
    assert d["user_id"] == "u1"
    assert d["event_type"] == "search"
    assert d["payload"] == '{"query": "火锅", "area": "春熙路"}'  # JSON string
    assert d["compressed"] is False


def test_session_summary_incremental():
    """SessionSummary defaults to incomplete (ongoing)."""
    s = SessionSummary(
        user_id="u1",
        summary="用户在春熙路搜索火锅",
        key_shops=["shop_1"],
        key_areas=["春熙路"],
        intent="recommend_shop",
    )
    assert s.is_complete is False


def test_agent_case_optional_user():
    """AgentCase user_id can be None for generic patterns."""
    ac = AgentCase(
        user_id=None,
        case_type="recommendation",
        description="用户不吃辣推荐粤菜成功",
        context={},
        action="推荐粤菜馆",
        outcome="success",
        lesson="不吃辣时优先推荐粤菜",
    )
    assert ac.user_id is None


def test_delta_operation_types():
    """Verify all delta operation constants are distinct."""
    ops = {DELTA_ADD, DELTA_REINFORCE, DELTA_REVISE, DELTA_DELETE, DELTA_MERGE, DELTA_NOCHANGE, DELTA_EXPIRE}
    assert len(ops) == 7


def test_profile_delta_structure():
    """ProfileDelta should carry operation + target info."""
    delta = ProfileDelta(
        op=DELTA_ADD,
        target_type="CuisinePreference",
        new_value=CuisinePreference(
            user_id="u1",
            cuisine="川渝火锅",
            confidence=0.6,
            weight=0.9,
        ),
        reason="用户最近频繁搜索火锅",
    )
    assert delta.op == DELTA_ADD
    assert delta.target_type == "CuisinePreference"
    assert delta.old_value is None
    assert delta.new_value.cuisine == "川渝火锅"
