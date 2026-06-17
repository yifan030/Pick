"""Order status and history tools for the Pick AI Shopping Guide."""
import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.commerce.orders")


@tool
def check_order_status(order_id: int) -> str:
    """查询指定订单的当前状态和详情。

    当用户询问"刚才那单怎么样了"、"我的订单什么状态"等关于
    已有订单的问题时调用此工具。

    Args:
        order_id: 订单 ID

    Returns:
        订单状态描述文本，包含券信息、金额、时间等
    """
    logger.info("check_order_status: order_id=%s", order_id)

    try:
        with get_java_client() as client:
            response = client.get(f"/api/orders/internal/{order_id}")
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "订单查询失败")
            return error_msg

        data = (result.get("data") if isinstance(result, dict) else None) or {}
        if not data:
            return "未找到该订单，请确认订单号是否正确。"

        status_text = data.get("status_text", "未知")
        voucher_title = data.get("voucher_title", "未知券")
        pay_amount = data.get("pay_amount", 0)
        create_time = data.get("create_time", "")
        quantity = data.get("quantity", 1)

        lines = [
            f"订单 #{order_id} 详情：",
            f"- 券名称：{voucher_title}",
            f"- 数量：{quantity} 张",
            f"- 实付：¥{pay_amount / 100:.2f}",
            f"- 状态：{status_text}",
        ]
        if create_time:
            lines.append(f"- 下单时间：{create_time}")
        return "\n".join(lines)

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code if e.response else 500
        if status_code == 404:
            return "未找到该订单，请确认订单号是否正确。"
        logger.warning("check_order_status HTTP %s: %s", status_code, e)
        return f"订单查询失败（{status_code}），请稍后重试。"
    except httpx.HTTPError as e:
        logger.error("check_order_status network error: %s", e)
        return "网络异常，订单查询失败，请稍后重试。"
    except Exception:
        logger.exception("check_order_status unexpected error")
        return "订单查询服务暂时不可用，请稍后重试。"


@tool
def list_my_orders(user_id: int, status: str | None = None) -> str:
    """查询用户的历史订单列表。

    当用户询问"我买过哪些券"、"我的订单"、"历史订单"时调用。

    Args:
        user_id: 用户 ID
        status: 可选状态过滤（NORMAL / CANCEL / REFUND / USED）

    Returns:
        格式化的订单列表文本
    """
    logger.info("list_my_orders: user_id=%s status=%s", user_id, status)

    try:
        with get_java_client() as client:
            params = {}
            if status:
                params["status"] = status
            response = client.get(
                f"/api/orders/internal/user/{user_id}", params=params
            )
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            return "订单查询失败，请稍后重试。"

        orders = (result.get("data") if isinstance(result, dict) else None) or []
        if not orders:
            status_hint = f"（状态：{status}）" if status else ""
            return f"您还没有相关订单记录{status_hint}。"

        lines = ["您的订单记录：", ""]
        for i, order in enumerate(orders, 1):
            oid = order.get("order_id", "")
            title = order.get("voucher_title", "未知券")
            amount = order.get("pay_amount", 0)
            create_time = order.get("create_time", "")[:10]
            status_map = {1: "正常", 2: "已取消", 3: "已退款", 4: "已使用"}
            st = status_map.get(order.get("status"), "未知")
            lines.append(
                f"{i}. 订单 #{oid} | {title} | "
                f"¥{amount / 100:.2f} | {st} | {create_time}"
            )

        return "\n".join(lines)

    except httpx.HTTPStatusError as e:
        logger.warning("list_my_orders HTTP error: %s", e)
        return "订单查询失败，请稍后重试。"
    except httpx.HTTPError as e:
        logger.error("list_my_orders network error: %s", e)
        return "网络异常，订单查询失败，请稍后重试。"
    except Exception:
        logger.exception("list_my_orders unexpected error")
        return "订单查询服务暂时不可用，请稍后重试。"
