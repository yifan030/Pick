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
from src.agent.memory.redis_history import (
    generate_session_id,
    load_history,
    save_history,
)
from src.retrieval.gateway import RetrievalGateway
from src.retrieval.prompt_builder import PromptBuilder
from src.storage.postgres_saver import PostgresSaverManager

logger = logging.getLogger("pick.main")

# ── Global agent instance (initialized at startup) ──────────────────
_agent = None
_retrieval_gateway: RetrievalGateway | None = None
_prompt_builder = PromptBuilder()


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
    """FastAPI lifespan: 启动时初始化agent、PostgresSaver、RetrievalGateway，关闭时清理资源."""
    global _agent, _retrieval_gateway

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

    # RetrievalGateway requires milvus_store and neo4j_client
    # These will be wired when Plan A storage is fully initialized
    _retrieval_gateway = None  # TODO: wire when Milvus + Neo4j are ready

    logger.info("Agent initialized successfully")
    app.state.pg_manager = pg_manager
    yield
    logger.info("Shutting down Pick AI agent...")
    await pg_manager.close()
    _agent = None
    _retrieval_gateway = None


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
    2. 从 Redis 加载历史消息（checkpointer 降级恢复）
    3. 新会话时执行记忆检索（语义 + BM25 + 实体增强）
    4. 构建 LangGraph config（thread_id = session_id）
    5. 通过 agent.astream() 流式生成回复
    6. 每个 token 作为 SSE text 事件推送
    7. 结构化事件（shop_card 等）作为 SSE 自定义事件推送
    8. checkpointer 自动持久化对话状态
    9. 发送 done 事件（携带 session_id）
    """
    session_id = request.session_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id}}

    # 避免消息重复：如果 checkpointer 已有该 thread_id 的状态（同进程生命周期内），
    # 则只用 checkpointer 的历史；否则从 Redis 恢复（进程重启后的恢复）。
    existing_state = agent.get_state(config)
    is_new_session = not (existing_state and existing_state.values and existing_state.values.get("messages"))

    if is_new_session:
        history = await load_history(session_id)
    else:
        history = []

    # 新会话时执行记忆检索
    memory_context = ""
    if is_new_session and _retrieval_gateway and request.user_id:
        try:
            retrieval_result = await _retrieval_gateway.retrieve(
                user_id=request.user_id,
                query=request.query,
                is_new_session=True,
            )
            memory_context = _prompt_builder.build(
                profiles=retrieval_result["profiles"],
                hard_constraints=retrieval_result["hard_constraints"],
                memories=retrieval_result["memories"],
            )
            logger.debug("Memory context built: %d chars", len(memory_context))
        except Exception:
            logger.exception("Retrieval failed, continuing without memories")

    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=history,
            agent=agent,
            config=config,
            memory_context=memory_context,
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
        # 没有中断 → 当作普通消息处理
        if state and state.values and state.values.get("messages"):
            history = []
            is_new = False
        else:
            history = await load_history(session_id)
            is_new = True

        memory_context = ""
        if is_new and _retrieval_gateway and request.user_id:
            try:
                retrieval_result = await _retrieval_gateway.retrieve(
                    user_id=request.user_id,
                    query=request.query,
                    is_new_session=True,
                )
                memory_context = _prompt_builder.build(
                    profiles=retrieval_result["profiles"],
                    hard_constraints=retrieval_result["hard_constraints"],
                    memories=retrieval_result["memories"],
                )
            except Exception:
                logger.exception("Retrieval failed in resume, continuing without memories")

        async def _generate():
            async for sse_event in stream_agent_response(
                query=request.query,
                history=history,
                agent=agent,
                config=config,
                memory_context=memory_context,
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
