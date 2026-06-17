"""In-store reservation and queue tools for the Pick AI Shopping Guide."""
import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.store.reservation")


@tool
def queue_reservation(shop_id: int, guests: int, user_id: int) -> str:
    """对指定店铺进行现场排队取号。

    适用于用户到店后需要排队的场景（如热门火锅店、KTV等）。

    Args:
        shop_id: 店铺 ID
        guests: 就餐/消费人数
        user_id: 用户 ID

    Returns:
        排队取号结果文本（含排队号）
    """
    logger.info(
        "queue_reservation: shop_id=%s guests=%s user_id=%s",
        shop_id, guests, user_id,
    )

    if guests < 1 or guests > 20:
        return "人数需在 1-20 之间，请确认后再试。"

    try:
        with get_java_client() as client:
            payload = {
                "userId": user_id,
                "shopId": shop_id,
                "type": 0,  # 排队取号
                "guests": guests,
            }
            response = client.post("/api/reservations/internal", json=payload)
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "排队取号失败")
            return error_msg

        data = (result.get("data") if isinstance(result, dict) else None) or {}
        queue_num = data.get("queue_number", "未知")
        msg = data.get("message", f"已为您取号，排队号: {queue_num}")

        return f"{msg}（{guests}人，当前排队号为 {queue_num}）"

    except httpx.HTTPError as e:
        logger.error("queue_reservation error: %s", e)
        return "排队取号失败，请稍后重试。"
    except Exception:
        logger.exception("queue_reservation unexpected error")
        return "排队服务暂时不可用。"


@tool
def make_reservation(shop_id: int, time: str, guests: int, user_id: int, phone: str = "") -> str:
    """对指定店铺进行电话/在线预约。

    适用于用户想提前预约某家店铺的场景（如包厢、桌位预约）。

    Args:
        shop_id: 店铺 ID
        time: 预约时间（ISO 格式，如 \"2026-06-17T19:00\"）
        guests: 人数
        user_id: 用户 ID
        phone: 联系电话（可选）

    Returns:
        预约结果描述文本
    """
    logger.info(
        "make_reservation: shop_id=%s time=%s guests=%s user_id=%s",
        shop_id, time, guests, user_id,
    )

    if not time or time.strip() == "":
        return "请提供预约时间，例如'帮我约今晚7点'。"

    if guests < 1 or guests > 20:
        return "人数需在 1-20 之间，请确认后再试。"

    try:
        with get_java_client() as client:
            payload = {
                "userId": user_id,
                "shopId": shop_id,
                "type": 1,  # 电话预约
                "guests": guests,
                "reserveTime": time,
            }
            if phone:
                payload["phone"] = phone
            response = client.post("/api/reservations/internal", json=payload)
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "预约失败")
            return error_msg

        data = (result.get("data") if isinstance(result, dict) else None) or {}
        msg = data.get("message", "预约已提交，等待店铺确认。")
        rid = data.get("reservation_id", "")

        return f"{msg}\n预约详情：{guests}人，时间 {time}，预约编号 #{rid}"

    except httpx.HTTPError as e:
        logger.error("make_reservation error: %s", e)
        return "预约提交失败，请稍后重试。"
    except Exception:
        logger.exception("make_reservation unexpected error")
        return "预约服务暂时不可用。"
