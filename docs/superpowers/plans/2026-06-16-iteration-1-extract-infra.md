# Iteration 1: Extract Shared Infrastructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganize agent directory from flat structure to domain-layered structure, extract shared services (Milvus, HTTP client), zero behavior changes.

**Architecture:** Pure restructure — move code from flat files into domain directories, split large files, unify duplicated patterns. No logic changes, no new features.

**Tech Stack:** Python, LangChain, httpx, pymilvus, Redis

---

## File Structure Map

### Files to create (9 directories + 8 .py files)

```
agent-service/src/agent/
  prompts/__init__.py
  prompts/system_prompt.py          ← SYSTEM_PROMPT from agent.py
  middleware/__init__.py
  middleware/logging.py             ← log_before/after_model from middleware.py
  middleware/safety.py              ← content_safety_filter from middleware.py
  stream/__init__.py
  stream/sse.py                    ← _sse() + stream_agent_response() from chat.py
  stream/events.py                 ← event type constants (new)
  memory/__init__.py               ← move from agent/ level
  memory/redis_history.py          ← move from agent/redis_history.py (no edits)
  tools/recommendation/__init__.py
  tools/recommendation/search_shops.py   ← @tool + formatters from retrieval.py
  tools/commerce/__init__.py
  tools/commerce/query_vouchers.py       ← @tool from voucher.py (use java_client)
  tools/commerce/place_order.py          ← @tool from purchase.py (use java_client)
  tools/social/__init__.py               ← empty placeholder for iteration 3
  tools/store/__init__.py                ← empty placeholder for iteration 4
  services/__init__.py
  services/milvus.py                ← Milvus client + search + filter from retrieval.py
  services/java_client.py           ← unified httpx client from voucher.py + purchase.py
```

### Files to modify (4)

```
agent-service/src/agent/agent.py               ← update imports, remove SYSTEM_PROMPT string
agent-service/src/agent/tools/__init__.py       ← update imports to new paths
agent-service/src/main.py                       ← update import paths
agent-service/src/agent/tools/retrieval.py      ← strip to thin @tool
agent-service/src/agent/tools/voucher.py        ← strip to thin @tool
agent-service/src/agent/tools/purchase.py       ← strip to thin @tool
```

### Files to delete after verification (4)

```
agent-service/src/agent/middleware.py           ← split into logging.py + safety.py
agent-service/src/agent/chat.py                 ← moved to stream/sse.py
agent-service/src/agent/redis_history.py        ← moved to memory/
```

### Files that stay unchanged

```
agent-service/src/agent/config.py
agent-service/tests/test_chat.py               ← no behavior changes, tests should pass as-is
```

---

## Task 1: Create directory structure

**Files:**
- Create all new empty `__init__.py` files and blank placeholder modules.

- [ ] **Step 1: Create all new directories**

```bash
mkdir -p agent-service/src/agent/prompts
mkdir -p agent-service/src/agent/middleware_new
mkdir -p agent-service/src/agent/stream
mkdir -p agent-service/src/agent/memory
mkdir -p agent-service/src/agent/tools/recommendation
mkdir -p agent-service/src/agent/tools/commerce
mkdir -p agent-service/src/agent/tools/social
mkdir -p agent-service/src/agent/tools/store
mkdir -p agent-service/src/agent/services
```

Note: `middleware_new` is temporary — will become `middleware` after old file is deleted. Use a rename-safe name to avoid import conflicts.

- [ ] **Step 2: Create all `__init__.py` files**

Create with empty content. Use these Write commands:

```bash
# All __init__.py files initially empty — they'll be populated in later tasks
touch agent-service/src/agent/prompts/__init__.py
touch agent-service/src/agent/middleware_new/__init__.py
touch agent-service/src/agent/stream/__init__.py
touch agent-service/src/agent/memory/__init__.py
touch agent-service/src/agent/tools/recommendation/__init__.py
touch agent-service/src/agent/tools/commerce/__init__.py
touch agent-service/src/agent/tools/social/__init__.py
touch agent-service/src/agent/tools/store/__init__.py
touch agent-service/src/agent/services/__init__.py
```

- [ ] **Step 3: Commit**

```bash
git add agent-service/src/agent/prompts/ agent-service/src/agent/middleware_new/ agent-service/src/agent/stream/ agent-service/src/agent/memory/ agent-service/src/agent/tools/recommendation/ agent-service/src/agent/tools/commerce/ agent-service/src/agent/tools/social/ agent-service/src/agent/tools/store/ agent-service/src/agent/services/
git commit -m "chore: create new agent directory structure for domain separation"
```

---

## Task 2: Extract `services/java_client.py`

**Files:**
- Create: `agent-service/src/agent/services/java_client.py`
- Modify: `agent-service/src/agent/services/__init__.py`

Unify the duplicated HTTP client pattern from `tools/voucher.py` and `tools/purchase.py` into a single class.

- [ ] **Step 1: Write `services/java_client.py`**

```python
"""Shared HTTP client for Java backend internal APIs.

Provides a singleton httpx.Client with unified auth header, base URL,
and timeout. All @tool functions that call the Java backend should
use get_java_client() instead of creating their own httpx.Client.
"""

import logging
import os

import httpx

logger = logging.getLogger("pick.services.java_client")

# Config
JAVA_BASE_URL = os.environ.get("JAVA_BASE_URL", "http://localhost:8085")
INTERNAL_TOKEN = os.environ.get("SYNC_INTERNAL_TOKEN", "internal-dev-token")
REQUEST_TIMEOUT = 15.0  # seconds (accommodates slowest endpoint)


def get_java_client(timeout: float | None = None) -> httpx.Client:
    """Return a configured httpx.Client for Java internal API calls.

    The client is created on each call (httpx.Client is not thread-safe).
    Callers should use it as a context manager:

        with get_java_client() as client:
            response = client.get("/api/...")

    Args:
        timeout: Override default timeout in seconds. If None, uses
                 REQUEST_TIMEOUT (15.0).
    """
    return httpx.Client(
        base_url=JAVA_BASE_URL,
        headers={"X-Internal-Token": INTERNAL_TOKEN},
        timeout=timeout or REQUEST_TIMEOUT,
    )
```

- [ ] **Step 2: Update `services/__init__.py`**

Write content for `agent-service/src/agent/services/__init__.py`:

```python
from src.agent.services.java_client import get_java_client

__all__ = ["get_java_client"]
```

(Will add Milvus exports in Task 3.)

- [ ] **Step 3: Commit**

```bash
git add agent-service/src/agent/services/java_client.py agent-service/src/agent/services/__init__.py
git commit -m "feat: add shared Java HTTP client service"
```

---

## Task 3: Extract `services/milvus.py`

**Files:**
- Create: `agent-service/src/agent/services/milvus.py`
- Modify: `agent-service/src/agent/services/__init__.py`

Move Milvus client management, filter builder, search functions, and result merger from `tools/retrieval.py` to `services/milvus.py`. Keep the original `tools/retrieval.py` intact during this task — we'll strip it in Task 6.

The content to move is lines 24-238 from `tools/retrieval.py` (everything from `MILVUS_HOST` to `return result`, inclusive), plus the `SUB_TYPE_TO_TYPE` dict and `_executor`. 

- [ ] **Step 1: Create `services/milvus.py`**

Write content — extract from `tools/retrieval.py`, keeping `__init__.py` untouched until later:

```python
"""Milvus vector search service for the Pick AI Shopping Guide.

Provides MilvusClient singleton management, scalar filter building,
dual-collection search (shop_desc + user_note), and result merging.
"""
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from pymilvus import MilvusClient

logger = logging.getLogger("pick.services.milvus")

# ── Config ────────────────────────────────────────────────────────────

MILVUS_HOST = os.environ.get("MILVUS_HOST", "localhost")
MILVUS_PORT = int(os.environ.get("MILVUS_PORT", "19530"))
SHOP_DESC_COLLECTION = "collection_shop_desc"
USER_NOTE_COLLECTION = "collection_user_note"

# Thread pool for sync Milvus calls from async context
_executor = ThreadPoolExecutor(max_workers=4)

# ── Type mapping ──────────────────────────────────────────────────────

SUB_TYPE_TO_TYPE: dict[str, str] = {
    "火锅": "美食",
    "川渝火锅": "美食",
    "串串香": "美食",
    "川菜": "美食",
    "粤菜": "美食",
    "日料": "美食",
    "日式料理": "美食",
    "韩料": "美食",
    "韩式料理": "美食",
    "烧烤": "美食",
    "烤肉": "美食",
    "西餐": "美食",
    "海鲜": "美食",
    "甜品": "美食",
    "奶茶": "饮品",
    "咖啡": "饮品",
    "茶饮": "饮品",
    "KTV": "休闲娱乐",
    "酒吧": "休闲娱乐",
    "密室逃脱": "休闲娱乐",
    "剧本杀": "休闲娱乐",
    "电影院": "休闲娱乐",
    "健身房": "运动健身",
    "瑜伽": "运动健身",
    "游泳": "运动健身",
    "酒店": "酒店",
    "民宿": "酒店",
}

# ── Milvus client (lazy singleton) ────────────────────────────────────

_milvus_client: MilvusClient | None = None


def get_milvus_client() -> MilvusClient:
    """Return a lazy-initialized MilvusClient singleton."""
    global _milvus_client
    if _milvus_client is None:
        _milvus_client = MilvusClient(uri=f"http://{MILVUS_HOST}:{MILVUS_PORT}")
    return _milvus_client


# ── Filter builder ────────────────────────────────────────────────────

def build_filter_expr(
    area: str | None = None,
    type_filter: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    min_score: float | None = None,
) -> str | None:
    """Build a Milvus scalar filter expression string.

    Args:
        area: 商圈名称 (e.g., "春熙路")
        type_filter: 大类名或子类名 (e.g., "美食" or "火锅")
        max_price: 最高人均价格
        min_price: 最低人均价格
        min_score: 最低评分 (0-5 scale, Milvus stores it ×10)

    Returns:
        Milvus filter expression string, or None if no filters.
    """
    parts: list[str] = []

    if area:
        parts.append(f'area == "{area}"')

    if type_filter:
        mapped_type = SUB_TYPE_TO_TYPE.get(type_filter, type_filter)
        parts.append(f'type == "{mapped_type}"')

    if max_price is not None:
        parts.append(f"avg_price <= {max_price}")

    if min_price is not None:
        parts.append(f"avg_price >= {min_price}")

    if min_score is not None:
        parts.append(f"score >= {int(min_score * 10)}")

    if not parts:
        return None

    return " and ".join(parts)


# ── Search functions ──────────────────────────────────────────────────

def search_shop_desc(
    query_embedding: list[float],
    filter_expr: str | None = None,
    limit: int = 5,
) -> list[dict]:
    """Search collection_shop_desc for semantically similar shops."""
    client = get_milvus_client()
    results = client.search(
        collection_name=SHOP_DESC_COLLECTION,
        data=[query_embedding],
        limit=limit,
        filter=filter_expr,
        output_fields=[
            "shop_id", "area", "longitude", "latitude",
            "avg_price", "type", "sub_type", "score",
            "open_hours", "tags", "content_type",
        ],
    )
    return _normalize_results(results)


def search_user_note(
    query_embedding: list[float],
    limit: int = 3,
) -> list[dict]:
    """Search collection_user_note for related user reviews."""
    client = get_milvus_client()
    results = client.search(
        collection_name=USER_NOTE_COLLECTION,
        data=[query_embedding],
        limit=limit,
        output_fields=["shop_id", "user_nickname", "content_type"],
    )
    return _normalize_results(results)


def _normalize_results(search_results: list) -> list[dict]:
    """Normalize pymilvus search output into a list of hit dicts."""
    if not search_results:
        return []
    hits = []
    for batch in search_results:
        for hit in batch:
            hits.append({
                "id": hit.get("id"),
                "score": hit.get("distance"),
                "entity": hit.get("entity", {}),
            })
    return hits


# ── Result merging ────────────────────────────────────────────────────

def merge_results(
    shop_hits: list[dict],
    note_hits: list[dict],
) -> list[dict]:
    """Merge shop and user-note search results by shop_id.

    Returns a list of dicts:
        [
            {
                "shop": {...entity fields...},
                "score": float,
                "notes": [{"user_nickname": "...", "score": float}, ...]
            },
            ...
        ]
    Shops with attached user notes are prioritized.
    """
    shops_by_id: dict[int, dict] = {}
    for hit in shop_hits:
        entity = hit.get("entity", {})
        shop_id = entity.get("shop_id")
        if shop_id is not None:
            shops_by_id[shop_id] = {
                "shop": entity,
                "score": hit.get("score", 0.0),
                "notes": [],
            }

    for hit in note_hits:
        entity = hit.get("entity", {})
        shop_id = entity.get("shop_id")
        if shop_id is not None and shop_id in shops_by_id:
            shops_by_id[shop_id]["notes"].append({
                "user_nickname": entity.get("user_nickname", ""),
                "score": hit.get("score", 0.0),
            })
        elif shop_id is not None:
            # Notes whose shop_id doesn't match any shop result
            pass

    result = sorted(
        shops_by_id.values(),
        key=lambda x: (len(x["notes"]) > 0, x["score"]),
        reverse=True,
    )

    return result
```

- [ ] **Step 2: Update `services/__init__.py`**

```python
from src.agent.services.java_client import get_java_client
from src.agent.services.milvus import (
    build_filter_expr,
    get_milvus_client,
    merge_results,
    search_shop_desc,
    search_user_note,
    SUB_TYPE_TO_TYPE,
)

__all__ = [
    "get_java_client",
    "get_milvus_client",
    "build_filter_expr",
    "merge_results",
    "search_shop_desc",
    "search_user_note",
    "SUB_TYPE_TO_TYPE",
]
```

- [ ] **Step 3: Commit**

```bash
git add agent-service/src/agent/services/
git commit -m "feat: extract Milvus client and search functions to services/milvus.py"
```

---

## Task 4: Split middleware into separate files

**Files:**
- Create: `agent-service/src/agent/middleware_new/logging.py`
- Create: `agent-service/src/agent/middleware_new/safety.py`
- Modify: `agent-service/src/agent/middleware_new/__init__.py`

Copy from `middleware.py`, no logic changes. One middleware per file.

- [ ] **Step 1: Write `middleware_new/logging.py`**

Extract `log_before_model` and `log_after_model` exactly as they are, update the logger name:

```python
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
```

- [ ] **Step 2: Write `middleware_new/safety.py`**

```python
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
```

- [ ] **Step 3: Write `middleware_new/__init__.py`**

```python
from src.agent.middleware_new.logging import log_before_model, log_after_model
from src.agent.middleware_new.safety import content_safety_filter

__all__ = ["log_before_model", "log_after_model", "content_safety_filter"]
```

- [ ] **Step 4: Commit**

```bash
git add agent-service/src/agent/middleware_new/
git commit -m "refactor: split middleware into logging.py and safety.py"
```

---

## Task 5: Create `stream/` module (formerly `chat.py`)

**Files:**
- Create: `agent-service/src/agent/stream/events.py`
- Create: `agent-service/src/agent/stream/sse.py`
- Modify: `agent-service/src/agent/stream/__init__.py`

Split the old `chat.py` into event type constants + SSE formatting + streaming logic.

- [ ] **Step 1: Write `stream/events.py`**

```python
"""SSE event type constants for the Pick AI agent streaming protocol."""

# Core event types
TEXT = "text"
SHOP_CARD = "shop_card"
ERROR = "error"
DONE = "done"
STATUS = "status"
```

- [ ] **Step 2: Write `stream/sse.py`**

Move `_sse()` and `stream_agent_response()` from `chat.py`, update the import:

```python
"""SSE formatting and streaming for the Pick AI agent."""

import json
import logging

from langgraph.types import Command

logger = logging.getLogger("pick.stream.sse")


def _sse(data: dict) -> str:
    """Format a dict as an SSE data line (no trailing newline after \n\n)."""
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
```

- [ ] **Step 3: Write `stream/__init__.py`**

```python
from src.agent.stream.sse import _sse, stream_agent_response
from src.agent.stream import events

__all__ = ["_sse", "stream_agent_response", "events"]
```

- [ ] **Step 4: Commit**

```bash
git add agent-service/src/agent/stream/
git commit -m "refactor: extract stream module from chat.py"
```

---

## Task 6: Extract `prompts/system_prompt.py` from `agent.py`

**Files:**
- Create: `agent-service/src/agent/prompts/system_prompt.py`
- Modify: `agent-service/src/agent/prompts/__init__.py`
- Modify: `agent-service/src/agent/agent.py` (import from prompts, remove inline string)

- [ ] **Step 1: Write `prompts/system_prompt.py`**

```python
"""System prompt for the Pick AI Shopping Guide agent.

Extracted from agent.py to support focused iteration on prompt engineering
with readable git diffs.
"""

SYSTEM_PROMPT = """你是一个本地生活智能导购助手，服务于 Pick 平台（类大众点评）。你的任务是帮助用户发现合适的店铺、了解优惠券信息，以及完成下单。

## 你的能力

根据用户意图，你可以使用以下工具：

- **search_shops**：搜索匹配用户需求的店铺。当用户想找/搜索/推荐店铺、餐厅、KTV 等本地服务时调用。
  支持按商圈（area）、类型（type_filter）、人均价格（max_price/min_price）、评分（min_score）过滤。
  搜索结果包含店铺基本信息和用户探店笔记。

- **query_vouchers**：查询指定店铺的可用优惠券。当用户对某店铺感兴趣想知道优惠时调用。

- **place_order**：为用户下单购买优惠券。此操作需要用户确认，调用后会等待用户回应。

- 如果用户的意图不属于以上工具覆盖的范围（如闲聊、打招呼、感谢），直接自然友好地回复。

## 回复原则

- 友好、简洁、有温度，像朋友推荐一样
- 推荐时要基于真实数据，绝不编造不存在的店铺
- 给出具体的推荐理由（评分高、人气旺、环境好、有特色等）
- 如果用户提供了位置，优先推荐附近的店铺
- 多轮对话时，自动继承和叠加之前提到的筛选条件
- 用户说"重新推荐"、"从新找"时会清空之前的条件
- 用户提供否定条件时（"不要XX"、"除了XX"），传递给工具对应的过滤参数
- 查券失败或结果为空时，仍然完成店铺推荐，告知用户券信息暂不可用

## 关于你所在的城市

你服务的城市目前以成都为主，商圈包括春熙路、太古里、宽窄巷子、玉林、建设路等。
"""
```

- [ ] **Step 2: Write `prompts/__init__.py`**

```python
from src.agent.prompts.system_prompt import SYSTEM_PROMPT

__all__ = ["SYSTEM_PROMPT"]
```

- [ ] **Step 3: Update `agent.py` imports**

In `agent.py`, remove the `SYSTEM_PROMPT = """..."""` string definition (lines 29-59) and replace with:

```python
from src.agent.prompts import SYSTEM_PROMPT
```

Also update the middleware import from `from src.agent.middleware import (...)` to:

```python
from src.agent.middleware_new.logging import (
    log_before_model,
    log_after_model,
)
from src.agent.middleware_new.safety import content_safety_filter
```

(The `config import get_model` and `tools import ...` stay unchanged.)

- [ ] **Step 4: Verify — run the agent test suite**

```bash
cd agent-service && python -m pytest tests/ -v
```

All tests should pass since no behavior changed.

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/agent/prompts/ agent-service/src/agent/agent.py agent-service/src/agent/middleware_new/
git commit -m "refactor: extract system prompt to prompts/ module"
```

---

## Task 7: Move `redis_history.py` into `memory/`

**Files:**
- Copy: `agent-service/src/agent/redis_history.py` → `agent-service/src/agent/memory/redis_history.py`
- Modify: `agent-service/src/agent/memory/__init__.py`
- Modify: `agent-service/src/main.py` (update import)
- Delete: `agent-service/src/agent/redis_history.py` (after verifying)

- [ ] **Step 1: Copy `redis_history.py` into `memory/`**

```bash
cp agent-service/src/agent/redis_history.py agent-service/src/agent/memory/redis_history.py
```

No code changes in the file itself.

- [ ] **Step 2: Update `memory/__init__.py`**

```python
from src.agent.memory.redis_history import (
    generate_session_id,
    load_history,
    save_history,
)

__all__ = ["generate_session_id", "load_history", "save_history"]
```

- [ ] **Step 3: Update `main.py` import**

Change:
```python
from src.agent.redis_history import (
    generate_session_id,
    load_history,
    save_history,
)
```

To:
```python
from src.agent.memory.redis_history import (
    generate_session_id,
    load_history,
    save_history,
)
```

- [ ] **Step 4: Run tests to verify**

```bash
cd agent-service && python -m pytest tests/test_chat.py -v
```

- [ ] **Step 5: Delete old file and commit**

```bash
rm agent-service/src/agent/redis_history.py
git add agent-service/src/agent/memory/ agent-service/src/agent/redis_history.py agent-service/src/main.py
git commit -m "refactor: move redis_history.py into memory/ module"
```

---

## Task 8: Update `main.py` stream imports

**Files:**
- Modify: `agent-service/src/main.py`

Replace `from src.agent.chat import stream_agent_response` and the `_error_stream` internal reference.

- [ ] **Step 1: Update main.py imports**

Change line 12:
```python
from src.agent.chat import stream_agent_response
```
To:
```python
from src.agent.stream.sse import _sse, stream_agent_response
```

Change line 205 inside `_error_stream()`:
```python
from src.agent.chat import _sse
```
To direct reference `_sse` (since it's now imported at module level).

- [ ] **Step 2: Run full test suite**

```bash
cd agent-service && python -m pytest tests/ -v
```

- [ ] **Step 3: Commit**

```bash
git add agent-service/src/main.py
git commit -m "refactor: update main.py to use new stream.sse and memory imports"
```

---

## Task 9: Rewrite tools into domain subdirectories

**Files:**
- Create: `agent-service/src/agent/tools/recommendation/search_shops.py` (from retrieval.py)
- Create: `agent-service/src/agent/tools/commerce/query_vouchers.py` (from voucher.py)
- Create: `agent-service/src/agent/tools/commerce/place_order.py` (from purchase.py)
- Modify: `agent-service/src/agent/tools/__init__.py` (update imports)
- Modify: `agent-service/src/agent/tools/recommendation/__init__.py`
- Modify: `agent-service/src/agent/tools/commerce/__init__.py`

Each new tool file is a thin wrapper: just the @tool function + formatting helpers. It imports services for infra and keeps only LLM-facing logic.

- [ ] **Step 1: Write `tools/recommendation/search_shops.py`**

```python
"""RAG retrieval tool: search shops by semantic vector search + scalar filters."""

import logging

from langchain.tools import tool
from langgraph.config import get_stream_writer

from src.agent.services.milvus import (
    build_filter_expr,
    merge_results,
    search_shop_desc,
    search_user_note,
)
from src.ingestion.embedding import embed_texts

logger = logging.getLogger("pick.tools.recommendation")


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


def _format_context_for_llm(merged: list[dict]) -> str:
    """Format merged search results as readable text for the LLM context window."""
    if not merged:
        return "（未找到匹配的店铺）"

    lines = ["检索到的店铺列表：", ""]
    for i, entry in enumerate(merged, 1):
        shop = entry.get("shop", {})
        name = _truncate(str(shop.get("sub_type", shop.get("type", ""))), 40)
        area = shop.get("area", "")
        avg_price = shop.get("avg_price", "")
        score_val = shop.get("score", 0)
        tags = _truncate(str(shop.get("tags", "")), 100)
        open_hours = _truncate(str(shop.get("open_hours", "")), 50)

        lines.append(
            f"{i}. [{name}] 商圈:{area} | 人均:¥{avg_price} | "
            f"评分:{score_val / 10:.1f} | 标签:{tags} | 营业:{open_hours}"
        )

        notes = entry.get("notes", [])
        for j, note in enumerate(notes):
            lines.append(f"   用户评价{j + 1}: 来自 {note.get('user_nickname', '匿名用户')}")

        if i < len(merged):
            lines.append("")

    return "\n".join(lines)


def _format_shop_card(entry: dict) -> dict:
    """Format a single merged result as a shop_card SSE event."""
    shop = entry.get("shop", {})
    return {
        "type": "shop_card",
        "data": {
            "shop_id": shop.get("shop_id"),
            "name": shop.get("sub_type", shop.get("type", "")),
            "area": shop.get("area", ""),
            "score": shop.get("score", 0),
            "avg_price": shop.get("avg_price", 0),
            "type": shop.get("type", ""),
            "sub_type": shop.get("sub_type", ""),
            "tags": shop.get("tags", ""),
            "open_hours": shop.get("open_hours", ""),
            "longitude": shop.get("longitude"),
            "latitude": shop.get("latitude"),
        },
    }


@tool(response_format="content_and_artifact")
def search_shops(
    query: str,
    area: str | None = None,
    type_filter: str | None = None,
    max_price: int | None = None,
    min_price: int | None = None,
    min_score: float | None = None,
) -> tuple[str, list[dict]]:
    """搜索匹配用户需求的本地生活店铺。

    根据用户查询在向量数据库中执行语义搜索，支持按商圈、类型、价格区间和评分过滤。
    搜索结果包含店铺基本信息和用户探店笔记。

    Args:
        query: 用户查询的自然语言描述（如"适合约会的火锅店"）
        area: 商圈/区域过滤（如"春熙路"、"太古里"）
        type_filter: 店铺类型过滤（如"火锅"、"川菜"、"KTV"）
        max_price: 最高人均价格（元）
        min_price: 最低人均价格（元）
        min_score: 最低评分（0.0-5.0）

    Returns:
        (LLM 可读的文本, 结构化店铺数据列表)
    """
    logger.info(
        "search_shops: query=%s area=%s type=%s max_price=%s",
        query, area, type_filter, max_price,
    )

    try:
        embeddings = embed_texts([query])
        if not embeddings:
            return "（搜索服务暂时不可用）", []
        query_embedding = embeddings[0]
    except Exception as e:
        logger.exception("Embedding failed for query=%s", query)
        return "（搜索服务暂时不可用）", []

    filter_expr = build_filter_expr(
        area=area,
        type_filter=type_filter,
        max_price=max_price,
        min_price=min_price,
        min_score=min_score,
    )

    try:
        shop_hits = search_shop_desc(query_embedding, filter_expr, limit=5)
    except Exception as e:
        logger.exception("Shop search failed")
        shop_hits = []

    try:
        note_hits = search_user_note(query_embedding, limit=3)
    except Exception as e:
        logger.exception("User note search failed")
        note_hits = []

    if not shop_hits and not note_hits:
        return "（搜索服务暂时不可用，请稍后再试）", []

    merged = merge_results(shop_hits, note_hits)

    try:
        writer = get_stream_writer()
        for entry in merged:
            writer(_format_shop_card(entry))
    except RuntimeError:
        pass

    context_text = _format_context_for_llm(merged)
    raw_data = [entry["shop"] for entry in merged]

    return context_text, raw_data
```

- [ ] **Step 2: Write `tools/commerce/query_vouchers.py`**

```python
"""Voucher query tool for the Pick AI Shopping Guide."""

import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.commerce.vouchers")


@tool(response_format="content_and_artifact")
def query_vouchers(
    shop_ids: list[int],
    user_id: int | None = None,
) -> tuple[str, list[dict]]:
    """查询指定店铺的可用优惠券。

    根据店铺 ID 列表查询 Java 后端，获取每个店铺当前可用的优惠券信息，
    包括券名称、面值、库存、使用条件等。

    Args:
        shop_ids: 店铺 ID 列表（最多 10 个）
        user_id: 用户 ID（可选，用于检查用户是否已领取）

    Returns:
        (LLM 可读的券信息文本, 结构化券数据列表)
    """
    if not shop_ids:
        return "（未查询到可用优惠券）", []

    logger.info("query_vouchers: shop_ids=%s user_id=%s", shop_ids, user_id)

    try:
        with get_java_client() as client:
            payload: dict = {"shopIds": shop_ids}
            if user_id is not None:
                payload["userId"] = user_id

            response = client.post(
                "/voucher/available-by-shop-ids",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            logger.warning("Voucher query returned error: %s", result.get("errorMsg"))
            return "（优惠券查询暂时不可用）", []

        shop_vouchers = result.get("data") or {}
        if not isinstance(shop_vouchers, dict):
            shop_vouchers = {}
        all_vouchers: list[dict] = []

        lines = ["可用优惠券：", ""]
        for shop_id_str, vouchers in shop_vouchers.items():
            sid = int(shop_id_str) if isinstance(shop_id_str, str) else shop_id_str
            lines.append(f"店铺 {sid}：")
            for v in vouchers:
                title = v.get("title", v.get("name", "未知券"))
                price = v.get("price", v.get("pay_value", 0))
                stock = v.get("stock", v.get("stock_num", 0))
                condition = v.get("condition", v.get("description", ""))
                lines.append(f"  - {title} | 价格:¥{price} | 库存:{stock} | {condition}")
                all_vouchers.append(v)
            lines.append("")

        if not all_vouchers:
            return "（暂无可用优惠券）", []

        return "\n".join(lines), all_vouchers

    except httpx.HTTPError as e:
        logger.warning("Voucher query HTTP error: %s", e)
        return "（优惠券查询暂时不可用）", []
    except Exception:
        logger.exception("Voucher query failed")
        return "（优惠券查询暂时不可用）", []
```

- [ ] **Step 3: Write `tools/commerce/place_order.py`**

```python
"""Purchase order tool for the Pick AI Shopping Guide."""

import logging

import httpx
from langchain.tools import tool

from src.agent.services.java_client import get_java_client

logger = logging.getLogger("pick.tools.commerce.orders")

SECKILL_SENTINEL = "SECKILL_NOT_SUPPORTED"
SECKILL_MSG = "秒杀券暂不支持自动下单，请留意秒杀开始时间手动参与"


def _is_seckill_blocked(error_msg: str | None) -> bool:
    return SECKILL_SENTINEL in (error_msg or "")


@tool
def place_order(
    voucher_id: int,
    quantity: int = 1,
    user_id: int | None = None,
    shop_name: str = "",
) -> str:
    """为用户下单购买优惠券。

    此工具会触发人工确认流程（HumanInTheLoopMiddleware）。
    用户必须明确确认后，订单才会真正提交到 Java 后端。

    业务规则：
    - 秒杀券不可自动下单，提示用户手动参与秒杀
    - 普通券库存不足时返回失败原因
    - 下单成功返回订单号和券信息

    Args:
        voucher_id: 优惠券 ID
        quantity: 购买数量（默认 1）
        user_id: 用户 ID
        shop_name: 店铺名称（用于确认语生成）

    Returns:
        下单结果描述文本
    """
    logger.info(
        "place_order: voucher_id=%s quantity=%s user_id=%s shop=%s",
        voucher_id, quantity, user_id, shop_name,
    )

    if quantity < 1:
        return "购买数量无效，请重新指定。"
    if quantity > 100:
        return f"单次最多购买100张，您请求了{quantity}张。"

    try:
        with get_java_client() as client:
            payload = {
                "quantity": quantity,
                "user_id": user_id,
            }
            response = client.post(
                f"/api/voucher-order/internal/{voucher_id}",
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        if isinstance(result, dict) and result.get("success") is False:
            error_msg = result.get("errorMsg", result.get("message", ""))
            if _is_seckill_blocked(error_msg):
                return SECKILL_MSG
            return error_msg or "下单失败，请稍后重试。"

        order_data = (result.get("data") if isinstance(result, dict) else None) or {}
        order_id = order_data.get("order_id", order_data.get("id", "未知"))
        message = order_data.get("message", f"下单成功！订单号：{order_id}")

        logger.info("Order placed: order_id=%s voucher_id=%s", order_id, voucher_id)
        return message

    except httpx.HTTPStatusError as e:
        logger.warning("Order HTTP error: %s response=%s", e, e.response.text if e.response else "")
        status_code = e.response.status_code if e.response else 500
        try:
            error_data = e.response.json() if e.response else {}
            error_msg = error_data.get("errorMsg", error_data.get("message", ""))
            if _is_seckill_blocked(error_msg):
                return SECKILL_MSG
        except Exception:
            pass

        if status_code == 409:
            return "库存不足，下单失败。让我为您推荐其他同类优惠券。"
        elif status_code == 403:
            return "您暂无权限购买此券，请先登录或检查账户状态。"
        else:
            return f"下单失败（{status_code}），请稍后重试。"

    except httpx.HTTPError as e:
        logger.error("Order network error: %s", e)
        return "网络异常，下单失败，请稍后重试。"

    except Exception:
        logger.exception("Order unexpected error")
        return "下单服务暂时不可用，请稍后重试。"
```

- [ ] **Step 4: Write `tools/recommendation/__init__.py`**

```python
from src.agent.tools.recommendation.search_shops import search_shops

__all__ = ["search_shops"]
```

- [ ] **Step 5: Write `tools/commerce/__init__.py`**

```python
from src.agent.tools.commerce.query_vouchers import query_vouchers
from src.agent.tools.commerce.place_order import place_order

__all__ = ["query_vouchers", "place_order"]
```

- [ ] **Step 6: Write `tools/social/__init__.py`** (placeholder)

```python
"""Social domain tools: bookmarks, alerts, reviews, sharing (iteration 3 & 5)."""

__all__: list[str] = []
```

- [ ] **Step 7: Write `tools/store/__init__.py`** (placeholder)

```python
"""Store/visit domain tools: reservation, navigation (iteration 4)."""

__all__: list[str] = []
```

- [ ] **Step 8: Update `tools/__init__.py`**

Change imports to new paths:

```python
"""Agent tools for the Pick AI Shopping Guide.

Tools by domain:
- recommendation/search_shops: Dual-collection RAG retrieval
- commerce/query_vouchers: Query available vouchers from Java backend
- commerce/place_order: Place a voucher order (triggers HumanInTheLoopMiddleware)
"""

from src.agent.tools.recommendation.search_shops import search_shops
from src.agent.tools.commerce.query_vouchers import query_vouchers
from src.agent.tools.commerce.place_order import place_order

__all__ = ["search_shops", "query_vouchers", "place_order"]
```

- [ ] **Step 9: Run full test suite**

```bash
cd agent-service && python -m pytest tests/ -v
```

All tests must pass — no behavior has changed.

- [ ] **Step 10: Commit**

```bash
git add agent-service/src/agent/tools/
git commit -m "refactor: reorganize tools into domain subdirectories"
```

---

## Task 10: Final cleanup — remove old files and rename middleware_new

**Files:**
- Delete: `agent-service/src/agent/chat.py`
- Delete: `agent-service/src/agent/middleware.py`
- Delete: `agent-service/src/agent/tools/retrieval.py`
- Delete: `agent-service/src/agent/tools/voucher.py`
- Delete: `agent-service/src/agent/tools/purchase.py`
- Rename: `agent-service/src/agent/middleware_new/` → `agent-service/src/agent/middleware/`

- [ ] **Step 1: Delete old files**

```bash
rm agent-service/src/agent/chat.py
rm agent-service/src/agent/middleware.py
rm agent-service/src/agent/tools/retrieval.py
rm agent-service/src/agent/tools/voucher.py
rm agent-service/src/agent/tools/purchase.py
```

- [ ] **Step 2: Rename middleware_new → middleware**

```bash
rmdir agent-service/src/agent/middleware 2>/dev/null; mv agent-service/src/agent/middleware_new agent-service/src/agent/middleware
```

- [ ] **Step 3: Update `agent.py` import path**

Change `from src.agent.middleware_new.logging` / `middleware_new.safety` to `from src.agent.middleware.logging` / `middleware.safety`:

```python
from src.agent.middleware.logging import (
    log_before_model,
    log_after_model,
)
from src.agent.middleware.safety import content_safety_filter
```

- [ ] **Step 4: Run full test suite to verify**

```bash
cd agent-service && python -m pytest tests/ -v
```

Expect: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/agent/
git commit -m "refactor: remove old flat files, finalize domain-layered structure"
```

---

## Task 11: Final verification — import sanity and end-to-end check

**Files:**
- None to change

- [ ] **Step 1: Check all Python files have clean imports**

```bash
cd agent-service && python -c "
from src.main import app
from src.agent.agent import create_pick_agent
from src.agent.stream.sse import _sse, stream_agent_response
from src.agent.memory.redis_history import generate_session_id, load_history, save_history
from src.agent.prompts import SYSTEM_PROMPT
from src.agent.middleware.logging import log_before_model, log_after_model
from src.agent.middleware.safety import content_safety_filter
from src.agent.services.milvus import get_milvus_client, build_filter_expr, search_shop_desc, merge_results
from src.agent.services.java_client import get_java_client
from src.agent.tools import search_shops, query_vouchers, place_order
print('All imports OK')
"
```

- [ ] **Step 2: Run full test suite**

```bash
cd agent-service && python -m pytest tests/ -v
```

- [ ] **Step 3: Verify git status is clean**

```bash
git status
```

- [ ] **Step 4: Final commit (if anything remaining)**

No files to commit if all steps done correctly.
```

---

## Summary

After this plan, the agent directory structure is:

```
src/agent/
  __init__.py
  agent.py              # thin factory, imports from all modules
  config.py             # unchanged
  prompts/
    __init__.py
    system_prompt.py
  middleware/
    __init__.py
    logging.py
    safety.py
  stream/
    __init__.py
    sse.py
    events.py
  memory/
    __init__.py
    redis_history.py
  tools/
    __init__.py         # re-exports all_tools for agent.py single import
    recommendation/
      __init__.py
      search_shops.py
    commerce/
      __init__.py
      query_vouchers.py
      place_order.py
    social/
      __init__.py       # placeholder (iteration 3)
    store/
      __init__.py       # placeholder (iteration 4)
  services/
    __init__.py
    milvus.py
    java_client.py
```
