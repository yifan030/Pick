"""FastAPI application for the Pick AI Shopping Guide agent."""

# ── MUST be called before any src.* imports — those read env vars at module level ──
from dotenv import load_dotenv

load_dotenv()

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from src.agent.agent import create_pick_agent
from src.agent.stream.sse import _sse, stream_agent_response
from src.memory.pipeline import MemoryPipeline
from src.memory.control.handler import MemoryControlHandler
from src.memory.profile.cold_start import ColdStartManager
from src.retrieval.gateway import RetrievalGateway
from src.retrieval.prompt_builder import PromptBuilder
from src.storage.postgres_saver import PostgresSaverManager
from src.storage.neo4j_client import Neo4jClient
from src.storage.milvus_store import MilvusMemoryStore

logger = logging.getLogger("pick.main")

# ── Global instances (initialized at startup) ─────────────────────────
_agent = None
_pipeline: MemoryPipeline | None = None
_retrieval_gateway: RetrievalGateway | None = None
_prompt_builder = PromptBuilder()

# Per-session round counter for memory extraction
_round_tracker: dict[str, int] = {}


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
    import os

    global _agent, _pipeline, _retrieval_gateway

    # ── PostgresSaver (Plan C) ──
    pg_manager = PostgresSaverManager()
    saver = None
    if os.getenv("POSTGRES_ENABLED", "true").lower() in ("true", "1", "yes"):
        try:
            await pg_manager.setup()
            saver = pg_manager.create_saver()
            logger.info("PostgresSaver initialized")
        except Exception:
            logger.exception("PostgresSaver init failed, falling back to InMemorySaver")
    else:
        logger.info("PostgresSaver skipped (POSTGRES_ENABLED=%s)", os.getenv("POSTGRES_ENABLED"))

    # ── Neo4j Client (Plan A) ──
    neo4j_client = None
    if os.getenv("NEO4J_ENABLED", "true").lower() in ("true", "1", "yes"):
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        neo4j_user = os.getenv("NEO4J_USER", "neo4j")
        neo4j_password = os.getenv("NEO4J_PASSWORD", "neo4j123")
        neo4j_client = Neo4jClient(uri=neo4j_uri, user=neo4j_user, password=neo4j_password)
        try:
            await neo4j_client.connect()
            logger.info("Neo4jClient connected: %s", neo4j_uri)
        except Exception:
            logger.exception("Neo4jClient init failed, falling back to None")
            neo4j_client = None
    else:
        logger.info("Neo4jClient skipped (NEO4J_ENABLED=%s)", os.getenv("NEO4J_ENABLED"))

    # ── Milvus Memory Store (Plan A) ──
    milvus_host = os.getenv("MILVUS_HOST", "localhost")
    milvus_port = int(os.getenv("MILVUS_PORT", "19530"))
    milvus_store = MilvusMemoryStore(host=milvus_host, port=milvus_port)
    try:
        milvus_store.connect()
        created = milvus_store.create_all_collections()
        logger.info("MilvusMemoryStore connected: %s:%s, collections=%s", milvus_host, milvus_port, created)
    except Exception:
        logger.exception("MilvusMemoryStore init failed, falling back to None")
        milvus_store = None

    # ── Cold Start Manager (Plan D) ──
    cold_start_mgr = ColdStartManager(neo4j_client=neo4j_client, java_client=None)
    app.state.cold_start_manager = cold_start_mgr
    logger.info("ColdStartManager initialized (neo4j_client=%s)", "ready" if neo4j_client else "pending")

    # ── Memory Control Handler (Plan D) ──
    memory_control = MemoryControlHandler(neo4j_client=neo4j_client)
    app.state.memory_control = memory_control
    logger.info("MemoryControlHandler initialized (neo4j_client=%s)", "ready" if neo4j_client else "pending")

    # ── Retrieval Gateway (Plan C + D cold start) ──
    _retrieval_gateway = RetrievalGateway(
        milvus_store=milvus_store,
        neo4j_client=neo4j_client,
        cold_start_manager=cold_start_mgr,
    ) if neo4j_client else None
    logger.info("RetrievalGateway initialized (neo4j=%s, milvus=%s, cold_start=%s)",
                "ready" if neo4j_client else "no",
                "ready" if milvus_store else "no",
                "ready" if cold_start_mgr else "no")

    # ── Memory Pipeline (Plan B) ──
    _pipeline = MemoryPipeline(neo4j_client=neo4j_client, milvus_store=milvus_store)
    logger.info("MemoryPipeline initialized (neo4j=%s, milvus=%s)",
                "ready" if neo4j_client else "no",
                "ready" if milvus_store else "no")

    # ── Agent ──
    logger.info("Initializing Pick AI agent...")
    _agent = create_pick_agent(
        checkpointer=saver,
        memory_control_handler=memory_control,
        neo4j_client=neo4j_client,
        retrieval_gateway=_retrieval_gateway,
        prompt_builder=_prompt_builder,
        memory_pipeline=_pipeline,
    )
    logger.info("Agent initialized successfully")

    # ── Feedback Consumer (Kafka) ──
    from src.retrieval.feedback_consumer import FeedbackConsumer

    kafka_bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    feedback_topic = os.getenv("FEEDBACK_TOPIC", "user.behavior.feedback")

    feedback_consumer = FeedbackConsumer(
        neo4j_client=neo4j_client,
        bootstrap_servers=kafka_bootstrap,
        topic=feedback_topic,
    )
    try:
        await feedback_consumer.start()
        consume_task = asyncio.create_task(feedback_consumer.consume_loop())
        app.state.feedback_consumer = feedback_consumer
        app.state.feedback_task = consume_task
        logger.info("FeedbackConsumer started on topic: %s", feedback_topic)
    except Exception:
        logger.warning("Failed to start FeedbackConsumer (Kafka may not be available): %s", exc_info=True)
        app.state.feedback_consumer = None
        app.state.feedback_task = None

    app.state.pg_manager = pg_manager
    app.state.neo4j_client = neo4j_client
    app.state.milvus_store = milvus_store
    yield
    logger.info("Shutting down Pick AI agent...")
    try:
        await pg_manager.close()
    except Exception:
        logger.exception("Error closing PostgresSaver")
    # 关闭 Milvus
    if milvus_store and milvus_store.client:
        try:
            milvus_store.client.close()
            logger.info("MilvusMemoryStore closed")
        except Exception:
            logger.exception("Error closing MilvusMemoryStore")
    # 关闭 Neo4j
    if neo4j_client:
        try:
            await neo4j_client.close()
            logger.info("Neo4jClient closed")
        except Exception:
            logger.exception("Error closing Neo4jClient")
    # 优雅关闭 FeedbackConsumer
    feedback_consumer = getattr(app.state, 'feedback_consumer', None)
    if feedback_consumer:
        await feedback_consumer.stop()
    feedback_task = getattr(app.state, 'feedback_task', None)
    if feedback_task and not feedback_task.done():
        feedback_task.cancel()
        try:
            await feedback_task
        except asyncio.CancelledError:
            pass
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
    session_id = request.session_id or f"pick_{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": session_id}}

    # PostgresSaver 自动恢复 checkpoint，无需手动 load_history
    existing_state = agent.get_state(config)
    is_new_session = not (existing_state and existing_state.values and existing_state.values.get("messages"))

    # 历史消息由 LangGraph checkpoint 管理，此处不再从 Redis 加载
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
        accumulated_text: list[str] = []
        async for sse_event in stream_agent_response(
            query=request.query,
            history=history,
            agent=agent,
            config=config,
            memory_context=memory_context,
        ):
            # Capture text tokens from SSE events for memory extraction
            try:
                data = json.loads(sse_event.removeprefix("data: ").strip())
                if data.get("type") == "text" and data.get("content"):
                    accumulated_text.append(data["content"])
            except (json.JSONDecodeError, AttributeError):
                pass
            yield sse_event

        # PostgresSaver 在 astream() 中自动持久化，无需手动 save_history
        if request.user_id:
            # Track conversation round per session
            round_idx = _round_tracker.get(session_id, 0) + 1
            _round_tracker[session_id] = round_idx

            _trigger_memory_extraction(
                user_id=request.user_id,
                session_id=session_id,
                user_message=request.query,
                assistant_response="".join(accumulated_text),
                round_index=round_idx,
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
        # PostgresSaver checkpoint 已有完整状态，无需从 Redis 加载
        history = []
        is_new = not (state and state.values and state.values.get("messages"))

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


# ── Sync Request Schema ────────────────────────────────────────────────


class SyncRequest(BaseModel):
    full_resync: bool = False


# ── Sync Endpoints ─────────────────────────────────────────────────────


@app.post("/sync/shops")
async def sync_shops(request: SyncRequest):
    """触发店铺描述全量/增量同步 → Milvus（多模态 embedding）。

    从 Java 后端拉取店铺数据，通过 DashScope MultiModalEmbedding
    生成多模态向量（文本 + 图片），写入 Milvus collection_shop_desc。
    """
    milvus_store = getattr(app.state, "milvus_store", None)
    if milvus_store is None:
        return {"status": "error", "message": "Milvus store not available"}

    from src.storage.shop_sync import run_full_shop_desc_sync

    async def _run():
        try:
            count = run_full_shop_desc_sync(full_resync=request.full_resync)
            logger.info("Shop sync completed: %d shops synced", count)
        except Exception:
            logger.exception("Shop sync failed")

    asyncio.create_task(_run())
    return {"status": "started", "message": "Shop sync triggered", "full_resync": request.full_resync}


@app.post("/sync/blogs")
async def sync_blogs(request: SyncRequest):
    """触发探店笔记全量/增量同步 → Milvus（文本 embedding）。

    从 Java 后端拉取博客/笔记数据，通过 DashScope TextEmbedding
    生成文本向量，写入 Milvus collection_user_note。
    """
    milvus_store = getattr(app.state, "milvus_store", None)
    if milvus_store is None:
        return {"status": "error", "message": "Milvus store not available"}

    from src.storage.user_note_sync import run_full_user_note_sync

    async def _run():
        try:
            count = run_full_user_note_sync(full_resync=request.full_resync)
            logger.info("Blog sync completed: %d blogs synced", count)
        except Exception:
            logger.exception("Blog sync failed")

    asyncio.create_task(_run())
    return {"status": "started", "message": "Blog sync triggered", "full_resync": request.full_resync}


@app.post("/sync/entities")
async def sync_entities(request: SyncRequest):
    """触发实体图谱同步 → Neo4j（Shops + Areas + Categories）。

    从 Java 同步端点拉取店铺 → 提取区域和品类 → 在 Neo4j 中
    创建/更新 Shop、Area、Category 节点及关系。
    """
    neo4j_client = getattr(app.state, "neo4j_client", None)
    if neo4j_client is None:
        return {"status": "error", "message": "Neo4j client not available — check NEO4J_ENABLED and connection"}

    from src.sync.entity_sync import sync_all_entities

    async def _run():
        try:
            counts = await sync_all_entities(neo4j_client)
            logger.info("Entity sync completed: %s", counts)
        except Exception:
            logger.exception("Entity sync failed")

    asyncio.create_task(_run())
    return {"status": "started", "message": "Entity sync triggered", "full_resync": request.full_resync}


@app.get("/health")
async def health():
    return {"status": "ok"}
