"""SSE formatting and streaming for the Pick AI agent."""

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
    """Stream agent response as SSE events.

    Uses agent.stream() with v2 streaming protocol:
    - stream_mode="messages" → token-level text chunks
    - stream_mode="custom" → structured events (shop_card, status, etc.)

    Args:
        query: The current user query text.
        history: Previous messages loaded from Redis (list of {role, content} dicts).
        agent: A compiled LangGraph agent from create_pick_agent().
        config: LangGraph config dict with thread_id for checkpointing.
        command: Optional Command for resuming after human-in-the-loop interrupts.

    Yields:
        SSE-formatted strings (data: {...}\n\n)
    """
    input_messages = history + [{"role": "user", "content": query}]

    stream_input = {"messages": input_messages}
    if command is not None:
        stream_input["command"] = command

    try:
        async for chunk in agent.astream(
            stream_input,
            config=config,
            stream_mode=["messages", "custom"],
            version="v2",
        ):
            chunk_type = chunk.get("type")

            if chunk_type == "messages":
                data = chunk.get("data", (None, None))
                token = data[0] if isinstance(data, tuple) else None
                if token is None:
                    continue
                content = getattr(token, "content", None)
                if content:
                    yield _sse({"type": "text", "content": content})

            elif chunk_type == "custom":
                custom_data = chunk.get("data")
                if isinstance(custom_data, dict):
                    yield _sse(custom_data)
                else:
                    logger.debug("non-dict custom event: %s", type(custom_data))

    except Exception:
        logger.exception(
            "Agent stream error for session=%s",
            config.get("configurable", {}).get("thread_id"),
        )
        yield _sse({"type": "error", "content": "抱歉，服务暂时不可用，请稍后再试"})

    session_id = config.get("configurable", {}).get("thread_id", "")
    yield _sse({"type": "done", "session_id": session_id})
