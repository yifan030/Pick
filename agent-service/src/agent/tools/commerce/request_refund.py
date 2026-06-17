"""Refund request tool for the Pick AI Shopping Guide."""
import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.commerce.refund")


@tool
def request_refund(order_id: int, reason: str = "") -> str:
    """为指定订单申请退款。

    此工具会触发人工确认流程（HumanInTheLoopMiddleware）。
    用户必须明确确认后，退款才会真正提交。

    业务规则：
    - 只有状态为"正常"的订单可以退款
    - 已退款、已取消、已使用的订单不可退款
    - 秒杀券订单遵循同样规则

    Args:
        order_id: 要退款的订单 ID
        reason: 退款原因（可选）

    Returns:
        退款结果描述文本
    """
    logger.info("request_refund: order_id=%s reason=%s", order_id, reason)

    try:
        with get_java_client() as client:
            payload = {"reason": reason}
            response = client.post(
                f"/api/orders/internal/{order_id}/refund",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "退款失败")
            return f"退款失败：{error_msg}"

        data = (result.get("data") if isinstance(result, dict) else None) or {}
        message = data.get("message", "退款申请已提交，款项将退回您的账户。")

        logger.info("Refund processed: order_id=%s", order_id)
        return message

    except httpx.HTTPStatusError as e:
        logger.warning("Refund HTTP error: %s", e)
        try:
            error_data = e.response.json() if e.response else {}
            error_msg = error_data.get("errorMsg", "")
            if error_msg:
                return f"退款失败：{error_msg}"
        except Exception:
            pass
        return f"退款失败（{e.response.status_code if e.response else 500}），请稍后重试。"
    except httpx.HTTPError as e:
        logger.error("Refund network error: %s", e)
        return "网络异常，退款失败，请稍后重试。"
    except Exception:
        logger.exception("Refund unexpected error")
        return "退款服务暂时不可用，请稍后重试。"
