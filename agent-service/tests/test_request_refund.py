"""Tests for request_refund tool."""
from unittest.mock import MagicMock, patch

import pytest
from httpx import Response

from src.agent.tools.commerce.request_refund import request_refund


class TestRequestRefund:
    def test_refund_success(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "data": {"order_id": 123, "message": "退款申请已提交"},
        }

        with patch(
            "src.agent.tools.commerce.request_refund.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = request_refund.invoke({"order_id": 123, "reason": "不想要了"})

        assert "退款" in result

    def test_refund_failure_when_order_not_refundable(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 400
        mock_response.json.return_value = {
            "success": False,
            "errorMsg": "只有正常状态的订单才能退款",
        }

        with patch(
            "src.agent.tools.commerce.request_refund.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = request_refund.invoke({"order_id": 999, "reason": "不想要了"})

        assert "退款失败" in result or "无法退款" in result or "正常状态" in result
