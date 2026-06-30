"""Tests for VectorPreFilter."""
import pytest
from unittest.mock import MagicMock, patch
from src.memory.pre_filter import VectorPreFilter
from src.storage.models import (
    MemoryEvent, TastePreference, CuisinePreference, DietaryPreference
)


@pytest.fixture
def mock_neo4j():
    neo4j = MagicMock()
    neo4j.read_profiles = MagicMock(return_value=[
        TastePreference(user_id="u1", property="spicy", value="avoid", confidence=0.9),
        CuisinePreference(user_id="u1", cuisine="川渝火锅", confidence=0.85, weight=0.9),
    ])
    return neo4j


@pytest.fixture
def mock_milvus():
    ms = MagicMock()
    # Simulate Milvus search returning similar historical events
    ms.search_dense = MagicMock(return_value=[
        {"id": "evt_001", "entity": {"event_type": "search"}},
        {"id": "evt_002", "entity": {"event_type": "search"}},
    ])
    return ms


@pytest.fixture
def mock_embed():
    with patch("src.memory.pre_filter.embed_texts") as mock:
        mock.return_value = [[0.1] * 1024]  # dummy embedding
        yield mock


@pytest.fixture
def pre_filter(mock_neo4j, mock_milvus, mock_embed):
    return VectorPreFilter(
        neo4j_client=mock_neo4j,
        milvus_store=mock_milvus,
    )


def test_pre_filter_returns_relevant_profiles(pre_filter, mock_neo4j):
    """Pre-filter should query Milvus for similar events, then fetch related profiles."""
    events = [
        MemoryEvent(
            user_id="u1", event_type="search",
            description="在春熙路搜索火锅", payload={}
        )
    ]
    profiles = pre_filter.filter("u1", events, top_k=5)
    assert len(profiles) > 0
    mock_neo4j.read_profiles.assert_called_once()


def test_pre_filter_empty_events(pre_filter, mock_neo4j):
    """Empty events should return empty profiles."""
    profiles = pre_filter.filter("u1", [], top_k=5)
    assert profiles == []


def test_pre_filter_always_includes_hard_constraints(pre_filter, mock_neo4j):
    """Hard constraints must always be included regardless of relevance."""
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
