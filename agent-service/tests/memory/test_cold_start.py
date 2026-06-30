"""Tests for ColdStartManager.

Covers the three core scenarios:
1. Cold-start detection (is_cold_start True / False).
2. Behavior-data fetching (with and without java_client).
3. Profile construction from behavior data (correct types, source, confidence).
4. Full orchestration import.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.memory.cold_start import ColdStartManager
from src.storage.models import (
    AreaPreference,
    BudgetPreference,
    CuisinePreference,
)


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_neo4j():
    neo4j = MagicMock()
    neo4j.read_profiles = AsyncMock(return_value=[])
    neo4j.write_profile = AsyncMock(return_value="profile_id")
    return neo4j


@pytest.fixture
def mock_java_client():
    client = MagicMock()
    client.get_user_favorites = AsyncMock(return_value=[])
    client.get_user_orders = AsyncMock(return_value=[])
    return client


@pytest.fixture
def manager(mock_neo4j, mock_java_client):
    return ColdStartManager(neo4j_client=mock_neo4j, java_client=mock_java_client)


# ── is_cold_start ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_is_cold_start_true(manager, mock_neo4j):
    """Should return True when ``read_profiles`` returns an empty list."""
    mock_neo4j.read_profiles.return_value = []
    assert await manager.is_cold_start("u1") is True
    mock_neo4j.read_profiles.assert_awaited_once_with("u1")


@pytest.mark.asyncio
async def test_is_cold_start_false(manager, mock_neo4j):
    """Should return False when at least one profile exists."""
    mock_neo4j.read_profiles.return_value = [
        CuisinePreference(user_id="u1", cuisine="川渝火锅")
    ]
    assert await manager.is_cold_start("u1") is False


@pytest.mark.asyncio
async def test_is_cold_start_true_when_no_neo4j():
    """Should return True when neo4j_client is None (assume cold start)."""
    mgr = ColdStartManager(neo4j_client=None)
    assert await mgr.is_cold_start("u1") is True


# ── fetch_behavior_data ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_behavior_data_returns_empty_when_no_client():
    """Should return {} when java_client is None."""
    mgr = ColdStartManager(neo4j_client=MagicMock(), java_client=None)
    result = await mgr.fetch_behavior_data("u1")
    assert result == {}


@pytest.mark.asyncio
async def test_fetch_behavior_data_returns_favorites_and_orders(manager, mock_java_client):
    """Should return favorites and orders from the java client."""
    mock_java_client.get_user_favorites.return_value = [
        {"shop_id": 1, "name": "海底捞", "cuisine": "川渝火锅"},
    ]
    mock_java_client.get_user_orders.return_value = [
        {"shop_id": 2, "name": "粤菜馆", "cuisine": "粤菜"},
    ]
    result = await manager.fetch_behavior_data("u1")
    assert result["favorites"] == [{"shop_id": 1, "name": "海底捞", "cuisine": "川渝火锅"}]
    assert result["orders"] == [{"shop_id": 2, "name": "粤菜馆", "cuisine": "粤菜"}]


@pytest.mark.asyncio
async def test_fetch_behavior_data_handles_exception(manager, mock_java_client):
    """Should gracefully handle API failures and return partial data."""
    mock_java_client.get_user_favorites.side_effect = Exception("API error")
    mock_java_client.get_user_orders.return_value = [
        {"shop_id": 2, "name": "粤菜馆", "cuisine": "粤菜"},
    ]
    result = await manager.fetch_behavior_data("u1")
    assert result["favorites"] == []
    assert len(result["orders"]) == 1


# ── build_profiles_from_behavior ──────────────────────────────────────────


class TestBuildProfilesFromBehavior:
    """Tests for the synchronous profile-building logic."""

    def test_empty_behavior_returns_empty_list(self, manager):
        """No favorites or orders should yield zero profiles."""
        profiles = manager.build_profiles_from_behavior("u1", {})
        assert profiles == []

    def test_creates_cuisine_preferences_from_favorites(self, manager):
        """Favorites with cuisine fields become CuisinePreference atoms."""
        data = {
            "favorites": [
                {"shop_id": 1, "name": "海底捞", "cuisine": "川渝火锅", "area": "春熙路"},
            ],
            "orders": [],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        cuisines = [p for p in profiles if isinstance(p, CuisinePreference)]
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "川渝火锅"

    def test_creates_area_preferences_from_favorites(self, manager):
        """Favorites with area fields become AreaPreference atoms."""
        data = {
            "favorites": [
                {"shop_id": 1, "name": "海底捞", "cuisine": "川渝火锅", "area": "春熙路"},
            ],
            "orders": [],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        areas = [p for p in profiles if isinstance(p, AreaPreference)]
        assert len(areas) == 1
        assert areas[0].area == "春熙路"

    def test_creates_budget_preference_from_orders(self, manager):
        """Order prices should produce a single BudgetPreference atom."""
        data = {
            "favorites": [],
            "orders": [
                {"shop_id": 1, "name": "A", "cuisine": "川渝火锅", "area": "春熙路", "price": 100},
                {"shop_id": 2, "name": "B", "cuisine": "粤菜", "area": "太古里", "price": 200},
            ],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        budgets = [p for p in profiles if isinstance(p, BudgetPreference)]
        assert len(budgets) == 1
        # avg price = 150, range_min = 105, range_max = 195
        assert budgets[0].range_min == 105
        assert budgets[0].range_max == 195

    def test_deduplicates_cuisine_across_favorites_and_orders(self, manager):
        """Same cuisine in both favorites and orders should appear only once."""
        data = {
            "favorites": [
                {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路"},
            ],
            "orders": [
                {"shop_id": 2, "cuisine": "川渝火锅", "area": "太古里"},
            ],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        cuisines = [p for p in profiles if isinstance(p, CuisinePreference)]
        assert len(cuisines) == 1

    def test_deduplicates_area_across_favorites_and_orders(self, manager):
        """Same area in both favorites and orders should appear only once."""
        data = {
            "favorites": [
                {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路"},
            ],
            "orders": [
                {"shop_id": 2, "cuisine": "粤菜", "area": "春熙路"},
            ],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        areas = [p for p in profiles if isinstance(p, AreaPreference)]
        assert len(areas) == 1

    def test_fallback_to_shop_type_when_no_cuisine(self, manager):
        """Should fall back to 'shop_type' when 'cuisine' is absent."""
        data = {
            "favorites": [
                {"shop_id": 1, "shop_type": "火锅", "area": "春熙路"},
            ],
            "orders": [],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        cuisines = [p for p in profiles if isinstance(p, CuisinePreference)]
        assert len(cuisines) == 1
        assert cuisines[0].cuisine == "火锅"

    def test_skips_zero_price_orders_for_budget(self, manager):
        """Orders with price 0 or None should not affect BudgetPreference."""
        data = {
            "favorites": [],
            "orders": [
                {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路", "price": 0},
                {"shop_id": 2, "cuisine": "粤菜", "area": "太古里", "price": None},
            ],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        budgets = [p for p in profiles if isinstance(p, BudgetPreference)]
        assert len(budgets) == 0

    def test_budget_range_min_never_below_zero(self, manager):
        """range_min should be clamped at 0 for very cheap orders."""
        data = {
            "favorites": [],
            "orders": [
                {"shop_id": 1, "cuisine": "小吃", "area": "街边", "price": 5},
            ],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        budgets = [p for p in profiles if isinstance(p, BudgetPreference)]
        assert len(budgets) == 1
        assert budgets[0].range_min == 3  # int(5 * 0.7) = 3


# ── source and confidence constraints ─────────────────────────────────────


class TestProfileMetadata:
    """Every profile built from behavior data must carry correct metadata."""

    SAMPLE_DATA = {
        "favorites": [
            {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路", "price": 120},
        ],
        "orders": [
            {"shop_id": 2, "cuisine": "粤菜", "area": "太古里", "price": 80},
        ],
    }

    def test_all_profiles_have_source_behavior_import(self, manager):
        """Every profile should carry ``source == 'behavior_import'``."""
        profiles = manager.build_profiles_from_behavior("u1", self.SAMPLE_DATA)
        assert len(profiles) > 0
        for p in profiles:
            assert p.source == "behavior_import", (
                f"{type(p).__name__} missing source='behavior_import'"
            )

    def test_all_profiles_confidence_within_bounds(self, manager):
        """Every profile confidence should be between 0.4 and 0.6 (inclusive)."""
        profiles = manager.build_profiles_from_behavior("u1", self.SAMPLE_DATA)
        assert len(profiles) > 0
        for p in profiles:
            assert 0.4 <= p.confidence <= 0.6, (
                f"{type(p).__name__} confidence {p.confidence} out of [0.4, 0.6]"
            )

    def test_favorite_profiles_have_higher_confidence_than_order_profiles(self, manager):
        """Cuisine/area from favorites (0.5) should be >= orders (0.4)."""
        data = {
            "favorites": [
                {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路"},
            ],
            "orders": [
                {"shop_id": 2, "cuisine": "粤菜", "area": "太古里"},
            ],
        }
        profiles = manager.build_profiles_from_behavior("u1", data)
        fav_cuisines = {
            p.cuisine: p.confidence
            for p in profiles
            if isinstance(p, CuisinePreference)
        }
        # "川渝火锅" comes from favorites → 0.5
        assert fav_cuisines["川渝火锅"] == 0.5
        # "粤菜" comes from orders → 0.4
        assert fav_cuisines["粤菜"] == 0.4


# ── run_behavior_import (orchestration) ────────────────────────────────────


@pytest.mark.asyncio
async def test_run_behavior_import_writes_profiles(manager, mock_neo4j, mock_java_client):
    """Full pipeline should write each profile to Neo4j and return count."""
    mock_java_client.get_user_favorites.return_value = [
        {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路", "price": 120},
    ]
    mock_java_client.get_user_orders.return_value = [
        {"shop_id": 2, "cuisine": "粤菜", "area": "太古里", "price": 80},
    ]

    count = await manager.run_behavior_import("u1")

    # Expected profiles: 2 cuisine + 2 area + 1 budget = 5
    assert count == 5
    assert mock_neo4j.write_profile.await_count == 5


@pytest.mark.asyncio
async def test_run_behavior_import_returns_zero_when_no_neo4j(mock_java_client):
    """Should return 0 when neo4j_client is None."""
    mgr = ColdStartManager(neo4j_client=None, java_client=mock_java_client)
    count = await mgr.run_behavior_import("u1")
    assert count == 0


@pytest.mark.asyncio
async def test_run_behavior_import_handles_write_failure(manager, mock_neo4j, mock_java_client):
    """A single write failure should not stop remaining profiles from being written."""
    mock_java_client.get_user_favorites.return_value = [
        {"shop_id": 1, "cuisine": "川渝火锅", "area": "春熙路"},
    ]
    mock_java_client.get_user_orders.return_value = []

    # Make the first write fail, second succeed
    mock_neo4j.write_profile = AsyncMock()
    mock_neo4j.write_profile.side_effect = [
        Exception("DB error"),   # first profile fails
        "profile_id_ok",         # second succeeds
    ]

    count = await manager.run_behavior_import("u1")
    # 1 cuisine + 1 area = 2 total, 1 succeeds
    assert count == 1
    assert mock_neo4j.write_profile.await_count == 2


@pytest.mark.asyncio
async def test_run_behavior_import_empty_behavior(manager, mock_neo4j, mock_java_client):
    """No behavior data should result in zero profiles and zero writes."""
    mock_java_client.get_user_favorites.return_value = []
    mock_java_client.get_user_orders.return_value = []

    count = await manager.run_behavior_import("u1")
    assert count == 0
    mock_neo4j.write_profile.assert_not_awaited()
