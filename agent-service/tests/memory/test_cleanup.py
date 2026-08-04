# tests/memory/test_cleanup.py
import pytest
import time
from unittest.mock import AsyncMock, MagicMock
from src.memory.lifecycle.cleanup import (
    CleanupJob,
    DECAY_INTERVAL_DAYS,
    DECAY_RATE,
    DECAY_MIN_CONFIDENCE,
)


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


# ── Confidence decay tests ────────────────────────────────────────────


def test_decay_stale_profiles(mock_neo4j):
    """Profiles not reinforced for >30 days should have confidence decayed."""
    from src.storage.models import CuisinePreference
    stale_time = int(time.time()) - (DECAY_INTERVAL_DAYS + 1) * 86400
    profile = CuisinePreference(
        user_id="u1", cuisine="川渝火锅", confidence=0.8,
        last_reinforced_at=stale_time, id="profile_cuisine_001",
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[profile])

    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    result = job.decay_stale_profiles("u1")

    assert result["decayed"] == 1
    assert result["deleted"] == 0

    # Verify the profile confidence was lowered
    expected_new_conf = round(0.8 * (1.0 - DECAY_RATE), 4)
    mock_neo4j.update_profile.assert_called_once()
    call_args = mock_neo4j.update_profile.call_args
    assert call_args[0][1]["confidence"] == expected_new_conf


def test_decay_skips_hard_constraints(mock_neo4j):
    """Hard constraints (is_hard=True) should never decay."""
    from src.storage.models import DietaryPreference
    stale_time = int(time.time()) - (DECAY_INTERVAL_DAYS + 10) * 86400
    profile = DietaryPreference(
        user_id="u1", constraint="清真", type="religious",
        confidence=1.0, last_reinforced_at=stale_time,
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[profile])

    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    result = job.decay_stale_profiles("u1")

    assert result["decayed"] == 0
    assert result["deleted"] == 0
    mock_neo4j.update_profile.assert_not_called()
    mock_neo4j.delete_profile.assert_not_called()


def test_decay_deletes_below_threshold(mock_neo4j):
    """Profiles whose confidence drops below DECAY_MIN_CONFIDENCE are deleted."""
    from src.storage.models import TastePreference
    stale_time = int(time.time()) - (DECAY_INTERVAL_DAYS + 5) * 86400
    # confidence = 0.33 → after decay (×0.9) = 0.297 < 0.3 → deleted
    profile = TastePreference(
        user_id="u1", property="spicy", value="like",
        confidence=0.33, last_reinforced_at=stale_time, id="profile_taste_001",
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[profile])

    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    result = job.decay_stale_profiles("u1")

    assert result["decayed"] == 0
    assert result["deleted"] == 1
    mock_neo4j.delete_profile.assert_called_once()
    mock_neo4j.update_profile.assert_not_called()


def test_decay_skips_recent_profiles(mock_neo4j):
    """Profiles reinforced recently should not be decayed."""
    from src.storage.models import CuisinePreference
    recent_time = int(time.time()) - 5 * 86400  # only 5 days ago
    profile = CuisinePreference(
        user_id="u1", cuisine="火锅", confidence=0.7,
        last_reinforced_at=recent_time,
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[profile])

    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    result = job.decay_stale_profiles("u1")

    assert result["decayed"] == 0
    assert result["deleted"] == 0
    mock_neo4j.update_profile.assert_not_called()


def test_decay_uses_fallback_timestamps(mock_neo4j):
    """When last_reinforced_at is None, fall back to updated_at then created_at."""
    from src.storage.models import AreaPreference
    stale_time = int(time.time()) - (DECAY_INTERVAL_DAYS + 3) * 86400
    # last_reinforced_at is None, updated_at is stale
    profile = AreaPreference(
        user_id="u1", area="太古里", confidence=0.6,
        last_reinforced_at=None, updated_at=stale_time,
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[profile])

    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    result = job.decay_stale_profiles("u1")

    assert result["decayed"] == 1
    assert result["deleted"] == 0


def test_decay_skips_recently_created_without_reinforce(mock_neo4j):
    """New profiles (<30 days, never reinforced) should not decay yet."""
    from src.storage.models import ScenePreference
    recent_time = int(time.time()) - 10 * 86400  # only 10 days old
    profile = ScenePreference(
        user_id="u1", scene="约会", confidence=0.6,
        last_reinforced_at=None, created_at=recent_time,
    )
    mock_neo4j.read_profiles = MagicMock(return_value=[profile])

    job = CleanupJob(neo4j_client=mock_neo4j, milvus_store=MagicMock())
    result = job.decay_stale_profiles("u1")

    assert result["decayed"] == 0
    assert result["deleted"] == 0
