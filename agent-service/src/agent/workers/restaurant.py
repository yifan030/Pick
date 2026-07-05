"""Restaurant worker subgraph -- shop search, bookmarks, reservations."""

from src.agent.tools.schemas import (
    RESTAURANT_TOOL_NAMES,
    HITL_TOOLS_BY_WORKER,
    get_tool_schemas_for_worker,
    get_tool_executors_for_worker,
)
from src.agent.workers.base import create_worker

# ── System Prompt ──────────────────────────────────────────────────────────

RESTAURANT_SYSTEM_PROMPT = """You are a local lifestyle shopping guide for the Pick platform.

## Capabilities
- Use search_shops to find shops matching user needs
- Use bookmark_shop / list_bookmarks / remove_bookmark to manage favorites
- Use queue_reservation / make_reservation for queue and reservation

## Response Principles
- Friendly, concise, warm -- like a friend recommending
- Base recommendations on real data, never fabricate shops
- Provide specific reasons (high rating, popular, good atmosphere, unique features)
- Prioritize nearby shops when location is provided
- When no results, suggest broadening search, never fabricate shops
- City: Chengdu, areas include Chunxi Road, Taikoo Li, Kuanzhai Alley, Yulin, Jianshe Road
"""


def create_worker_restaurant():
    """Build a compiled restaurant-worker StateGraph."""
    return create_worker(
        name="worker_restaurant",
        system_prompt=RESTAURANT_SYSTEM_PROMPT,
        tool_schemas=get_tool_schemas_for_worker(RESTAURANT_TOOL_NAMES),
        tool_executors=get_tool_executors_for_worker(RESTAURANT_TOOL_NAMES),
        hitl_tools=HITL_TOOLS_BY_WORKER.get("worker_restaurant", frozenset()),
        max_rounds=8,
        extract_deltas=True,
    )
