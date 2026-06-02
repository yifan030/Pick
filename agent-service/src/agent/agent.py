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
from src.agent.middleware import (
    log_before_model,
    log_after_model,
    content_safety_filter,
)
from src.agent.tools import search_shops, query_vouchers, place_order

# ── System Prompt ───────────────────────────────────────────────────

SYSTEM_PROMPT = """你是一个本地生活智能导购助手，服务于 Pick 平台（类大众点评）。你的任务是帮助用户发现合适的店铺、了解优惠券信息，以及完成下单。

## 你的能力

根据用户意图，你可以使用以下工具：

- **search_shops**：搜索匹配用户需求的店铺。当用户想找/搜索/推荐店铺、餐厅、KTV 等本地服务时调用。
  支持按商圈（area）、类型（type_filter）、人均价格（max_price/min_price）、评分（min_score）过滤。
  搜索结果包含店铺基本信息和用户探店笔记。

- **query_vouchers**：查询指定店铺的可用优惠券。当用户对某店铺感兴趣想知道优惠时调用。

- **place_order**：为用户下单购买优惠券。此操作需要用户确认，调用后会等待用户回应。

- 如果用户的意图不属于以上工具覆盖的范围（如闲聊、打招呼、感谢），直接自然友好地回复。

## 回复原则

- 友好、简洁、有温度，像朋友推荐一样
- 推荐时要基于真实数据，绝不编造不存在的店铺
- 给出具体的推荐理由（评分高、人气旺、环境好、有特色等）
- 如果用户提供了位置，优先推荐附近的店铺
- 多轮对话时，自动继承和叠加之前提到的筛选条件
- 用户说"重新推荐"、"从新找"时会清空之前的条件
- 用户提供否定条件时（"不要XX"、"除了XX"），传递给工具对应的过滤参数
- 查券失败或结果为空时，仍然完成店铺推荐，告知用户券信息暂不可用

## 关于你所在的城市

你服务的城市目前以成都为主，商圈包括春熙路、太古里、宽窄巷子、玉林、建设路等。
"""


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
    default_tools = [search_shops, query_vouchers, place_order]
    if tools:
        default_tools.extend(tools)

    # 默认中间件链：日志 → 内容安全 → 重试 → 人机确认
    default_middleware = [
        log_before_model,
        log_after_model,
        content_safety_filter,
        ModelRetryMiddleware(max_retries=3),
        ToolRetryMiddleware(max_retries=2),
        HumanInTheLoopMiddleware(interrupt_on={"place_order": True}),
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
