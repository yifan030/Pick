"""Tests for VectorPreFilter."""
import pytest
from unittest.mock import MagicMock, patch
from src.memory.event.pre_filter import VectorPreFilter, EVENT_TYPE_TO_PROFILE_TYPES
from src.storage.models import (
    MemoryEvent, TastePreference, CuisinePreference, DietaryPreference,
    AreaPreference, BudgetPreference, ScenePreference,
)


@pytest.fixture
def mock_neo4j():
    neo4j = MagicMock()
    neo4j.read_profiles = MagicMock(return_value=[
        TastePreference(user_id="u1", property="spicy", value="avoid", confidence=0.9),
        CuisinePreference(user_id="u1", cuisine="川渝火锅", confidence=0.85, weight=0.9),
        AreaPreference(user_id="u1", area="春熙路", confidence=0.7),
        BudgetPreference(user_id="u1", range_min=50, range_max=100, confidence=0.8),
    ])
    return neo4j


@pytest.fixture
def mock_milvus():
    ms = MagicMock()
    # Simulate Milvus search returning similar historical events
    ms.search_dense = MagicMock(return_value=[
        {"id": "evt_001", "entity": {"event_type": "search", "description": "search火锅"}},
        {"id": "evt_002", "entity": {"event_type": "search", "description": "search川菜"}},
    ])
    return ms


@pytest.fixture
def mock_embed():
    with patch("src.memory.event.pre_filter.embed_texts") as mock:
        mock.return_value = [[0.1] * 1024]  # dummy embedding
        yield mock


@pytest.fixture
def pre_filter(mock_neo4j, mock_milvus, mock_embed):
    return VectorPreFilter(
        neo4j_client=mock_neo4j,
        milvus_store=mock_milvus,
    )


# ── Core filtering tests ──────────────────────────────────────────────


def test_pre_filter_returns_only_relevant_profiles(pre_filter, mock_neo4j):
    """When matching events are found, only profiles of relevant types are returned.

    Events of type "search" map to CuisinePreference, AreaPreference,
    BudgetPreference — so TastePreference should NOT be included.
    """
    events = [
        MemoryEvent(
            user_id="u1", event_type="search",
            description="在春熙路搜索火锅", payload={}
        )
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)

    # CuisinePreference, AreaPreference, BudgetPreference should be included
    profile_types = {p.node_type() for p in profiles}
    assert "CuisinePreference" in profile_types
    assert "AreaPreference" in profile_types
    assert "BudgetPreference" in profile_types

    # TastePreference should NOT be included (search does not map to it)
    assert "TastePreference" not in profile_types

    mock_neo4j.read_profiles.assert_called_once()


def test_pre_filter_empty_events(pre_filter, mock_neo4j):
    """Empty events should return empty profiles."""
    profiles = pre_filter.filter("u1", [], top_k=5)
    assert profiles == []


def test_pre_filter_always_includes_hard_constraints(pre_filter, mock_neo4j):
    """Hard constraints must always be included regardless of event type."""
    mock_neo4j.get_hard_constraints = MagicMock(return_value=[
        DietaryPreference(user_id="u1", constraint="清真", type="religious")
    ])
    events = [MemoryEvent(user_id="u1", event_type="search", description="test", payload={})]
    profiles = pre_filter.filter("u1", events, top_k=5)
    hard_constraints = [p for p in profiles if isinstance(p, DietaryPreference)]
    assert len(hard_constraints) >= 1


def test_pre_filter_embedding_failure_falls_back(pre_filter, mock_neo4j, mock_embed):
    """When embedding fails, pre-filter should fall back to returning all profiles."""
    mock_embed.side_effect = RuntimeError("API unavailable")
    events = [
        MemoryEvent(
            user_id="u1", event_type="search",
            description="在春熙路搜索火锅", payload={}
        )
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)
    assert len(profiles) > 0
    mock_neo4j.read_profiles.assert_called_once()


def test_pre_filter_empty_descriptions(pre_filter, mock_neo4j):
    """Events with no description should return empty profiles list."""
    events = [
        MemoryEvent(user_id="u1", event_type="search", description="", payload={})
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)
    assert profiles == []


def test_pre_filter_deduplication(pre_filter, mock_neo4j):
    """Profiles with same key should not be duplicated."""
    mock_neo4j.get_hard_constraints = MagicMock(return_value=[
        DietaryPreference(user_id="u1", constraint="清真", type="religious")
    ])
    # Include the same hard constraint in regular profiles too
    mock_neo4j.read_profiles = MagicMock(return_value=[
        DietaryPreference(user_id="u1", constraint="清真", type="religious"),
    ])
    events = [MemoryEvent(user_id="u1", event_type="search", description="test", payload={})]
    profiles = pre_filter.filter("u1", events, top_k=5)
    dietary = [p for p in profiles if isinstance(p, DietaryPreference)]
    assert len(dietary) == 1  # deduplicated


def test_pre_filter_sanitizes_user_id_in_filter_expr(pre_filter, mock_milvus):
    """User ID containing double quotes should be escaped in Milvus filter expression."""
    events = [
        MemoryEvent(user_id="u1", event_type="search", description="test query", payload={})
    ]
    pre_filter.filter('u"ser_1', events, top_k=5)
    mock_milvus.search_dense.assert_called_once()
    call_kwargs = mock_milvus.search_dense.call_args[1]
    filter_expr = call_kwargs["filter_expr"]
    assert '\\"' in filter_expr  # double quotes escaped
    assert 'u"ser_1' not in filter_expr.split('"')[1::2]  # raw quotes not in quoted segments


def test_pre_filter_whitespace_only_descriptions(pre_filter):
    """Events with only whitespace descriptions should return empty list."""
    events = [
        MemoryEvent(user_id="u1", event_type="search", description="   ", payload={}),
        MemoryEvent(user_id="u1", event_type="view", description="\t\n", payload={}),
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)
    assert profiles == []


# ── Event-type-based filtering tests ──────────────────────────────────


def test_pre_filter_filters_by_event_type_dietary(pre_filter, mock_neo4j):
    """dietary events should only return DietaryPreference profiles (plus hard constraints)."""
    mock_neo4j.read_profiles = MagicMock(return_value=[
        TastePreference(user_id="u1", property="spicy", value="like", confidence=0.8),
        CuisinePreference(user_id="u1", cuisine="粤菜", confidence=0.7),
        DietaryPreference(user_id="u1", constraint="素食", type="ethical"),
    ])
    mock_neo4j.get_hard_constraints = MagicMock(return_value=[
        DietaryPreference(user_id="u1", constraint="清真", type="religious")
    ])
    pre_filter._milvus.search_dense = MagicMock(return_value=[
        {"id": "evt_003", "entity": {"event_type": "dietary"}},
    ])

    events = [
        MemoryEvent(user_id="u1", event_type="dietary",
                    description="用户表示素食", payload={"constraint": "素食"})
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)

    profile_types = {p.node_type() for p in profiles}
    assert "DietaryPreference" in profile_types
    assert "TastePreference" not in profile_types
    assert "CuisinePreference" not in profile_types

    # All DietaryPreference profiles (from profiles + hard constraints) should be included
    dietary = [p for p in profiles if isinstance(p, DietaryPreference)]
    assert len(dietary) == 2


def test_pre_filter_filters_by_event_type_purchase(pre_filter, mock_neo4j):
    """purchase events should return BudgetPreference and CuisinePreference."""
    events = [
        MemoryEvent(user_id="u1", event_type="purchase",
                    description="用户购买了优惠券", payload={})
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)

    profile_types = {p.node_type() for p in profiles}
    assert "CuisinePreference" in profile_types
    assert "BudgetPreference" in profile_types
    # search-based mocks include search events in historical matches,
    # but combined with purchase current event, relevant types should
    # include Cuisine and Budget at minimum
    assert "TastePreference" not in profile_types


def test_pre_filter_cold_start_returns_hard_constraints_only(pre_filter, mock_neo4j):
    """When no matching historical events, only hard constraints are returned."""
    mock_neo4j.get_hard_constraints = MagicMock(return_value=[
        DietaryPreference(user_id="u1", constraint="清真", type="religious")
    ])
    pre_filter._milvus.search_dense = MagicMock(return_value=[])  # no matches

    events = [
        MemoryEvent(user_id="u1", event_type="search",
                    description="搜索火锅", payload={})
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)

    # Only hard constraints should be returned (cold start)
    profile_types = {p.node_type() for p in profiles}
    assert profile_types == {"DietaryPreference"}


def test_pre_filter_unknown_event_type_ignored(pre_filter, mock_neo4j):
    """Events with unknown event_type should be ignored (no profile types matched)."""
    pre_filter._milvus.search_dense = MagicMock(return_value=[
        {"id": "evt_xxx", "entity": {"event_type": "unknown_future_type"}},
    ])
    mock_neo4j.get_hard_constraints = MagicMock(return_value=[])

    events = [
        MemoryEvent(user_id="u1", event_type="unknown_future_type",
                    description="something new", payload={})
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)

    # No profiles mapped from unknown type, no hard constraints → empty
    assert profiles == []


# ── EVENT_TYPE_TO_PROFILE_TYPES mapping tests ─────────────────────────


def test_mapping_covers_all_known_event_types():
    """Verify the mapping covers all event types mentioned in prompts.py."""
    expected_types = {"search", "purchase", "reservation", "view", "feedback",
                      "constraint", "dietary"}
    assert set(EVENT_TYPE_TO_PROFILE_TYPES.keys()) == expected_types


def test_mapping_only_contains_valid_profile_types():
    """All profile type names in the mapping should be real ProfileBase subclasses."""
    from src.storage.models import ProfileBase
    valid_types = {
        "TastePreference", "DietaryPreference", "BudgetPreference",
        "CuisinePreference", "AreaPreference", "ScenePreference",
        "ConstraintPreference",
    }
    for event_type, profile_types in EVENT_TYPE_TO_PROFILE_TYPES.items():
        for pt in profile_types:
            assert pt in valid_types, f"{event_type} → {pt} is not a valid profile type"
