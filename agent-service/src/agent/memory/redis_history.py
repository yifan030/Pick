"""Redis 对话历史持久化层。

将 LangGraph checkpointer 的消息状态持久化到 Redis：
- 每轮对话结束后序列化消息列表 → Redis（TTL 30min）
- 新会话时从 Redis 恢复历史 → 注入 checkpointer
- Redis 不可用时降级为 in-memory only（不影响本轮对话）
"""

import json
import logging
import os
import uuid

import redis.asyncio as aioredis
from redis.exceptions import RedisError

logger = logging.getLogger("pick.agent.redis_history")

# ── 配置 ────────────────────────────────────────────────────────────

REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB = int(os.environ.get("REDIS_DB", "0"))
SESSION_TTL = 1800  # 30 分钟

KEY_PREFIX = "chat:session:"

# ── 连接缓存 ────────────────────────────────────────────────────────

_redis_client: aioredis.Redis | None = None
_redis_available: bool | None = None  # None=未检测, True=可用, False=不可用


def generate_session_id() -> str:
    """生成新的 UUID v4 会话 ID."""
    return uuid.uuid4().hex


def _session_key(session_id: str) -> str:
    return f"{KEY_PREFIX}{session_id}"


async def _get_redis() -> aioredis.Redis | None:
    """获取或创建 Redis 连接。连接失败时缓存失败状态，避免重复重试."""
    global _redis_client, _redis_available

    # 已确认不可用 → 直接返回 None
    if _redis_available is False:
        return None

    # 已有可用连接 → 返回
    if _redis_client is not None:
        return _redis_client

    # 首次尝试连接
    try:
        _redis_client = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            db=REDIS_DB,
            decode_responses=True,
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
        )
        # 测试连接
        await _redis_client.ping()
        _redis_available = True
        logger.info("Redis connected: %s:%d", REDIS_HOST, REDIS_PORT)
        return _redis_client
    except (RedisError, OSError, ConnectionError, TimeoutError) as e:
        logger.warning("Redis unavailable: %s (operating without history)", e)
        _redis_available = False
        _redis_client = None
        return None


def _serialize_messages(messages: list) -> list[dict]:
    """将 LangChain Message 对象列表序列化为可 JSON 存储的字典列表."""
    result = []
    for msg in messages:
        entry = {
            "role": getattr(msg, "type", "unknown"),
            "content": getattr(msg, "content", ""),
        }
        if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
            shops = msg.additional_kwargs.get("shops")
            if shops:
                entry["shops"] = shops
        result.append(entry)
    return result


def _deserialize_messages(data: list[dict]) -> list[dict]:
    """将 Redis JSON 反序列化为 LangChain 兼容的消息字典列表."""
    result = []
    for entry in data:
        result.append({
            "role": entry.get("role", "user"),
            "content": entry.get("content", ""),
        })
    return result


async def load_history(session_id: str) -> list[dict]:
    """从 Redis 加载会话历史消息。

    失败时返回空列表（不阻塞对话）。
    """
    if not session_id:
        return []

    r = await _get_redis()
    if r is None:
        return []

    try:
        raw = await r.get(_session_key(session_id))
        if raw:
            return _deserialize_messages(json.loads(raw))
    except Exception:
        logger.exception("Failed to load history for session=%s", session_id)

    return []


async def save_history(session_id: str, messages: list) -> None:
    """将消息列表保存到 Redis，设置 30 分钟 TTL。

    messages 应为 LangChain Message 对象列表。
    """
    if not session_id or not messages:
        return

    r = await _get_redis()
    if r is None:
        return

    try:
        serialized = _serialize_messages(messages)
        key = _session_key(session_id)
        await r.set(key, json.dumps(serialized, ensure_ascii=False), ex=SESSION_TTL)
    except Exception:
        logger.exception("Failed to save history for session=%s", session_id)
