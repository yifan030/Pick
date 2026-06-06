"""Purchase order tool for the Pick AI Shopping Guide.

Provides place_order() – a LangChain @tool that:
- Places a voucher order via the Java backend
- Designed to work with HumanInTheLoopMiddleware for user confirmation
- Handles seckill vouchers (intercept, don't auto-order)
- Returns order result with order ID or error message
"""

import logging
import os

import httpx
from langchain.tools import tool

logger = logging.getLogger("pick.agent.tools.purchase")

# ── Config ───────────────────────────────────────────────────────────

JAVA_BASE_URL = os.environ.get("JAVA_BASE_URL", "http://localhost:8085")
INTERNAL_TOKEN = os.environ.get("SYNC_INTERNAL_TOKEN", "internal-dev-token")
REQUEST_TIMEOUT = 15.0


# ── HTTP Client ──────────────────────────────────────────────────────


def _http_client() -> httpx.Client:
    return httpx.Client(
        base_url=JAVA_BASE_URL,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        timeout=REQUEST_TIMEOUT,
    )


# ── Helpers ──────────────────────────────────────────────────────────

SECKILL_SENTINEL = "SECKILL_NOT_SUPPORTED"
SECKILL_MSG = "秒杀券暂不支持自动下单，请留意秒杀开始时间手动参与"


def _is_seckill_blocked(error_msg: str | None) -> bool:
    """检查 Java 返回的错误是否为秒杀券拦截."""
    return SECKILL_SENTINEL in (error_msg or "")


# ── Main Tool ────────────────────────────────────────────────────────


@tool
def place_order(
    voucher_id: int,
    quantity: int = 1,
    user_id: int | None = None,
    shop_name: str = "",
) -> str:
    """为用户下单购买优惠券。

    此工具会触发人工确认流程（HumanInTheLoopMiddleware）。
    用户必须明确确认后，订单才会真正提交到 Java 后端。

    业务规则：
    - 秒杀券不可自动下单，提示用户手动参与秒杀
    - 普通券库存不足时返回失败原因
    - 下单成功返回订单号和券信息

    Args:
        voucher_id: 优惠券 ID
        quantity: 购买数量（默认 1）
        user_id: 用户 ID
        shop_name: 店铺名称（用于确认语生成）

    Returns:
        下单结果描述文本
    """
    logger.info(
        "place_order: voucher_id=%s quantity=%s user_id=%s shop=%s",
        voucher_id, quantity, user_id, shop_name,
    )

    if quantity < 1:
        return "购买数量无效，请重新指定。"
    if quantity > 100:
        return f"单次最多购买100张，您请求了{quantity}张。"

    # 提交订单（秒杀券检测由 Java InternalVoucherOrderController 负责）
    try:
        with _http_client() as client:
            payload = {
                "quantity": quantity,
                "user_id": user_id,
            }
            response = client.post(
                f"/api/voucher-order/internal/{voucher_id}",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        # Java Result<T> 包装：{success, errorMsg, data}
        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", result.get("message", ""))
            if _is_seckill_blocked(error_msg):
                return SECKILL_MSG
            return error_msg or "下单失败，请稍后重试。"

        # 成功时 data 字段包含 {order_id, message}
        order_data = (result.get("data") if isinstance(result, dict) else None) or {}
        order_id = order_data.get("order_id", order_data.get("id", "未知"))
        message = order_data.get("message", f"下单成功！订单号：{order_id}")

        logger.info("Order placed: order_id=%s voucher_id=%s", order_id, voucher_id)
        return message

    except httpx.HTTPStatusError as e:
        logger.warning("Order HTTP error: %s response=%s", e, e.response.text if e.response else "")
        status_code = e.response.status_code if e.response else 500
        # 尝试从响应中提取业务错误信息
        try:
            error_data = e.response.json() if e.response else {}
            error_msg = error_data.get("errorMsg", error_data.get("message", ""))
            if _is_seckill_blocked(error_msg):
                return SECKILL_MSG
        except Exception:
            pass

        if status_code == 409:
            return "库存不足，下单失败。让我为您推荐其他同类优惠券。"
        elif status_code == 403:
            return "您暂无权限购买此券，请先登录或检查账户状态。"
        else:
            return f"下单失败（{status_code}），请稍后重试。"

    except httpx.HTTPError as e:
        logger.error("Order network error: %s", e)
        return "网络异常，下单失败，请稍后重试。"

    except Exception:
        logger.exception("Order unexpected error")
        return "下单服务暂时不可用，请稍后重试。"
