# tests/memory/test_cleanup.py
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from src.memory.lifecycle.cleanup import CleanupJob


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.read_profiles = MagicMock(return_value=[])
    return neo4j


@pytest.fixture
def mock_milvus():
    ms = MagicMock()
    ms.delete_by_filter = MagicMock()
    ms.search_dense = MagicMock(return_value=[])
    return ms


def test_ttl_cleanup_expired_profiles(mock_neo4j):
    """Expired profiles should be deleted from Neo4j."""
    from src.storage.models import TastePreference
    past = int(time.time()) - 86400  # 1 day ago
    expired = TastePreference(
        user_id="u1", property="spicy", value="avoid",
        expires_at=past, ttl_seconds=86400,
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[expired])
    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    count = job.cleanup_expired_profiles("u1")
    assert count >= 1


def test_event_compression_trigger():
    """Events older than 7 days, same type+area should be compressed."""
    job = CleanupJob(neo4j_client=MagicMock(), milvus_store=MagicMock())
    events = [
        {"id": "e1", "event_type": "search", "description": "春熙路 火锅", "created_at": int(time.time()) - 8*86400},
        {"id": "e2", "event_type": "search", "description": "春熙路 川渝火锅", "created_at": int(time.time()) - 7*86400},
    ]
    groups = job._group_for_compression(events)
    assert len(groups) > 0
