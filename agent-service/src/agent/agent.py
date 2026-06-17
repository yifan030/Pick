"""Core agent creation for the Pick AI Shopping Guide.

Uses LangChain's create_agent (not the deprecated create_react_agent) with:
- InMemorySaver for multi-turn conversation state
- Custom middleware for logging and content safety
- Built-in middleware for retry and human-in-the-loop confirmation
- Tools for RAG retrieval and voucher purchase
- System prompt encoding intent routing via native function calling
"""

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
from langgraph.checkpoint.memory import InMemorySaver

from src.agent.config import get_model
from src.agent.middleware.logging import (
    log_before_model,
    log_after_model,
)
from src.agent.middleware.safety import content_safety_filter
from src.agent.tools import (
    search_shops,
    query_vouchers,
    place_order,
    check_order_status,
    list_my_orders,
    request_refund,
)

from src.agent.prompts import SYSTEM_PROMPT


# ── Agent Factory ────────────────────────────────────────────────────

def create_pick_agent(
    tools: list | None = None,
    middleware: list | None = None,
) -> "CompiledAgent":
    """创建 Pick AI 导购 Agent。

    Args:
        tools: 额外的 LangChain @tool 函数（默认包含 search_shops, query_vouchers, place_order）
        middleware: 额外的自定义中间件

    Returns:
        编译好的 LangGraph agent，支持 .stream() 和 .invoke()
    """
    checkpointer = InMemorySaver()

    # 默认工具
    default_tools = [
        search_shops, query_vouchers, place_order,
        check_order_status, list_my_orders, request_refund,
    ]
    if tools:
        default_tools.extend(tools)

    # 默认中间件链：日志 → 内容安全 → 重试 → 人机确认
    default_middleware = [
        log_before_model,
        log_after_model,
        content_safety_filter,
        ModelRetryMiddleware(max_retries=3),
        ToolRetryMiddleware(max_retries=2),
        HumanInTheLoopMiddleware(interrupt_on={
            "place_order": True,
            "request_refund": True,
        }),
    ]
    if middleware:
        default_middleware.extend(middleware)

    agent = create_agent(
        model=get_model(),
        tools=default_tools,
        system_prompt=SYSTEM_PROMPT,
        middleware=default_middleware,
        checkpointer=checkpointer,
    )

    return agent
