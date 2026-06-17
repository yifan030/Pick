"""Tests for voucher alert tool."""
from unittest.mock import MagicMock, patch

import pytest
from httpx import Response

from src.agent.tools.social.alerts import set_voucher_alert


class TestSetVoucherAlert:
    def test_alert_success(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch(
            "src.agent.tools.social.alerts.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = set_voucher_alert.invoke(
                {"voucher_id": 100, "user_id": 200}
            )

        assert "提醒" in result or "秒杀" in result or "设置" in result

    def test_alert_already_set(self):
        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": False,
            "errorMsg": "您已订阅该秒杀提醒",
        }

        with patch(
            "src.agent.tools.social.alerts.get_java_client"
        ) as mock_client:
            mock_client.return_value.__enter__.return_value.post.return_value = (
                mock_response
            )
            result = set_voucher_alert.invoke(
                {"voucher_id": 100, "user_id": 200}
            )

        assert "已" in result
