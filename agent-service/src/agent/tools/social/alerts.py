"""Voucher alert / seckill reminder tool for the Pick AI Shopping Guide.

Reuses the existing Java /voucher/subscribe endpoint — no new Java code needed.
"""
import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.social.alerts")


@tool
def set_voucher_alert(voucher_id: int, user_id: int) -> str:
    """设置秒杀优惠券提醒。

    当用户想在某张券秒杀开始时收到提醒时调用。
    复用 Java 后端已有的订阅（subscribe）机制，秒杀开始前会自动通知用户。

    Args:
        voucher_id: 优惠券 ID
        user_id: 用户 ID

    Returns:
        提醒设置结果文本
    """
    logger.info("set_voucher_alert: voucher_id=%s user_id=%s", voucher_id, user_id)

    try:
        with get_java_client() as client:
            payload = {"voucherId": voucher_id, "userId": user_id}
            response = client.post("/voucher/subscribe", json=payload)
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "")
            if "已订阅" in error_msg or "already" in error_msg.lower():
                return "您已经设置了该券的秒杀提醒，开始时会通知您。"
            return f"设置提醒失败：{error_msg}"

        return "已为您设置秒杀提醒，秒杀开始前会通知您。"

    except httpx.HTTPError as e:
        logger.error("set_voucher_alert error: %s", e)
        return "设置提醒失败，请稍后重试。"
    except Exception:
        logger.exception("set_voucher_alert unexpected error")
        return "提醒服务暂时不可用。"
