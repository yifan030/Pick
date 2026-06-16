"""Voucher query tool for the Pick AI Shopping Guide."""

import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.commerce.vouchers")


@tool(response_format="content_and_artifact")
def query_vouchers(
    shop_ids: list[int],
    user_id: int | None = None,
) -> tuple[str, list[dict]]:
    """查询指定店铺的可用优惠券。

    根据店铺 ID 列表查询 Java 后端，获取每个店铺当前可用的优惠券信息，
    包括券名称、面值、库存、使用条件等。

    Args:
        shop_ids: 店铺 ID 列表（最多 10 个）
        user_id: 用户 ID（可选，用于检查用户是否已领取）

    Returns:
        (LLM 可读的券信息文本, 结构化券数据列表)
    """
    if not shop_ids:
        return "（未查询到可用优惠券）", []

    logger.info("query_vouchers: shop_ids=%s user_id=%s", shop_ids, user_id)

    try:
        with get_java_client() as client:
            payload: dict = {"shopIds": shop_ids}
            if user_id is not None:
                payload["userId"] = user_id

            response = client.post(
                "/voucher/available-by-shop-ids",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            logger.warning("Voucher query returned error: %s", result.get("errorMsg"))
            return "（优惠券查询暂时不可用）", []

        shop_vouchers = result.get("data") or {}
        if not isinstance(shop_vouchers, dict):
            shop_vouchers = {}
        all_vouchers: list[dict] = []

        lines = ["可用优惠券：", ""]
        for shop_id_str, vouchers in shop_vouchers.items():
            sid = int(shop_id_str) if isinstance(shop_id_str, str) else shop_id_str
            lines.append(f"店铺 {sid}：")
            for v in vouchers:
                title = v.get("title", v.get("name", "未知券"))
                price = v.get("price", v.get("pay_value", 0))
                stock = v.get("stock", v.get("stock_num", 0))
                condition = v.get("condition", v.get("description", ""))
                lines.append(f"  - {title} | 价格:¥{price} | 库存:{stock} | {condition}")
                all_vouchers.append(v)
            lines.append("")

        if not all_vouchers:
            return "（暂无可用优惠券）", []

        return "\n".join(lines), all_vouchers

    except httpx.HTTPError as e:
        logger.warning("Voucher query HTTP error: %s", e)
        return "（优惠券查询暂时不可用）", []
    except Exception:
        logger.exception("Voucher query failed")
        return "（优惠券查询暂时不可用）", []
