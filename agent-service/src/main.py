"""FastAPI application for the Pick AI Shopping Guide agent."""

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from src.agent.agent import create_pick_agent
from src.agent.chat import stream_agent_response
from src.agent.redis_history import (
    generate_session_id,
    load_history,
    save_history,
)

logger = logging.getLogger("pick.main")

# ── Global agent instance (initialized at startup) ──────────────────
_agent = None


def get_agent():
    """返回全局编译好的 agent 实例（懒初始化 + lifespan 预热）."""
    global _agent
    if _agent is None:
        logger.info("Lazy-initializing agent (lifespan not triggered)")
        _agent = create_pick_agent()
    return _agent


# ── Lifespan ────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: 启动时初始化 agent，关闭时清理资源."""
    global _agent
    logger.info("Initializing Pick AI agent...")
    _agent = create_pick_agent()
    logger.info("Agent initialized successfully")
    yield
    logger.info("Shutting down Pick AI agent...")
    _agent = None


# ── FastAPI App ─────────────────────────────────────────────────────

app = FastAPI(title="Pick AI Shopping Guide", lifespan=lifespan)


# ── Request Schema ──────────────────────────────────────────────────


class ChatRequest(BaseModel):
    session_id: str | None = None
    user_id: str | None = None
    query: str
    longitude: float | None = None
    latitude: float | None = None


# ── Endpoints ───────────────────────────────────────────────────────


@app.post("/chat")
async def chat(request: ChatRequest, agent=Depends(get_agent)):
    """主对话端点，返回 SSE 事件流。

    流式处理流程：
    1. 生成或复用 session_id
    2. 从 Redis 加载历史消息
    3. 构建 LangGraph config（thread_id = session_id）
    4. 通过 agent.astream() 流式生成回复
    5. 每个 token 作为 SSE text 事件推送
    6. 结构化事件（shop_card 等）作为 SSE 自定义事件推送
    7. 流结束后保存消息历史到 Redis
    8. 发送 done 事件（携带 session_id）
    """
    session_id = request.session_id or generate_session_id()
    history = await load_history(session_id)
    config = {"configurable": {"thread_id": session_id}}

    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=history,
            agent=agent,
            config=config,
        ):
            yield sse_event

        # 流结束后，保存消息历史到 Redis
        try:
            state = agent.get_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                await save_history(session_id, messages)
        except Exception:
            logger.exception(
                "Failed to save history for session=%s", session_id
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"content-type": "text/event-stream"},
    )


@app.post("/chat/resume")
async def chat_resume(request: ChatRequest, agent=Depends(get_agent)):
    """Resume a conversation after a human-in-the-loop interrupt.

    Used for purchase confirmation flow: after the agent is interrupted
    waiting for user confirmation, the user's "确认" or "取消" response
    is passed as a Command to resume execution.
    """
    session_id = request.session_id
    if not session_id:
        return StreamingResponse(
            _error_stream("Missing session_id for resume"),
            media_type="text/event-stream",
            headers={"content-type": "text/event-stream"},
        )

    config = {"configurable": {"thread_id": session_id}}

    # 检查是否有待处理的中断
    state = agent.get_state(config)
    interrupts = state.tasks[0].interrupts if state and state.tasks else []

    if not interrupts:
        # 没有中断 → 当作普通消息处理
        history = await load_history(session_id)

        async def _generate():
            async for sse_event in stream_agent_response(
                query=request.query,
                history=history,
                agent=agent,
                config=config,
            ):
                yield sse_event

        return StreamingResponse(
            _generate(),
            media_type="text/event-stream",
            headers={"content-type": "text/event-stream"},
        )

    # 确认/取消语义判断
    query_lower = request.query.strip().lower()
    if any(word in query_lower for word in ("确认", "是的", "好的", "下单", "ok", "yes", "confirm")):
        command = Command(resume={"confirmed": True})
    elif any(word in query_lower for word in ("取消", "不要", "算了", "no", "cancel")):
        command = Command(resume={"confirmed": False})
    else:
        command = Command(resume={"confirmed": False, "reason": "unclear"})

    history = await load_history(session_id)

    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=history,
            agent=agent,
            config=config,
            command=command,
        ):
            yield sse_event

        # 保存状态
        try:
            state = agent.get_state(config)
            if state and state.values:
                messages = state.values.get("messages", [])
                await save_history(session_id, messages)
        except Exception:
            logger.exception(
                "Failed to save history for session=%s", session_id
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"content-type": "text/event-stream"},
    )


def _error_stream(message: str):
    """Helper to return an error SSE stream."""
    async def _gen():
        from src.agent.chat import _sse
        yield _sse({"type": "error", "content": message})
        yield _sse({"type": "done"})
    return _gen()


@app.get("/health")
async def health():
    return {"status": "ok"}
