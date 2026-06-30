"""FastAPI application for the Pick AI Shopping Guide agent."""

import asyncio
import logging
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
from src.memory.pipeline import MemoryPipeline
from src.retrieval.gateway import RetrievalGateway
from src.retrieval.prompt_builder import PromptBuilder
from src.storage.neo4j_client import Neo4jClient
from src.storage.milvus_store import MilvusMemoryStore
from src.storage.postgres_saver import PostgresSaverManager

logger = logging.getLogger("pick.main")

# ── Global instances (initialized at startup) ─────────────────────────
_agent = None
_pipeline: MemoryPipeline | None = None
_retrieval_gateway: RetrievalGateway | None = None
_prompt_builder = PromptBuilder()


def get_agent():
    """返回全局编译好的 agent 实例（懒初始化 + lifespan 预热）."""
    global _agent
    if _agent is None:
        logger.info("Lazy-initializing agent (lifespan not triggered)")
        _agent = create_pick_agent()
    return _agent


# ── Memory Extraction (Plan B) ────────────────────────────────────────


def _trigger_memory_extraction(
    user_id: str,
    session_id: str,
    user_message: str,
    assistant_response: str,
    tool_calls: str = "",
    round_index: int = 1,
    recommendations: str = "",
    user_feedback: str = "",
):
    """Schedule memory extraction as a background task (non-blocking)."""
    if _pipeline is None:
        logger.warning("MemoryPipeline not initialized, skipping extraction")
        return

    async def _run():
        try:
            await _pipeline.extract_memories(
                user_id=user_id,
                session_id=session_id,
                user_message=user_message,
                assistant_response=assistant_response,
                tool_calls=tool_calls,
                round_index=round_index,
                recommendations=recommendations,
                user_feedback=user_feedback,
            )
        except Exception:
            logger.exception("Background memory extraction failed")

    asyncio.create_task(_run())


# ── Lifespan ──────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: 启动时初始化所有组件，关闭时清理资源."""
    global _agent, _pipeline, _retrieval_gateway
    import os

    # ── Storage Clients (Plan A) ──
    neo4j = Neo4jClient(
        uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        user=os.environ.get("NEO4J_USER", "neo4j"),
        password=os.environ.get("NEO4J_PASSWORD", "password"),
    )
    milvus = MilvusMemoryStore(
        host=os.environ.get("MILVUS_HOST", "localhost"),
        port=int(os.environ.get("MILVUS_PORT", "19530")),
    )
    try:
        await neo4j.connect()
        milvus.connect()
        milvus.create_all_collections()
        logger.info("Neo4j + Milvus connected")
    except Exception:
        logger.exception("Storage init failed — memory pipeline will be degraded")

    # ── PostgresSaver (Plan C) ──
    pg_manager = PostgresSaverManager()
    saver = None
    try:
        await pg_manager.setup()
        saver = pg_manager.create_saver()
        logger.info("PostgresSaver initialized")
    except Exception:
        logger.exception("PostgresSaver init failed, falling back to InMemorySaver")

    # ── Agent ──
    logger.info("Initializing Pick AI agent...")
    _agent = create_pick_agent(checkpointer=saver)
    logger.info("Agent initialized successfully")

    # ── Retrieval Gateway (Plan C) + Memory Pipeline (Plan B) ──
    _retrieval_gateway = RetrievalGateway(
        neo4j_client=neo4j,
        milvus_store=milvus,
    )
    _pipeline = MemoryPipeline(neo4j_client=neo4j, milvus_store=milvus)
    logger.info("RetrievalGateway + MemoryPipeline initialized")

    app.state.pg_manager = pg_manager
    yield
    logger.info("Shutting down Pick AI agent...")
    try:
        await pg_manager.close()
    except Exception:
        logger.exception("Error closing PostgresSaver")
    try:
        await neo4j.close()
    except Exception:
        logger.exception("Error closing Neo4j")
    _agent = None
    _pipeline = None
    _retrieval_gateway = None


# ── FastAPI App ───────────────────────────────────────────────────────

app = FastAPI(title="Pick AI Shopping Guide", lifespan=lifespan)


# ── Request Schema ────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    session_id: str | None = None
    user_id: str | None = None
    query: str
    longitude: float | None = None
    latitude: float | None = None


# ── Helpers ────────────────────────────────────────────────────────────


async def _save_history_safe(agent, config: dict, session_id: str) -> None:
    """将当前 agent 状态中的消息持久化到 Redis，失败时仅记录日志."""
    try:
        state = agent.get_state(config)
        if state and state.values:
            messages = state.values.get("messages", [])
            await save_history(session_id, messages)
    except Exception:
        logger.exception("Failed to save history for session=%s", session_id)


def _error_stream(message: str):
    """Helper to return an error SSE stream."""
    async def _gen():
        yield _sse({"type": "error", "content": message})
        yield _sse({"type": "done"})
    return _gen()


# ── Endpoints ─────────────────────────────────────────────────────────


@app.post("/chat")
async def chat(request: ChatRequest, agent=Depends(get_agent)):
    """主对话端点，返回 SSE 事件流。

    流式处理流程：
    1. 生成或复用 session_id
    2. 从 Redis 加载历史消息（checkpointer 降级恢复）
    3. 新会话时执行记忆检索（Plan C: 语义 + BM25 + 实体增强）
    4. 构建 LangGraph config（thread_id = session_id）
    5. 通过 agent.astream() 流式生成回复
    6. 每个 token 作为 SSE text 事件推送
    7. 流结束后触发记忆提取（Plan B: 后台异步）
    8. 发送 done 事件（携带 session_id）
    """
    session_id = request.session_id or generate_session_id()
    config = {"configurable": {"thread_id": session_id}}

    # 避免消息重复
    existing_state = agent.get_state(config)
    is_new_session = not (existing_state and existing_state.values and existing_state.values.get("messages"))

    if is_new_session:
        history = await load_history(session_id)
    else:
        history = []

    # 新会话时执行记忆检索 (Plan C)
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

        # 流结束后保存历史到 Redis + 触发记忆提取 (Plan B)
        await _save_history_safe(agent, config, session_id)
        if request.user_id:
            _trigger_memory_extraction(
                user_id=request.user_id,
                session_id=session_id,
                user_message=request.query,
                assistant_response="",  # TODO: collect from SSE stream
                round_index=1,           # TODO: track conversation round
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"content-type": "text/event-stream"},
    )


@app.post("/chat/resume")
async def chat_resume(request: ChatRequest, agent=Depends(get_agent)):
    """恢复被中断的对话（人工确认流程）。"""
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
                logger.exception("Retrieval failed in resume")

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

    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=[],
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


@app.get("/health")
async def health():
    return {"status": "ok"}
