"""Tests for bookmark tools."""
from unittest.mock import MagicMock, patch

import pytest
from httpx import Response

from src.agent.tools.social.bookmarks import (
    bookmark_shop,
    list_bookmarks,
    remove_bookmark,
)


class TestBookmarkShop:
    def test_bookmark_success(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {"bookmark_id": 1, "shop_id": 200, "message": "收藏成功"},
        }

        with patch(
            "src.agent.tools.social.bookmarks.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = bookmark_shop.invoke({"shop_id": 200, "user_id": 100})

        assert "收藏成功" in result or "已收藏" in result


class TestListBookmarks:
    def test_list_empty(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "data": []}

        with patch(
            "src.agent.tools.social.bookmarks.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )
            result = list_bookmarks.invoke({"user_id": 100})

        assert "暂无" in result or "没有" in result

    def test_list_with_items(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": [
                {"bookmark_id": 1, "shop_id": 200, "shop_name": "海底捞", "area": "春熙路"}
            ],
        }

        with patch(
            "src.agent.tools.social.bookmarks.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )
            result = list_bookmarks.invoke({"user_id": 100})

        assert "海底捞" in result


class TestRemoveBookmark:
    def test_remove_success(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch(
            "src.agent.tools.social.bookmarks.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.delete.return_value = (
                mock_response
            )
            result = remove_bookmark.invoke({"bookmark_id": 1})

        assert "取消" in result or "移除" in result
