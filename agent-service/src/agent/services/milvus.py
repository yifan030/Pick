"""Milvus client management and vector search for the Pick AI Shopping Guide.

Provides lazy-singleton MilvusClient, scalar filter builder, search functions
for shop_desc and user_note collections, and result merging by shop_id.
"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from pymilvus import MilvusClient

logger = logging.getLogger("pick.services.milvus")

# ── Milvus config ────────────────────────────────────────────────────

MILVUS_HOST = os.environ.get("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", "19530"))
SHOP_DESC_COLLECTION = "collection_shop_desc"
USER_NOTE_COLLECTION = "collection_user_note"

# ── Type mapping: user-facing sub-type → Milvus type field (大类名) ──

SUB_TYPE_TO_TYPE: dict[str, str] = {
    "火锅": "美食",
    "川渝火锅": "美食",
    "串串香": "美食",
    "川菜": "美食",
    "粤菜": "美食",
    "日料": "美食",
    "日式料理": "美食",
    "韩料": "美食",
    "韩式料理": "美食",
    "烧烤": "美食",
    "烤肉": "美食",
    "西餐": "美食",
    "海鲜": "美食",
    "甜品": "美食",
    "奶茶": "饮品",
    "咖啡": "饮品",
    "茶饮": "饮品",
    "KTV": "休闲娱乐",
    "酒吧": "休闲娱乐",
    "密室逃脱": "休闲娱乐",
    "剧本杀": "休闲娱乐",
    "电影院": "休闲娱乐",
    "健身房": "运动健身",
    "瑜伽": "运动健身",
    "游泳": "运动健身",
    "酒店": "酒店",
    "民宿": "酒店",
}

# Thread pool for sync Milvus calls from async context
_executor = ThreadPoolExecutor(max_workers=4)


# ── Milvus client (lazy) ─────────────────────────────────────────────

_milvus_client: MilvusClient | None = None


def get_milvus_client() -> MilvusClient:
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    return _milvus_client


# ── Filter builder ───────────────────────────────────────────────────


def build_filter_expr(
    area: str | None = None,
    type_filter: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    min_score: float | None = None,
) -> str | None:
    """Build a Milvus scalar filter expression string.

    Args:
        area: 商圈名称 (e.g., "春熙路")
        type_filter: 大类名或子类名 (e.g., "美食" or "火锅")
        max_price: 最高人均价格
        min_price: 最低人均价格
        min_score: 最低评分 (0-5 scale, Milvus stores it ×10)

    Returns:
        Milvus filter expression string, or None if no filters.
    """
    parts: list[str] = []

    if area:
        parts.append(f'area == "{area}"')

    if type_filter:
        # 如果是子类名，映射到大类名
        mapped_type = SUB_TYPE_TO_TYPE.get(type_filter, type_filter)
        parts.append(f'type == "{mapped_type}"')

    if max_price is not None:
        parts.append(f"avg_price <= {max_price}")

    if min_price is not None:
        parts.append(f"avg_price >= {min_price}")

    if min_score is not None:
        # Milvus stores score × 10
        parts.append(f"score >= {int(min_score * 10)}")

    if not parts:
        return None

    return " and ".join(parts)


# ── Search functions ─────────────────────────────────────────────────


def search_shop_desc(
    query_embedding: list[float],
    filter_expr: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search collection_shop_desc for semantically similar shops."""
    client = get_milvus_client()
    results = client.search(
        collection_name=SHOP_DESC_COLLECTION,
        data=[query_embedding],
        limit=limit,
        filter=filter_expr,
        output_fields=[
            "shop_id", "area", "longitude", "latitude",
            "avg_price", "type", "sub_type", "score",
            "open_hours", "tags", "content_type",
        ],
    )
    return _normalize_results(results)


def search_user_note(
    query_embedding: list[float],
    limit: int = 3,
) -> list[dict]:
    """Search collection_user_note for related user reviews."""
    client = get_milvus_client()
    results = client.search(
        collection_name=USER_NOTE_COLLECTION,
        data=[query_embedding],
        limit=limit,
        output_fields=["shop_id", "user_nickname", "content_type"],
    )
    return _normalize_results(results)


def _normalize_results(search_results: list) -> list[dict]:
    """Normalize pymilvus search output into a list of hit dicts."""
    if not search_results:
        return []
    hits = []
    for batch in search_results:
        for hit in batch:
            hits.append({
                "id": hit.get("id"),
                "score": hit.get("distance"),  # COSINE similarity
                "entity": hit.get("entity", {}),
            })
    return hits


# ── Result merging ───────────────────────────────────────────────────


def merge_results(
    shop_hits: list[dict],
    note_hits: list[dict],
) -> list[dict]:
    """Merge shop and user-note search results by shop_id.

    Returns a list of dicts:
        [
            {
                "shop": {...entity fields...},
                "score": float,
                "notes": [{"content_preview": "...", "user_nickname": "...", "score": float}, ...]
            },
            ...
        ]
    Shops with attached user notes are prioritized. Notes whose shop_id
    doesn't match any shop result are included as standalone entries.
    """
    # Build shop lookup
    shops_by_id: dict[int, dict] = {}
    for hit in shop_hits:
        entity = hit.get("entity", {})
        shop_id = entity.get("shop_id")
        if shop_id is not None:
            shops_by_id[shop_id] = {
                "shop": entity,
                "score": hit.get("score", 0.0),
                "notes": [],
            }

    # Attach notes to matching shops
    unmatched_notes: list[dict] = []
    for hit in note_hits:
        entity = hit.get("entity", {})
        shop_id = entity.get("shop_id")
        if shop_id is not None and shop_id in shops_by_id:
            shops_by_id[shop_id]["notes"].append({
                "user_nickname": entity.get("user_nickname", ""),
                "score": hit.get("score", 0.0),
            })
        elif shop_id is not None:
            unmatched_notes.append({
                "shop_id": shop_id,
                "user_nickname": entity.get("user_nickname", ""),
                "score": hit.get("score", 0.0),
            })

    # Sort: shops with notes first, then by score
    result = sorted(
        shops_by_id.values(),
        key=lambda x: (len(x["notes"]) > 0, x["score"]),
        reverse=True,
    )

    return result
