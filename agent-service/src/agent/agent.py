"""Core agent for the Pick AI Shopping Guide.

Builds an explicit LangGraph StateGraph with:
1. Intent classification node (recommend_shop / chat / purchase)
2. Conditional routing to specialized sub-agent nodes
3. Each sub-agent has only the tools it needs
4. Streaming support via astream() with v2 protocol
5. Human-in-the-loop for purchase confirmation

Graph topology:
    START → classify_intent
               ↓ (conditional on intent)
        ┌──────┼──────┐
        ↓      ↓      ↓
      chat  recommend purchase
        ↓      ↓      ↓
       END    END    END
"""

import logging
from typing import Annotated, TypedDict

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelRetryMiddleware,
    ToolRetryMiddleware,
)
from langgraph.graph import StateGraph, START, END, add_messages
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage

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
    bookmark_shop,
    list_bookmarks,
    remove_bookmark,
    set_voucher_alert,
    queue_reservation,
    make_reservation,
    create_memory_tools,
)
from src.memory.user_control import MemoryControlHandler

logger = logging.getLogger("pick.agent")

# ── State Schema ─────────────────────────────────────────────────────


class PickAgentState(TypedDict):
    """Shared state across the Pick agent graph.

    messages: conversation history, merged via add_messages reducer.
    intent:   classified user intent – set by classify_intent node,
              read by the conditional routing edge.
    """

    messages: Annotated[list, add_messages]
    intent: str  # "recommend_shop" | "chat" | "purchase"


# ── System Prompts (per branch) ──────────────────────────────────────

RECOMMEND_SYSTEM_PROMPT = """你是一个本地生活智能导购助手，服务于 Pick 平台（类大众点评）。

## 你的任务
根据 search_shops 工具的检索结果，为用户推荐合适的店铺。

## 回复原则
- 友好、简洁、有温度，像朋友推荐一样
- 推荐时要基于真实数据，绝不编造不存在的店铺
- 给出具体的推荐理由（评分高、人气旺、环境好、有特色等）
- 如果用户提供了位置，优先推荐附近的店铺
- 多轮对话时，自动继承和叠加之前提到的筛选条件
- 用户说"重新推荐"、"从新找"时会清空之前的条件
- 用户提供否定条件时（"不要XX"、"除了XX"），传递给工具对应的过滤参数
- 检索结果为空时，告知用户扩大搜索范围，绝不编造店铺
- 查券失败或结果为空时，仍然完成店铺推荐，告知用户券信息暂不可用

## 关于你所在的城市
你服务的城市目前以成都为主，商圈包括春熙路、太古里、宽窄巷子、玉林、建设路等。
"""

CHAT_SYSTEM_PROMPT = """你是一个本地生活智能导购助手，服务于 Pick 平台（类大众点评）。

## 你的能力范围
当前你处于闲聊模式，没有搜索工具可用。你可以：
- 进行友好的日常对话（打招呼、感谢、道别等）
- 回答关于成都本地生活的一般性问题
- 介绍你能提供的导购服务

如果用户希望查找店铺或推荐，请引导用户提出具体的搜索需求，比如"推荐附近的火锅"、"春熙路人均100以内的川菜"等。

## 回复原则
- 友好、简洁、有温度
- 不要编造具体的店铺信息
- 引导用户使用店铺搜索功能
"""

PURCHASE_SYSTEM_PROMPT = """你是一个本地生活智能导购助手，服务于 Pick 平台（类大众点评）。

## 你的任务
帮助用户完成优惠券购买流程。

## 工作流程
1. 如果用户提到了店铺名但没有指定具体券，先使用 query_vouchers 查询该店铺的可用优惠券
2. 向用户展示可用券的信息（名称、价格、使用条件、库存）
3. 用户确认后，使用 place_order 工具下单（此操作需要用户再次确认）
4. 下单成功后在回复中告知用户订单号

## 业务规则
- 秒杀券不支持自动下单，提示用户"秒杀券暂不支持自动下单，已为您设置提醒"
- 普通券库存不足时，推荐同类替代券
- 价格和数量必须明确告知用户，确认后再下单

## 回复原则
- 精确、清晰，涉及金额和券信息时不得有误
- 下单前必须获得用户明确确认
"""

# ── Shared middleware ─────────────────────────────────────────────────

SHARED_MIDDLEWARE = [
    log_before_model,
    log_after_model,
    content_safety_filter,
    ModelRetryMiddleware(max_retries=3),
    ToolRetryMiddleware(max_retries=2),
]

PURCHASE_MIDDLEWARE = [
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

# ── Intent Classification ────────────────────────────────────────────

INTENT_CLASSIFICATION_PROMPT = """你是一个意图分类器。请将以下用户查询分类为**恰好一个**意图。

意图类型：
- **recommend_shop**: 用户想找、搜索、发现、推荐店铺、餐厅、KTV 等本地服务。
  关键词：推荐、找、搜索、附近、好吃、好玩、火锅、餐厅、川菜、约会、聚餐 等
- **purchase**: 用户想买、下单、购买优惠券或代金券。
  关键词：买、下单、购买、券、优惠、帮我订 等
- **chat**: 闲聊、打招呼、感谢、询问助手能力、或其他不属于以上两类的任何内容。
  关键词：你好、谢谢、你是谁、你能做什么、再见 等

请只回复一个词（recommend_shop、chat 或 purchase），不要加任何其他内容。

用户查询：{query}"""


def _classify_intent(query: str) -> str:
    """Invoke LLM for intent classification.

    Uses a lightweight few-shot-style prompt to keep latency low.
    Returns one of: "recommend_shop", "chat", "purchase".
    """
    model = get_model()
    prompt = INTENT_CLASSIFICATION_PROMPT.format(query=query)
    try:
        response = model.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip().lower()
    except Exception:
        logger.exception("Intent classification failed, defaulting to chat")
        return "chat"

    # Robust parsing: extract the intent even if LLM adds extra text
    if "purchase" in raw:
        return "purchase"
    elif "recommend" in raw or "shop" in raw:
        return "recommend_shop"
    else:
        return "chat"


# ── Graph Builder ────────────────────────────────────────────────────


def create_pick_agent(
    checkpointer=None,
    memory_control_handler: MemoryControlHandler | None = None,
    neo4j_client=None,
) -> "CompiledStateGraph":
    """Build and compile the Pick AI Shopping Guide agent graph.

    Args:
        checkpointer: A LangGraph checkpointer instance.
                    如果为None，则降级使用InMemorySaver（非持久化）。
        memory_control_handler: Optional MemoryControlHandler instance.
            When provided together with neo4j_client, memory control
            tools (view/delete/update/clear/ignore preferences) are
            wired into every sub-agent.
        neo4j_client: Neo4jClient instance required for memory tools.
            Only used when memory_control_handler is also provided.

    The compiled graph exposes:
    - .astream(input, config)  → async streaming iterator
    - .ainvoke(input, config)  → async single invocation
    - .get_state(config)       → retrieve current conversation state
    """
    model = get_model()

    if checkpointer is None:
        checkpointer = InMemorySaver()
        logger.warning("未提供checkpointer，使用InMemorySaver（非持久化）")

    # ── Sub-agents ──────────────────────────────────────────────────

    # Base tools per intent branch
    chat_tools: list = []
    recommend_tools = [
        search_shops,
        bookmark_shop,
        list_bookmarks,
        remove_bookmark,
        queue_reservation,
        make_reservation,
    ]
    purchase_tools = [
        query_vouchers,
        place_order,
        check_order_status,
        list_my_orders,
        request_refund,
        set_voucher_alert,
    ]

    # Wire memory control tools into all branches when handler + client are available
    if memory_control_handler is not None and neo4j_client is not None:
        memory_tools = create_memory_tools(memory_control_handler, neo4j_client)
        chat_tools.extend(memory_tools)
        recommend_tools.extend(memory_tools)
        purchase_tools.extend(memory_tools)
        logger.info(
            "Memory control tools wired into agent (%d tools)",
            len(memory_tools),
        )

    chat_handler = create_agent(
        model=model,
        tools=chat_tools,
        system_prompt=CHAT_SYSTEM_PROMPT,
        middleware=SHARED_MIDDLEWARE,
        name="chat_handler",
    )

    recommend_handler = create_agent(
        model=model,
        tools=recommend_tools,
        system_prompt=RECOMMEND_SYSTEM_PROMPT,
        middleware=SHARED_MIDDLEWARE,
        name="recommend_handler",
    )

    purchase_handler = create_agent(
        model=model,
        tools=purchase_tools,
        system_prompt=PURCHASE_SYSTEM_PROMPT,
        middleware=PURCHASE_MIDDLEWARE,
        name="purchase_handler",
    )

    # ── Intent classification node ──────────────────────────────────

    def classify_intent(state: PickAgentState) -> dict:
        """Extract the latest user message and classify intent.

        This node does NOT modify the message history – it only sets
        the ``intent`` field used by the downstream conditional edge.
        """
        messages = state.get("messages", [])
        if not messages:
            logger.debug("No messages in state, defaulting to chat")
            return {"intent": "chat"}

        # Find the most recent HumanMessage
        last_msg = messages[-1]
        query = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

        intent = _classify_intent(query)
        logger.info(
            "Intent classified: intent=%s query=%.80s",
            intent,
            query,
        )
        return {"intent": intent}

    # ── Conditional routing ─────────────────────────────────────────

    def route_by_intent(state: PickAgentState) -> str:
        """Return the name of the next node based on classified intent."""
        intent = state.get("intent", "chat")
        # Normalize in case LLM returns unexpected variant
        if intent not in ("recommend_shop", "chat", "purchase"):
            logger.warning(
                "Unknown intent '%s', falling back to chat", intent
            )
            intent = "chat"
        return intent

    # ── Assemble graph ──────────────────────────────────────────────

    builder = StateGraph(PickAgentState)

    builder.add_node("classify_intent", classify_intent)
    builder.add_node("chat_handler", chat_handler)
    builder.add_node("recommend_handler", recommend_handler)
    builder.add_node("purchase_handler", purchase_handler)

    builder.add_edge(START, "classify_intent")
    builder.add_conditional_edges(
        "classify_intent",
        route_by_intent,
        {
            "chat": "chat_handler",
            "recommend_shop": "recommend_handler",
            "purchase": "purchase_handler",
        },
    )
    builder.add_edge("chat_handler", END)
    builder.add_edge("recommend_handler", END)
    builder.add_edge("purchase_handler", END)

    return builder.compile(checkpointer=checkpointer)
