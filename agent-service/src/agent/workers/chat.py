"""Chat worker subgraph -- memory tools only, no domain operations."""

from src.agent.tools.schemas import (
    CHAT_TOOL_NAMES,
    HITL_TOOLS_BY_WORKER,
    get_tool_schemas_for_worker,
    get_tool_executors_for_worker,
)
from src.agent.workers.base import create_worker

# ── System Prompt ──────────────────────────────────────────────────────────

CHAT_SYSTEM_PROMPT = """You are a local lifestyle shopping guide for the Pick platform.

## Your Scope
You are in chat mode with no search tools. You can:
- Engage in friendly conversation (greetings, thanks, farewells)
- Answer general questions about Chengdu lifestyle
- Introduce the shopping guide services available

If the user wants to find shops, guide them to make a specific search request.

## Response Principles
- Friendly, concise, warm
- Never fabricate specific shop information
- Guide users to use the shop search feature
"""


def create_worker_chat():
    """Build a compiled chat-worker StateGraph."""
    return create_worker(
        name="worker_chat",
        system_prompt=CHAT_SYSTEM_PROMPT,
        tool_schemas=get_tool_schemas_for_worker(CHAT_TOOL_NAMES),
        tool_executors=get_tool_executors_for_worker(CHAT_TOOL_NAMES),
        hitl_tools=HITL_TOOLS_BY_WORKER.get("worker_chat", frozenset()),
        max_rounds=3,
        extract_deltas=False,
    )
