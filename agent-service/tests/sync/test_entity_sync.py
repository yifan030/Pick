# tests/sync/test_entity_sync.py
"""Tests for entity graph sync."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.sync.entity_sync import sync_all_entities, _sync_shops, _sync_areas


@pytest.mark.asyncio
async def test_sync_shops_empty():
    """Sync should handle empty shop list gracefully."""
    neo4j = AsyncMock()
    neo4j.upsert_shop = AsyncMock()
    neo4j.upsert_area = AsyncMock()
    neo4j.link_shop_area = AsyncMock()

    # Mock httpx to return empty list
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        # Use MagicMock for response since .json() is sync, not async
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        count = await _sync_shops(neo4j, mock_client, "http://test")
        assert count == 0


@pytest.mark.asyncio
async def test_sync_shops_with_data():
    """Sync should upsert each shop from the API response."""
    neo4j = AsyncMock()
    neo4j.upsert_shop = AsyncMock()
    neo4j.upsert_area = AsyncMock()
    neo4j.link_shop_area = AsyncMock()

    shop_data = [
        {
            "shopId": 1, "name": "蜀大侠火锅", "type": "美食",
            "subType": "川渝火锅", "area": "春熙路", "address": "春熙路88号",
            "longitude": 104.08, "latitude": 30.66,
            "avgPrice": 80, "score": 4.5,
        },
        {
            "shopId": 2, "name": "点都德", "type": "美食",
            "subType": "粤菜", "area": "太古里", "address": "太古里10号",
            "longitude": 104.09, "latitude": 30.65,
            "avgPrice": 60, "score": 4.2,
        },
    ]

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        # Use MagicMock for response since .json() is sync, not async
        mock_resp = MagicMock()
        mock_resp.json.return_value = shop_data
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        count = await _sync_shops(neo4j, mock_client, "http://test")
        assert count == 2
        assert neo4j.upsert_shop.call_count == 2
        assert neo4j.upsert_area.call_count == 2
        assert neo4j.link_shop_area.call_count == 2
