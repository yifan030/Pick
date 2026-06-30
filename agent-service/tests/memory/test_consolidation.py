# tests/memory/test_consolidation.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.memory.consolidation import ConsolidationJob
from src.storage.models import CuisinePreference


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.read_profiles = AsyncMock(return_value=[
        CuisinePreference(user_id="u1", cuisine="火锅", confidence=0.7, reinforce_count=2, weight=0.8),
        CuisinePreference(user_id="u1", cuisine="川渝火锅", confidence=0.8, reinforce_count=3, weight=0.9),
    ])
    neo4j.delete_profile = AsyncMock()
    neo4j.write_profile = AsyncMock(return_value="merged_id")
    return neo4j


@pytest.fixture
def mock_llm():
    model = MagicMock()
    response = MagicMock()
    response.content = (
        '{"should_merge":true,'
        '"merged":{"cuisine":"川渝火锅","confidence":0.8,"reinforce_count":5,"weight":0.9},'
        '"reason":"火锅是川渝火锅的泛称，语义相似度0.92"}'
    )
    model.invoke = MagicMock(return_value=response)
    return model


@pytest.mark.asyncio
async def test_find_merge_candidates(mock_neo4j):
    """Should find same-type profiles with similar semantics."""
    job = ConsolidationJob(neo4j_client=mock_neo4j, model=MagicMock())
    candidates = await job.find_candidates("u1")
    # Two CuisinePreference -> 1 pair
    assert len(candidates) > 0


@pytest.mark.asyncio
async def test_merge_pair(mock_neo4j, mock_llm):
    """Merging should delete old atoms and create new merged atom."""
    job = ConsolidationJob(neo4j_client=mock_neo4j, model=mock_llm)
    a = CuisinePreference(user_id="u1", cuisine="火锅", confidence=0.7, reinforce_count=2)
    b = CuisinePreference(user_id="u1", cuisine="川渝火锅", confidence=0.8, reinforce_count=3)
    merged = await job.try_merge("u1", a, b)
    assert merged is not None
    mock_neo4j.delete_profile.assert_called()
    mock_neo4j.write_profile.assert_called_once()
