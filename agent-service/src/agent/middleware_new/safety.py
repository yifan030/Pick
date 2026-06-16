"""Content safety middleware: intercepts content filter flags."""

import logging
from typing import Any

from langchain.agents.middleware import (
    AgentState,
    after_model,
)
from langgraph.config import get_stream_writer
from langgraph.runtime import Runtime

logger = logging.getLogger("pick.middleware.safety")


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

    if response_metadata.get("content_filter"):
        logger.warning(
            "content_filter_triggered | session=%s",
            runtime.config.get("configurable", {}).get("thread_id", "unknown"),
        )
        try:
            writer = get_stream_writer()
            writer({"type": "error", "content": "抱歉，我无法回答这个问题"})
        except RuntimeError:
            pass
        last_msg.content = "抱歉，我无法回答这个问题。"

    return None
