"""Logging middleware: intent, latency, token usage per model call."""

import logging
import time
from typing import Any

from langchain.agents.middleware import (
    AgentState,
    after_model,
    before_model,
)
from langgraph.runtime import Runtime

logger = logging.getLogger("pick.middleware.logging")


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
