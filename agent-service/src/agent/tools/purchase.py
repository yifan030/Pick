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

    # Check for seckill voucher (先通过查券信息判断)
    # 如果 Java 返回秒杀券标识，拦截并提示
    try:
        with _http_client() as client:
            # 先查券详情判断是否为秒杀券
            check_resp = client.get(f"/api/voucher/{voucher_id}")
            if check_resp.status_code == 200:
                voucher_info = check_resp.json()
                if voucher_info.get("is_seckill") or voucher_info.get("type") == "seckill":
                    return (
                        f"「{voucher_info.get('title', '该券')}」为秒杀券，不支持自动下单。"
                        "已为您设置秒杀提醒，请在秒杀开始时手动参与。"
                    )

    except httpx.HTTPError:
        # 查券详情失败不阻塞，继续下单流程
        pass

    # 提交订单
    try:
        with _http_client() as client:
            payload = {
                "voucher_id": voucher_id,
                "quantity": quantity,
                "user_id": user_id,
            }
            response = client.post(
                f"/api/voucher-order/seckill/{voucher_id}",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        order_id = result.get("order_id", result.get("id", "未知"))
        message = result.get("message", f"下单成功！订单号：{order_id}")

        logger.info("Order placed: order_id=%s voucher_id=%s", order_id, voucher_id)
        return message

    except httpx.HTTPStatusError as e:
        logger.warning("Order HTTP error: %s response=%s", e, e.response.text if e.response else "")
        status_code = e.response.status_code if e.response else 500
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
