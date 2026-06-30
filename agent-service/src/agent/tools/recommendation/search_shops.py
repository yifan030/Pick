"""RAG retrieval tool: search shops by semantic vector search + scalar filters."""

import logging

from langchain.tools import tool
from langgraph.config import get_stream_writer

from src.agent.services.milvus import (
    build_filter_expr,
    merge_results,
    search_shop_desc,
    search_user_note,
)
from src.storage.embedding import embed_texts
from src.agent.stream.events import build_shop_card_event, generate_trace_id

logger = logging.getLogger("pick.tools.recommendation")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "�"


def _format_context_for_llm(merged: list[dict]) -> str:
    """Format merged search results as readable text for the LLM context window."""
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

        notes = entry.get("notes", [])
        for j, note in enumerate(notes):
            lines.append(f"   用户评价{j + 1}: 来自 {note.get('user_nickname', '匿名用户')}")

        if i < len(merged):
            lines.append("")

    return "\n".join(lines)


def _build_shop_card(entry: dict, trace_id: str) -> dict:
    """Format a single merged result as a shop_card SSE event with trace_id."""
    shop = entry.get("shop", {})
    return build_shop_card_event(shop=shop, trace_id=trace_id)


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

    try:
        embeddings = embed_texts([query])
        if not embeddings:
            return "（搜索服务暂时不可用）", []
        query_embedding = embeddings[0]
    except Exception as e:
        logger.exception("Embedding failed for query=%s", query)
        return "（搜索服务暂时不可用）", []

    filter_expr = build_filter_expr(
        area=area,
        type_filter=type_filter,
        max_price=max_price,
        min_price=min_price,
        min_score=min_score,
    )

    try:
        shop_hits = search_shop_desc(query_embedding, filter_expr, limit=5)
    except Exception as e:
        logger.exception("Shop search failed")
        shop_hits = []

    try:
        note_hits = search_user_note(query_embedding, limit=3)
    except Exception as e:
        logger.exception("User note search failed")
        note_hits = []

    if not shop_hits and not note_hits:
        return "（搜索服务暂时不可用，请稍后再试）", []

    merged = merge_results(shop_hits, note_hits)

    trace_id = generate_trace_id()
    try:
        writer = get_stream_writer()
        for entry in merged:
            writer(_build_shop_card(entry, trace_id))
    except RuntimeError:
        pass

    context_text = _format_context_for_llm(merged)
    raw_data = [entry["shop"] for entry in merged]

    return context_text, raw_data
