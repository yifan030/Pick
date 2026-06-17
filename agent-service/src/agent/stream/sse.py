"""SSE formatting and streaming for the Pick AI agent.

Uses LangGraph v3 astream_events for structured event streaming with
built-in interrupt detection.
"""

import json
import logging

from langgraph.types import Command

logger = logging.getLogger("pick.stream.sse")


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


async def stream_agent_response(
    query: str,
    history: list[dict],
    agent,
    config: dict,
    *,
    command: Command | None = None,
) -> str:
    """Stream agent response as SSE events via LangGraph v3 event streaming.

    Uses agent.astream_events() with v3 protocol:
    - Raw "messages" events → token-level text deltas
    - Raw "custom" events → structured events (shop_card, status, etc.)
    - stream.interrupted → human-in-the-loop interrupt detection

    Args:
        query: The current user query text.
        history: Previous messages (list of {role, content} dicts).
        agent: A compiled LangGraph agent from create_pick_agent().
        config: LangGraph config dict with thread_id for checkpointing.
        command: Optional Command for resuming after human-in-the-loop interrupts.

    Yields:
        SSE-formatted strings (data: {...}\n\n)
    """
    if command is not None:
        stream_input = command
    else:
        input_messages = history + [{"role": "user", "content": query}]
        stream_input = {"messages": input_messages}

    try:
        stream = await agent.astream_events(
            stream_input,
            config=config,
            version="v3",
        )
        async for event in stream:
            method = event.get("method", "")

            if method == "messages":
                data = event.get("params", {}).get("data")
                token = data[0] if isinstance(data, tuple) else None
                if token is None:
                    continue
                content = getattr(token, "content", None)
                if content:
                    yield _sse({"type": "text", "content": content})

            elif method == "custom":
                custom_data = event.get("params", {}).get("data")
                if isinstance(custom_data, dict):
                    yield _sse(custom_data)

    except Exception:
        logger.exception(
            "Agent stream error for session=%s",
            config.get("configurable", {}).get("thread_id"),
        )
        yield _sse({"type": "error", "content": "抱歉，服务暂时不可用，请稍后再试"})

    session_id = config.get("configurable", {}).get("thread_id", "")
    yield _sse({"type": "done", "session_id": session_id})
