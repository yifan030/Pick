from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.retrieval.consistency import ConsistencyChecker


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    return neo4j


@pytest.fixture
def mock_milvus():
    ms = MagicMock()
    ms.search_dense = MagicMock(return_value=[
        {"id": "evt_1", "entity": {"description": "test"}},
    ])
    return ms


@pytest.fixture
def checker(mock_neo4j, mock_milvus):
    return ConsistencyChecker(
        neo4j_client=mock_neo4j,
        milvus_store=mock_milvus,
    )


def test_is_orphan_true(checker):
    """An event ID not found in Milvus should be marked orphan (returns False = not exists)."""
    checker._milvus.search_dense = MagicMock(return_value=[])
    is_orphan = checker._check_entity_exists("user_event", "evt_nonexistent")
    assert is_orphan is False  # Not found → not exists → orphan


def test_is_orphan_false(checker):
    """An event ID found in Milvus should not be orphan (returns True = exists)."""
    checker._milvus.search_dense = MagicMock(return_value=[{"id": "evt_exists"}])
    is_orphan = checker._check_entity_exists("user_event", "evt_exists")
    assert is_orphan is True  # Found → exists → not orphan
