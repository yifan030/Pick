"""Custom middleware for the Pick AI Shopping Guide agent.

Provides:
- LoggingMiddleware: logs intent, latency, and token usage per model call
- ContentSafetyMiddleware: intercepts content_filter flags and replaces unsafe output
"""

import logging
import time
from typing import Any

from langchain.agents.middleware import (
    AgentState,
    ModelRequest,
    ModelResponse,
    before_model,
    after_model,
)
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

logger = logging.getLogger("pick.agent.middleware")


# ── Logging Middleware ──────────────────────────────────────────────

@before_model
def log_before_model(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """记录每次模型调用前的消息数量和当前时间戳."""
    state.setdefault("_log_start", time.monotonic())
    msg_count = len(state.get("messages", []))
    logger.info(
        "model_call_start | messages=%d | session=%s",
        msg_count,
        runtime.config.get("configurable", {}).get("thread_id", "unknown"),
    )
    return None


@after_model
def log_after_model(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """记录模型调用后的延迟和输出长度."""
    start: float = state.pop("_log_start", 0)
    elapsed_ms = (time.monotonic() - start) * 1000 if start else 0
    last_msg = state["messages"][-1] if state.get("messages") else {}
    content_len = len(getattr(last_msg, "content", "") or "")
    logger.info(
        "model_call_end | latency_ms=%.0f | output_chars=%d | session=%s",
        elapsed_ms,
        content_len,
        runtime.config.get("configurable", {}).get("thread_id", "unknown"),
    )
    return None


# ── Content Safety Middleware ───────────────────────────────────────

@after_model
def content_safety_filter(
    state: AgentState, runtime: Runtime
) -> dict[str, Any] | None:
    """检测模型输出是否触发了内容安全审核。

    如果检测到 content_filter 标记，用安全兜底消息替换输出，
    并通过 stream writer 推送 error 事件。
    """
    if not state.get("messages"):
        return None

    last_msg = state["messages"][-1]
    response_metadata = getattr(last_msg, "response_metadata", {}) or {}

    # 检查 OpenAI 风格的 content_filter 标记
    if response_metadata.get("content_filter"):
        logger.warning(
            "content_filter_triggered | session=%s",
            runtime.config.get("configurable", {}).get("thread_id", "unknown"),
        )
        try:
            writer = get_stream_writer()
            writer({"type": "error", "content": "抱歉，我无法回答这个问题"})
        except RuntimeError:
            # 不在 streaming 上下文中（如测试），跳过
            pass
        # 替换不安全内容
        last_msg.content = "抱歉，我无法回答这个问题。"

    return None
