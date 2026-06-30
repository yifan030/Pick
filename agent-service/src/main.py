"""FastAPI application for the Pick AI Shopping Guide agent."""

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from src.agent.agent import create_pick_agent
from src.agent.stream.sse import _sse, stream_agent_response
from src.storage.postgres_saver import PostgresSaverManager

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
    """FastAPI lifespan: 启动时初始化agent和PostgresSaver，关闭时清理资源."""
    global _agent

    # 初始化PostgresSaver
    pg_manager = PostgresSaverManager()
    try:
        await pg_manager.setup()
        saver = pg_manager.create_saver()
        logger.info("PostgresSaver初始化成功")
    except Exception:
        logger.exception("PostgresSaver初始化失败，降级使用InMemorySaver")
        saver = None

    logger.info("Initializing Pick AI agent...")
    _agent = create_pick_agent(checkpointer=saver)
    logger.info("Agent initialized successfully")
    app.state.pg_manager = pg_manager
    yield
    logger.info("Shutting down Pick AI agent...")
    await pg_manager.close()
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
    2. 构建 LangGraph config（thread_id = session_id）
    3. 通过 agent.astream() 流式生成回复
    4. 每个 token 作为 SSE text 事件推送
    5. 结构化事件（shop_card 等）作为 SSE 自定义事件推送
    6. checkpointer 自动持久化对话状态（无需Redis）
    7. 发送 done 事件（携带 session_id）
    """
    session_id = request.session_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id}}

    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=[],  # checkpointer 已完成状态恢复
            agent=agent,
            config=config,
        ):
            yield sse_event

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"content-type": "text/event-stream"},
    )


@app.post("/chat/resume")
async def chat_resume(request: ChatRequest, agent=Depends(get_agent)):
    """恢复被中断的对话（人工确认流程）。

    用于购买确认流程：agent被中断等待用户确认后，
    用户的"确认"或"取消"响应通过Command恢复执行。
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
        # 没有中断 → 当作普通消息处理（checkpointer已有完整上下文）
        async def _generate():
            async for sse_event in stream_agent_response(
                query=request.query,
                history=[],  # checkpointer 已有完整状态
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

    # 有中断时 checkpointer 已有完整上下文
    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=[],  # checkpointer 已有完整状态
            agent=agent,
            config=config,
            command=command,
        ):
            yield sse_event

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"content-type": "text/event-stream"},
    )


def _error_stream(message: str):
    """Helper to return an error SSE stream."""
    async def _gen():
        yield _sse({"type": "error", "content": message})
        yield _sse({"type": "done"})
    return _gen()


@app.get("/health")
async def health():
    return {"status": "ok"}
