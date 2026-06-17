"""Tests for check_order_status and list_my_orders tools."""
from unittest.mock import MagicMock, patch

import pytest
from httpx import Response

from src.agent.tools.commerce.check_orders import check_order_status, list_my_orders


class TestCheckOrderStatus:
    def test_returns_order_details_on_success(self):
        """When the backend returns order data, the tool should format it."""
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {
                "order_id": 123,
                "status": 0,
                "status_text": "正常",
                "voucher_title": "50元代金券",
                "quantity": 1,
                "pay_amount": 5000,
                "create_time": "2026-06-17T10:00:00",
            },
        }

        with patch(
            "src.agent.tools.commerce.check_orders.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )
            result = check_order_status.invoke({"order_id": 123})

        assert "订单 #123" in result
        assert "50元代金券" in result
        assert "正常" in result

    def test_returns_not_found_when_order_absent(self):
        """When the backend returns a failed response, report not found."""
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 404
        mock_response.json.return_value = {
            "success": False,
            "errorMsg": "订单不存在",
        }

        with patch(
            "src.agent.tools.commerce.check_orders.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )
            result = check_order_status.invoke({"order_id": 999})

        assert "未找到" in result or "不存在" in result


class TestListMyOrders:
    def test_returns_formatted_order_list(self):
        """Should return a formatted list of user orders."""
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": [
                {
                    "order_id": 1,
                    "voucher_title": "券A",
                    "status": 0,
                    "pay_amount": 3000,
                    "create_time": "2026-06-17T10:00:00",
                }
            ],
        }

        with patch(
            "src.agent.tools.commerce.check_orders.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.get.return_value = (
                mock_response
            )
            result = list_my_orders.invoke({"user_id": 100})

        assert "券A" in result
        assert "¥30.00" in result or "3000" in result
