from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.retrieval.gateway import RetrievalGateway


@pytest.fixture
def mock_milvus():
    ms = MagicMock()
    ms.search_dense = MagicMock(return_value=[
        {"id": "evt_1", "distance": 0.9, "entity": {"description": "搜索火锅"}},
    ])
    ms.search_sparse = MagicMock(return_value=[
        {"id": "evt_2", "score": 0.5, "entity": {"description": "浏览粤菜"}},
    ])
    return ms


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.read_profiles = AsyncMock(return_value=[])
    neo4j.get_hard_constraints = AsyncMock(return_value=[])
    neo4j.subgraph_search = AsyncMock(return_value=[])
    return neo4j


@pytest.fixture
def gateway(mock_milvus, mock_neo4j):
    return RetrievalGateway(
        milvus_store=mock_milvus,
        neo4j_client=mock_neo4j,
    )


@pytest.mark.asyncio
async def test_retrieve_new_session(gateway):
    """New session should trigger full three-way retrieval."""
    result = await gateway.retrieve(
        user_id="u1",
        query="春熙路火锅",
        is_new_session=True,
    )
    assert result is not None
    assert "memories" in result
    assert "profiles" in result
    assert "hard_constraints" in result


@pytest.mark.asyncio
async def test_retrieve_existing_session_skips(gateway):
    """Existing session should skip retrieval."""
    result = await gateway.retrieve(
        user_id="u1",
        query="继续",
        is_new_session=False,
    )
    assert result["memories"] == []
    assert result["profiles"] == []
    assert result["hard_constraints"] == []


def test_gateway_has_all_searchers(gateway):
    """Gateway should instantiate all three searchers."""
    assert gateway.semantic is not None
    assert gateway.bm25 is not None
    assert gateway.entity_boost is not None
