"""RAG retrieval tool for the Pick AI Shopping Guide.

Provides search_shops() – a LangChain @tool that:
- Searches both collection_shop_desc and collection_user_note in Milvus
- Supports scalar filtering (area, type, price range, score)
- Merges results by shop_id (shops + attached user notes)
- Emits shop_card SSE events via get_stream_writer()
- Returns (LLM-readable text, structured shop data) via content_and_artifact
"""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from langchain.tools import tool
from langgraph.config import get_stream_writer
from pymilvus import MilvusClient

from src.ingestion.embedding import embed_texts

logger = logging.getLogger("pick.agent.tools.retrieval")

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


def _get_milvus_client() -> MilvusClient:
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    return _milvus_client


# ── Filter builder ───────────────────────────────────────────────────


def _build_filter_expr(
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


def _search_shop_desc(
    query_embedding: list[float],
    filter_expr: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search collection_shop_desc for semantically similar shops."""
    client = _get_milvus_client()
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


def _search_user_note(
    query_embedding: list[float],
    limit: int = 3,
) -> list[dict]:
    """Search collection_user_note for related user reviews."""
    client = _get_milvus_client()
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


def _merge_results(
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


# ── LLM context formatting ───────────────────────────────────────────


def _format_context_for_llm(merged: list[dict]) -> str:
    """Format merged search results as readable text for the LLM context window.

    Truncates fields to control token usage.
    """
    if not merged:
        return "（未找到匹配的店铺）"

    lines = ["检索到的店铺列表：", ""]
    for i, entry in enumerate(merged, 1):
        shop = entry.get("shop", {})
        name = _truncate(str(shop.get("sub_type", shop.get("type", ""))), 40)
        area = shop.get("area", "")
        avg_price = shop.get("avg_price", "")
        score_val = shop.get("score", 0)
        tags = _truncate(str(shop.get("tags", "")), 100)
        open_hours = _truncate(str(shop.get("open_hours", "")), 50)

        lines.append(
            f"{i}. [{name}] 商圈:{area} | 人均:¥{avg_price} | "
            f"评分:{score_val / 10:.1f} | 标签:{tags} | 营业:{open_hours}"
        )

        # Attach user notes
        notes = entry.get("notes", [])
        for j, note in enumerate(notes):
            lines.append(f"   用户评价{j + 1}: 来自 {note.get('user_nickname', '匿名用户')}")

        if i < len(merged):
            lines.append("")

    return "\n".join(lines)


def _format_shop_card(entry: dict) -> dict:
    """Format a single merged result as a PRD-compliant shop_card SSE event."""
    shop = entry.get("shop", {})
    return {
        "type": "shop_card",
        "data": {
            "shop_id": shop.get("shop_id"),
            "name": shop.get("sub_type", shop.get("type", "")),
            "area": shop.get("area", ""),
            "score": shop.get("score", 0),
            "avg_price": shop.get("avg_price", 0),
            "type": shop.get("type", ""),
            "sub_type": shop.get("sub_type", ""),
            "tags": shop.get("tags", ""),
            "open_hours": shop.get("open_hours", ""),
            "longitude": shop.get("longitude"),
            "latitude": shop.get("latitude"),
        },
    }


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


# ── Main Tool ────────────────────────────────────────────────────────


@tool(response_format="content_and_artifact")
def search_shops(
    query: str,
    area: str | None = None,
    type_filter: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    min_score: float | None = None,
) -> tuple[str, list[dict]]:
    """搜索匹配用户需求的本地生活店铺。

    根据用户查询在向量数据库中执行语义搜索，支持按商圈、类型、价格区间和评分过滤。
    搜索结果包含店铺基本信息和用户探店笔记。

    Args:
        query: 用户查询的自然语言描述（如"适合约会的火锅店"）
        area: 商圈/区域过滤（如"春熙路"、"太古里"）
        type_filter: 店铺类型过滤（如"火锅"、"川菜"、"KTV"）
        max_price: 最高人均价格（元）
        min_price: 最低人均价格（元）
        min_score: 最低评分（0.0-5.0）

    Returns:
        (LLM 可读的文本, 结构化店铺数据列表)
    """
    logger.info(
        "search_shops: query=%s area=%s type=%s max_price=%s",
        query, area, type_filter, max_price,
    )

    # 1. Generate query embedding
    try:
        embeddings = embed_texts([query])
        if not embeddings:
            return "（搜索服务暂时不可用）", []
        query_embedding = embeddings[0]
    except Exception as e:
        logger.exception("Embedding failed for query=%s", query)
        return "（搜索服务暂时不可用）", []

    # 2. Build filter expression
    filter_expr = _build_filter_expr(
        area=area,
        type_filter=type_filter,
        max_price=max_price,
        min_price=min_price,
        min_score=min_score,
    )

    # 3. Search both collections (sequential for now — MilvusClient is sync)
    try:
        shop_hits = _search_shop_desc(query_embedding, filter_expr, limit=5)
    except Exception as e:
        logger.exception("Shop search failed")
        shop_hits = []

    try:
        note_hits = _search_user_note(query_embedding, limit=3)
    except Exception as e:
        logger.exception("User note search failed")
        note_hits = []

    # If both failed, return degradation message
    if not shop_hits and not note_hits:
        return "（搜索服务暂时不可用，请稍后再试）", []

    # 4. Merge results
    merged = _merge_results(shop_hits, note_hits)

    # 5. Emit shop_card SSE events via stream writer
    try:
        writer = get_stream_writer()
        for entry in merged:
            writer(_format_shop_card(entry))
    except RuntimeError:
        # Not in a streaming context (e.g., test or debug)
        pass

    # 6. Format for LLM and return
    context_text = _format_context_for_llm(merged)
    raw_data = [entry["shop"] for entry in merged]

    return context_text, raw_data
