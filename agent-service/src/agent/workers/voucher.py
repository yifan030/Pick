"""Voucher worker subgraph -- voucher query, order, refund, alerts."""

from src.agent.tools.schemas import (
    VOUCHER_TOOL_NAMES,
    HITL_TOOLS_BY_WORKER,
    get_tool_schemas_for_worker,
    get_tool_executors_for_worker,
)
from src.agent.workers.base import create_worker

# ── System Prompt ──────────────────────────────────────────────────────────

VOUCHER_SYSTEM_PROMPT = """You are a local lifestyle shopping guide for the Pick platform.

## Capabilities
- Use query_vouchers to find available vouchers for shops
- Use place_order to purchase vouchers (requires user confirmation)
- Use check_order_status / list_my_orders to check order status
- Use request_refund to request refunds (requires user confirmation)
- Use set_voucher_alert to set seckill reminders

## Business Rules
- Seckill vouchers cannot be auto-ordered; advise user to participate manually
- When stock is insufficient, recommend alternative vouchers
- Always confirm price and quantity with user before ordering
"""


def create_worker_voucher():
    """Build a compiled voucher-worker StateGraph."""
    return create_worker(
        name="worker_voucher",
        system_prompt=VOUCHER_SYSTEM_PROMPT,
        tool_schemas=get_tool_schemas_for_worker(VOUCHER_TOOL_NAMES),
        tool_executors=get_tool_executors_for_worker(VOUCHER_TOOL_NAMES),
        hitl_tools=HITL_TOOLS_BY_WORKER.get("worker_voucher", frozenset()),
        max_rounds=6,
        extract_deltas=True,
    )
