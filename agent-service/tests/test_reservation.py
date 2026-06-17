"""Tests for reservation tools."""
from unittest.mock import MagicMock, patch

import pytest
from httpx import Response

from src.agent.tools.store.reservation import queue_reservation, make_reservation


class TestQueueReservation:
    def test_queue_success(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "reservation_id": 1,
                "queue_number": 5,
                "guests": 2,
                "message": "排队取号成功",
            },
        }

        with patch(
            "src.agent.tools.store.reservation.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = queue_reservation.invoke(
                {"shop_id": 200, "guests": 2, "user_id": 100}
            )

        assert "排队" in result or "取号" in result or "5" in result


class TestMakeReservation:
    def test_reservation_success(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "reservation_id": 2,
                "type": 1,
                "message": "预约已提交，等待确认",
            },
        }

        with patch(
            "src.agent.tools.store.reservation.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = make_reservation.invoke({
                "shop_id": 200,
                "time": "2026-06-17T19:00",
                "guests": 4,
                "user_id": 100,
            })

        assert "预约" in result

    def test_reservation_missing_time(self):
        """When time is missing, the tool should return an error message."""
        result = make_reservation.invoke({
            "shop_id": 200,
            "time": "",
            "guests": 4,
            "user_id": 100,
        })
        assert "预约时间" in result or "时间" in result
