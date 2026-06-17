"""Bookmark/shop collection tools for the Pick AI Shopping Guide."""
import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.social.bookmarks")


@tool
def bookmark_shop(shop_id: int, user_id: int) -> str:
    """收藏指定店铺。

    用户可以对感兴趣的店铺进行收藏，收藏后可随时查看。

    Args:
        shop_id: 店铺 ID
        user_id: 用户 ID

    Returns:
        收藏结果描述文本
    """
    logger.info("bookmark_shop: shop_id=%s user_id=%s", shop_id, user_id)

    try:
        with get_java_client() as client:
            payload = {"shop_id": shop_id, "user_id": user_id}
            response = client.post("/api/bookmarks/internal", json=payload)
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "收藏失败")
            return error_msg

        data = (result.get("data") if isinstance(result, dict) else None) or {}
        msg = data.get("message", "已收藏该店铺")
        return msg

    except httpx.HTTPError as e:
        logger.error("bookmark_shop error: %s", e)
        return "收藏失败，请稍后重试。"
    except Exception:
        logger.exception("bookmark_shop unexpected error")
        return "收藏服务暂时不可用。"


@tool
def list_bookmarks(user_id: int) -> str:
    """查看用户的收藏列表。

    列出用户所有已收藏的店铺，包含店铺名称、类型、商圈等信息。

    Args:
        user_id: 用户 ID

    Returns:
        格式化的收藏列表文本
    """
    logger.info("list_bookmarks: user_id=%s", user_id)

    try:
        with get_java_client() as client:
            response = client.get(f"/api/bookmarks/internal/{user_id}")
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            return "查询收藏失败，请稍后重试。"

        bookmarks = (result.get("data") if isinstance(result, dict) else None) or []
        if not bookmarks:
            return "您还没有收藏任何店铺。看到感兴趣的店铺可以对我说'收藏这家店'。"

        lines = ["您的收藏列表：", ""]
        for i, bm in enumerate(bookmarks, 1):
            name = bm.get("shop_name", "未知店铺")
            shop_type = bm.get("shop_type", "")
            area = bm.get("area", "")
            avg_price = bm.get("avg_price", "")
            bid = bm.get("bookmark_id", "")
            lines.append(
                f"{i}. [{shop_type}] {name} | 商圈:{area} | "
                f"人均:¥{avg_price} | 收藏ID:{bid}"
            )
        return "\n".join(lines)

    except httpx.HTTPError as e:
        logger.error("list_bookmarks error: %s", e)
        return "查询收藏失败，请稍后重试。"
    except Exception:
        logger.exception("list_bookmarks unexpected error")
        return "收藏查询暂时不可用。"


@tool
def remove_bookmark(bookmark_id: int) -> str:
    """取消收藏指定店铺。

    用户可以通过收藏 ID 取消对某店铺的收藏。

    Args:
        bookmark_id: 收藏记录 ID（从 list_bookmarks 中获取）

    Returns:
        取消收藏结果文本
    """
    logger.info("remove_bookmark: bookmark_id=%s", bookmark_id)

    try:
        with get_java_client() as client:
            response = client.delete(f"/api/bookmarks/internal/{bookmark_id}")
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", "取消收藏失败")
            return error_msg

        return "已取消收藏该店铺。"

    except httpx.HTTPError as e:
        logger.error("remove_bookmark error: %s", e)
        return "取消收藏失败，请稍后重试。"
    except Exception:
        logger.exception("remove_bookmark unexpected error")
        return "取消收藏服务暂时不可用。"
