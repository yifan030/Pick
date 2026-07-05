# Plan A: Storage Foundation & Data Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Set up all persistent storage (Neo4j, Milvus collections, Postgres checkpoint) and define the shared data models that Plans B and C depend on.

**Architecture:** This plan delivers the storage substrate. Neo4j stores Profile atoms and Entity relationships as a property graph. Three new Milvus collections (`user_event`, `user_session`, `agent_case`) store vector-searchable memories with dual dense+sparse indexes. Postgres replaces `InMemorySaver` for LangGraph checkpoints. A one-time entity sync seeds Neo4j from existing MySQL data (Shop, Category). `redis_history.py` is deleted — session persistence moves to the PostgresSaver.

**Tech Stack:** Neo4j 5.x (Docker), Milvus 2.6, PostgreSQL 16 (Docker), Python neo4j driver, pymilvus, langgraph-checkpoint-postgres

**Prerequisite for Plans B & C:** This plan MUST be started first. Plans B and C can begin in parallel once Task 5 (data models) and Task 8 (Neo4j client interface) are complete — they code against those interfaces.

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `agent-service/docker-compose.storage.yml` | Create | Neo4j + Postgres Docker services |
| `agent-service/src/storage/__init__.py` | Create | Public API exports |
| `agent-service/src/storage/models.py` | Create | Shared dataclasses: ProfileAtom, MemoryEvent, SessionSummary, AgentCase |
| `agent-service/src/storage/neo4j_client.py` | Create | Neo4j driver, CRUD for profiles/entities/refs |
| `agent-service/src/storage/milvus_store.py` | Create | MilvusMemoryStore: collection mgmt + insert/search/delete |
| `agent-service/src/storage/postgres_saver.py` | Create | PostgresSaver factory + table setup |
| `agent-service/src/storage/embedding.py` | Create | Shared embedding client (moved from ingestion/) |
| `agent-service/src/sync/__init__.py` | Create | Sync module exports |
| `agent-service/src/sync/entity_sync.py` | Create | MySQL → Neo4j entity graph seeder |
| `agent-service/scripts/init_neo4j.cypher` | Create | Neo4j constraints + indexes |
| `agent-service/src/agent/agent.py` | Modify | InMemorySaver → PostgresSaver |
| `agent-service/src/main.py` | Modify | Remove redis_history, add storage lifecycle |
| `agent-service/src/agent/memory/redis_history.py` | Delete | Replaced by PostgresSaver |
| `agent-service/pyproject.toml` | Modify | Add neo4j, langgraph-checkpoint-postgres deps |
| `agent-service/tests/storage/__init__.py` | Create | Test package |
| `agent-service/tests/storage/test_models.py` | Create | Model validation tests |
| `agent-service/tests/storage/test_neo4j_client.py` | Create | Neo4j CRUD tests (integration) |
| `agent-service/tests/storage/test_milvus_store.py` | Create | Milvus collection tests (integration) |
| `agent-service/tests/storage/test_postgres_saver.py` | Create | PostgresSaver tests |
| `agent-service/tests/sync/test_entity_sync.py` | Create | Entity sync tests |

---

## Prerequisites

Before starting, ensure:
- Docker Desktop is running
- Existing Milvus is available at `111.229.253.150:19530` (or `localhost:19530`)
- Python 3.11+ with current `agent-service` venv active

---

### Task A1: Add dependencies and Docker infrastructure

**Files:**
- Modify: `agent-service/pyproject.toml`
- Create: `agent-service/docker-compose.storage.yml`
- Create: `agent-service/scripts/init_neo4j.cypher`

- [ ] **Step 1: Add Python dependencies to pyproject.toml**

Read `agent-service/pyproject.toml` first. Add under `dependencies`:

```toml
"neo4j>=5.26.0",
"langgraph-checkpoint-postgres>=2.0.0",
"psycopg[binary]>=3.2.0",
```

- [ ] **Step 2: Install new dependencies**

```bash
cd agent-service && pip install -e ".[dev]"
```

Expected: packages install without errors.

- [ ] **Step 3: Create docker-compose.storage.yml**

```yaml
version: "3.8"
services:
  neo4j:
    image: neo4j:5.26
    container_name: pick-neo4j
    ports:
      - "7474:7474"   # HTTP
      - "7687:7687"   # Bolt
    environment:
      NEO4J_AUTH: neo4j/pick-neo4j-dev
      NEO4J_PLUGINS: '["apoc"]'
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs

  postgres:
    image: postgres:16-alpine
    container_name: pick-postgres
    ports:
      - "5433:5432"
    environment:
      POSTGRES_USER: pick
      POSTGRES_PASSWORD: pick-pg-dev
      POSTGRES_DB: pick_agent_checkpoint
    volumes:
      - pg_data:/var/lib/postgresql/data

volumes:
  neo4j_data:
  neo4j_logs:
  pg_data:
```

Note: Postgres uses port 5433 to avoid conflicts with any local PG on 5432.

- [ ] **Step 4: Create Neo4j init script**

```cypher
// init_neo4j.cypher — Run once after Neo4j first starts

// ── Constraints ────────────────────────────────────────────
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

CREATE CONSTRAINT shop_id_unique IF NOT EXISTS
FOR (s:Shop) REQUIRE s.shop_id IS UNIQUE;

CREATE CONSTRAINT area_name_unique IF NOT EXISTS
FOR (a:Area) REQUIRE a.name IS UNIQUE;

CREATE CONSTRAINT category_id_unique IF NOT EXISTS
FOR (c:Category) REQUIRE c.category_id IS UNIQUE;

CREATE CONSTRAINT voucher_id_unique IF NOT EXISTS
FOR (v:Voucher) REQUIRE v.voucher_id IS UNIQUE;

CREATE CONSTRAINT eventref_id_unique IF NOT EXISTS
FOR (e:EventRef) REQUIRE e.event_id IS UNIQUE;

CREATE CONSTRAINT sessionref_id_unique IF NOT EXISTS
FOR (s:SessionRef) REQUIRE s.session_id IS UNIQUE;

CREATE CONSTRAINT agentcaseref_id_unique IF NOT EXISTS
FOR (ac:AgentCaseRef) REQUIRE ac.case_id IS UNIQUE;

// Profile atom uniqueness (user_id + property combination)
CREATE CONSTRAINT taste_pref_unique IF NOT EXISTS
FOR (tp:TastePreference) REQUIRE (tp.user_id, tp.property) IS UNIQUE;

CREATE CONSTRAINT dietary_pref_unique IF NOT EXISTS
FOR (dp:DietaryPreference) REQUIRE (dp.user_id, dp.constraint) IS UNIQUE;

CREATE CONSTRAINT cuisine_pref_unique IF NOT EXISTS
FOR (cp:CuisinePreference) REQUIRE (cp.user_id, cp.cuisine) IS UNIQUE;

CREATE CONSTRAINT area_pref_unique IF NOT EXISTS
FOR (ap:AreaPreference) REQUIRE (ap.user_id, ap.area) IS UNIQUE;

CREATE CONSTRAINT scene_pref_unique IF NOT EXISTS
FOR (sp:ScenePreference) REQUIRE (sp.user_id, sp.scene) IS UNIQUE;

CREATE CONSTRAINT budget_pref_unique IF NOT EXISTS
FOR (bp:BudgetPreference) REQUIRE (bp.user_id, bp.type) IS UNIQUE;

CREATE CONSTRAINT constraint_pref_unique IF NOT EXISTS
FOR (cp2:ConstraintPreference) REQUIRE (cp2.user_id, cp2.constraint) IS UNIQUE;

// ── Indexes ────────────────────────────────────────────────
CREATE INDEX shop_area_idx IF NOT EXISTS FOR (s:Shop) ON (s.area);
CREATE INDEX shop_type_idx IF NOT EXISTS FOR (s:Shop) ON (s.type);
CREATE INDEX taste_confidence_idx IF NOT EXISTS FOR (tp:TastePreference) ON (tp.confidence);
CREATE INDEX cuisine_confidence_idx IF NOT EXISTS FOR (cp:CuisinePreference) ON (cp.confidence);
CREATE INDEX area_pref_confidence_idx IF NOT EXISTS FOR (ap:AreaPreference) ON (ap.confidence);
CREATE INDEX eventref_user_idx IF NOT EXISTS FOR (e:EventRef) ON (e.user_id);
CREATE INDEX sessionref_user_idx IF NOT EXISTS FOR (s:SessionRef) ON (s.user_id);
```

- [ ] **Step 5: Start storage services**

```bash
cd agent-service && docker compose -f docker-compose.storage.yml up -d
```

Expected: `docker ps` shows `pick-neo4j` and `pick-postgres` running.

- [ ] **Step 6: Run Neo4j init script**

```bash
docker exec -i pick-neo4j cypher-shell -u neo4j -p pick-neo4j-dev < agent-service/scripts/init_neo4j.cypher
```

Expected: No errors, constraints created.

- [ ] **Step 7: Commit**

```bash
git add agent-service/pyproject.toml agent-service/docker-compose.storage.yml agent-service/scripts/init_neo4j.cypher
git commit -m "feat: add Neo4j + Postgres Docker infra and Python dependencies"
```

---

### Task A2: Define shared data models

**Files:**
- Create: `agent-service/src/storage/__init__.py`
- Create: `agent-service/src/storage/models.py`
- Create: `agent-service/tests/storage/__init__.py`
- Create: `agent-service/tests/storage/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/storage/test_models.py
"""Tests for shared memory data models."""
import json
import time
from dataclasses import asdict
from src.storage.models import (
    ProfileAtom,
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    MemoryEvent,
    SessionSummary,
    AgentCase,
    DeltaOperation,
    ProfileDelta,
    DELTA_ADD,
    DELTA_REINFORCE,
    DELTA_REVISE,
    DELTA_DELETE,
    DELTA_MERGE,
    DELTA_NOCHANGE,
    DELTA_EXPIRE,
)


def test_taste_preference_defaults():
    """TastePreference should have correct defaults."""
    p = TastePreference(
        user_id="u1",
        property="spicy",
        value="like",
    )
    assert p.confidence == 0.6
    assert p.reinforce_count == 0
    assert p.source == "agent"
    assert p.is_hard is False
    assert p.ttl_seconds is None
    assert p.expires_at is None


def test_dietary_preference_is_hard():
    """DietaryPreference is always hard by default."""
    p = DietaryPreference(
        user_id="u1",
        constraint="清真",
        type="religious",
    )
    assert p.is_hard is True
    assert p.confidence == 1.0


def test_memory_event_serialization():
    """MemoryEvent should serialize to dict for Milvus insert."""
    e = MemoryEvent(
        user_id="u1",
        event_type="search",
        description="用户在春熙路搜索火锅",
        payload={"query": "火锅", "area": "春熙路"},
        session_id="sess_abc",
    )
    d = asdict(e)
    assert d["user_id"] == "u1"
    assert d["event_type"] == "search"
    assert d["payload"] == '{"query": "火锅", "area": "春熙路"}'  # JSON string
    assert d["compressed"] is False


def test_session_summary_incremental():
    """SessionSummary defaults to incomplete (ongoing)."""
    s = SessionSummary(
        user_id="u1",
        summary="用户在春熙路搜索火锅",
        key_shops=["shop_1"],
        key_areas=["春熙路"],
        intent="recommend_shop",
    )
    assert s.is_complete is False


def test_agent_case_optional_user():
    """AgentCase user_id can be None for generic patterns."""
    ac = AgentCase(
        user_id=None,
        case_type="recommendation",
        description="用户不吃辣推荐粤菜成功",
        context={},
        action="推荐粤菜馆",
        outcome="success",
        lesson="不吃辣时优先推荐粤菜",
    )
    assert ac.user_id is None


def test_delta_operation_types():
    """Verify all delta operation constants are distinct."""
    ops = {DELTA_ADD, DELTA_REINFORCE, DELTA_REVISE, DELTA_DELETE, DELTA_MERGE, DELTA_NOCHANGE, DELTA_EXPIRE}
    assert len(ops) == 7


def test_profile_delta_structure():
    """ProfileDelta should carry operation + target info."""
    delta = ProfileDelta(
        op=DELTA_ADD,
        target_type="CuisinePreference",
        new_value=CuisinePreference(
            user_id="u1",
            cuisine="川渝火锅",
            confidence=0.6,
            weight=0.9,
        ),
        reason="用户最近频繁搜索火锅",
    )
    assert delta.op == DELTA_ADD
    assert delta.target_type == "CuisinePreference"
    assert delta.old_value is None
    assert delta.new_value.cuisine == "川渝火锅"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd agent-service && python -m pytest tests/storage/test_models.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.storage.models'`

- [ ] **Step 3: Write models.py**

```python
# src/storage/models.py
"""Shared data models for the agent memory system.

These dataclasses are the canonical in-memory representation of all memory
types. They are used by Plans A, B, and C. Storage backends (Neo4j, Milvus)
convert to/from these types.

Profile atoms live in Neo4j as labeled nodes.
Events, Sessions, and AgentCases live in Milvus as vector-searchable documents.
"""

from dataclasses import dataclass, field, asdict
import json
import time
from typing import Any


# ── Delta Operation Constants ─────────────────────────────────────────

DELTA_ADD = "ADD"
DELTA_REINFORCE = "REINFORCE"
DELTA_REVISE = "REVISE"
DELTA_DELETE = "DELETE"
DELTA_MERGE = "MERGE"
DELTA_NOCHANGE = "NOCHANGE"
DELTA_EXPIRE = "EXPIRE"


# ── Timestamp helper ──────────────────────────────────────────────────

def _now() -> int:
    return int(time.time())


# ── Profile Atoms (Neo4j nodes) ──────────────────────────────────────


@dataclass
class ProfileAtom:
    """Base class for all profile preference atoms.

    These are stored as labeled nodes in Neo4j, attached to (:User) nodes
    via typed relationships (PREFERS_TASTE, PREFERS_CUISINE, etc.).
    """
    user_id: str
    confidence: float = 0.6
    source: str = "agent"
    reinforce_count: int = 0
    last_reinforced_at: int = 0
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)
    ttl_seconds: int | None = None
    expires_at: int | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return _now() >= self.expires_at

    def node_type(self) -> str:
        raise NotImplementedError


@dataclass
class TastePreference(ProfileAtom):
    """Taste preference: e.g. spicy→like, sweet→avoid."""
    property: str = ""
    value: str = "like"
    is_hard: bool = False

    def node_type(self) -> str:
        return "TastePreference"


@dataclass
class DietaryPreference(ProfileAtom):
    """Dietary constraint (hard): halal, vegetarian, allergen, etc.

    Hard constraints: never decay, never auto-REVISE, always injected.
    """
    constraint: str = ""
    type: str = ""  # "religious" | "health" | "allergy" | "ethical"
    is_hard: bool = True
    confidence: float = 1.0   # Hard constraints start at 1.0

    def node_type(self) -> str:
        return "DietaryPreference"


@dataclass
class BudgetPreference(ProfileAtom):
    """Budget range preference. Only one per user (latest wins)."""
    range_min: int = 0
    range_max: int = 0
    type: str = "per_person"  # "per_person" | "total"

    def node_type(self) -> str:
        return "BudgetPreference"


@dataclass
class CuisinePreference(ProfileAtom):
    """Cuisine type preference with weight."""
    cuisine: str = ""
    weight: float = 0.5

    def node_type(self) -> str:
        return "CuisinePreference"


@dataclass
class AreaPreference(ProfileAtom):
    """Area/business district preference."""
    area: str = ""
    weight: float = 0.5

    def node_type(self) -> str:
        return "AreaPreference"


@dataclass
class ScenePreference(ProfileAtom):
    """Dining scene preference: 约会, 家庭聚餐, 朋友聚餐, etc."""
    scene: str = ""
    weight: float = 0.5

    def node_type(self) -> str:
        return "ScenePreference"


@dataclass
class ConstraintPreference(ProfileAtom):
    """Soft constraint: "不要辣", "要包间", etc.

    Unlike DietaryPreference, these participate in decay and can be auto-REVISEd.
    """
    constraint: str = ""
    type: str = "taste"
    is_hard: bool = False

    def node_type(self) -> str:
        return "ConstraintPreference"


# Union type for any profile atom
AnyProfile = (
    TastePreference | DietaryPreference | BudgetPreference
    | CuisinePreference | AreaPreference | ScenePreference
    | ConstraintPreference
)


# ── Memory Events (Milvus collection: user_event) ─────────────────────


@dataclass
class MemoryEvent:
    """A single behavioral event extracted from a conversation turn.

    Stored in Milvus collection `user_event` with dense + sparse embeddings.
    """
    user_id: str
    event_type: str           # "search" | "purchase" | "reservation" | "view" | "feedback" | "constraint" | "dietary"
    description: str           # Natural language description (embedding source)
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    embedding: list[float] | None = None      # Filled by embedder before insert
    sparse_embedding: dict[int, float] | None = None  # BM25 sparse vector
    compressed: bool = False
    compressed_from: list[str] = field(default_factory=list)
    ttl_seconds: int | None = None
    expires_at: int | None = None
    created_at: int = field(default_factory=_now)

    @property
    def id(self) -> str:
        """Derive ID from content hash for idempotency."""
        import hashlib
        key = f"{self.user_id}:{self.event_type}:{self.created_at}:{self.description[:80]}"
        return f"evt_{hashlib.md5(key.encode()).hexdigest()[:16]}"

    def to_milvus_dict(self) -> dict:
        """Convert to dict for Milvus insert, JSON-serializing payload."""
        d = asdict(self)
        d["payload"] = json.dumps(self.payload, ensure_ascii=False)
        d["compressed_from"] = json.dumps(self.compressed_from, ensure_ascii=False)
        # Remove Python-only fields
        d.pop("embedding", None)
        d.pop("sparse_embedding", None)
        return d


# ── Session Summaries (Milvus collection: user_session) ───────────────


@dataclass
class SessionSummary:
    """A conversation session summary stored in Milvus.

    Incrementally updated every 3 turns. Marked complete when session ends.
    """
    user_id: str
    summary: str              # Natural language summary (embedding source)
    key_shops: list[str] = field(default_factory=list)
    key_areas: list[str] = field(default_factory=list)
    intent: str = ""
    is_complete: bool = False
    embedding: list[float] | None = None
    sparse_embedding: dict[int, float] | None = None
    created_at: int = field(default_factory=_now)
    updated_at: int = field(default_factory=_now)

    @property
    def id(self) -> str:
        import hashlib
        key = f"{self.user_id}:{self.created_at}"
        return f"sess_{hashlib.md5(key.encode()).hexdigest()[:16]}"

    def to_milvus_dict(self) -> dict:
        d = asdict(self)
        d["key_shops"] = json.dumps(self.key_shops, ensure_ascii=False)
        d["key_areas"] = json.dumps(self.key_areas, ensure_ascii=False)
        d.pop("embedding", None)
        d.pop("sparse_embedding", None)
        return d


# ── Agent Cases (Milvus collection: agent_case) ───────────────────────


@dataclass
class AgentCase:
    """Agent experience memory — records of past recommendation outcomes."""
    user_id: str | None       # None = generic pattern
    case_type: str            # "recommendation" | "purchase_flow" | "error_recovery" | "user_handling"
    description: str
    context: dict[str, Any] = field(default_factory dict)
    action: str = ""
    outcome: str = ""         # "success" | "partial" | "failure"
    outcome_reason: str = ""
    lesson: str = ""
    embedding: list[float] | None = None
    sparse_embedding: dict[int, float] | None = None
    created_at: int = field(default_factory=_now)
    ttl_seconds: int | None = 15552000  # 180 days default

    @property
    def id(self) -> str:
        import hashlib
        key = f"{self.user_id or 'global'}:{self.case_type}:{self.created_at}:{self.description[:80]}"
        return f"case_{hashlib.md5(key.encode()).hexdigest()[:16]}"

    def to_milvus_dict(self) -> dict:
        d = asdict(self)
        d["context"] = json.dumps(self.context, ensure_ascii=False)
        d.pop("embedding", None)
        d.pop("sparse_embedding", None)
        return d


# ── Delta Operations (for Profile Updater output) ─────────────────────


@dataclass
class DeltaOperation:
    """A single memory delta produced by the Profile Updater."""
    op: str                   # ADD | REINFORCE | REVISE | DELETE | MERGE | NOCHANGE | EXPIRE
    target_type: str
    target_id: str | None = None
    old_value: AnyProfile | None = None
    new_value: AnyProfile | None = None
    reason: str = ""

    def to_audit_dict(self) -> dict:
        return {
            "op": self.op,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "old_value": _profile_to_dict(self.old_value),
            "new_value": _profile_to_dict(self.new_value),
            "reason": self.reason,
        }


def _profile_to_dict(p: AnyProfile | None) -> dict | None:
    if p is None:
        return None
    d = asdict(p)
    # Remove large/unnecessary fields for audit
    d.pop("created_at", None)
    d.pop("updated_at", None)
    return d


# Alias for backward compat
ProfileDelta = DeltaOperation
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd agent-service && python -m pytest tests/storage/test_models.py -v
```

Expected: All 7 tests PASS.

- [ ] **Step 5: Write storage __init__.py**

```python
# src/storage/__init__.py
"""Storage layer for agent memory system.

Public API:
- models:     Shared data models (ProfileAtom, MemoryEvent, SessionSummary, AgentCase)
- Neo4jClient: Profile + Entity graph CRUD
- MilvusMemoryStore: Event/Session/AgentCase insert + search
- PostgresSaverManager: LangGraph checkpoint persistence
"""

from src.storage.models import (
    # Profile atoms
    ProfileAtom,
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    AnyProfile,
    # Memory types
    MemoryEvent,
    SessionSummary,
    AgentCase,
    # Delta operations
    DeltaOperation,
    DELTA_ADD,
    DELTA_REINFORCE,
    DELTA_REVISE,
    DELTA_DELETE,
    DELTA_MERGE,
    DELTA_NOCHANGE,
    DELTA_EXPIRE,
)

__all__ = [
    "ProfileAtom",
    "TastePreference",
    "DietaryPreference",
    "BudgetPreference",
    "CuisinePreference",
    "AreaPreference",
    "ScenePreference",
    "ConstraintPreference",
    "AnyProfile",
    "MemoryEvent",
    "SessionSummary",
    "AgentCase",
    "DeltaOperation",
    "DELTA_ADD",
    "DELTA_REINFORCE",
    "DELTA_REVISE",
    "DELTA_DELETE",
    "DELTA_MERGE",
    "DELTA_NOCHANGE",
    "DELTA_EXPIRE",
]
```

- [ ] **Step 6: Commit**

```bash
git add agent-service/src/storage/__init__.py agent-service/src/storage/models.py agent-service/tests/storage/
git commit -m "feat: define shared memory data models (ProfileAtom, MemoryEvent, SessionSummary, AgentCase)"
```

---

### Task A3: Create shared embedding client

**Files:**
- Create: `agent-service/src/storage/embedding.py`

- [ ] **Step 1: Write embedding.py**

The embedding module already exists at `src/ingestion/embedding.py`. We move it to `storage/` for shared use and add a sparse embedding function placeholder.

```python
# src/storage/embedding.py
"""Shared embedding client for dense + sparse (BM25) vector generation.

Consolidated from src/ingestion/embedding.py. All plans use this single client.
"""

import os
import logging
from openai import OpenAI

logger = logging.getLogger("pick.storage.embedding")

# ── Config ────────────────────────────────────────────────────────────

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", LLM_BASE_URL)
LLM_API_KEY = os.environ.get("LLM_API_KEY", "sk-placeholder")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", LLM_API_KEY)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=EMBEDDING_BASE_URL or None,
            api_key=EMBEDDING_API_KEY,
        )
    return _client


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Generate dense embeddings for a list of texts.

    Returns a list of float vectors, one per input text.
    """
    if not texts:
        return []
    client = _get_client()
    try:
        resp = client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=texts,
        )
        return [d.embedding for d in resp.data]
    except Exception:
        logger.exception("Embedding failed for %d texts", len(texts))
        raise


def embed_single(text: str) -> list[float]:
    """Generate a single dense embedding."""
    return embed_texts([text])[0]


# ── Sparse (BM25) Embedding ──────────────────────────────────────────
# Milvus 2.4+ supports SPARSE_FLOAT_VECTOR via built-in BM25 analyzer.
# The actual sparse embedding is generated server-side by Milvus when
# the collection schema includes a SPARSE_FLOAT_VECTOR field with BM25
# function. This function returns None as a sentinel — Milvus handles it.
# For client-side BM25, use the milvus_model library (future).


def embed_sparse(texts: list[str]) -> list[dict[int, float]]:
    """Generate BM25 sparse embeddings.

    NOTE: Milvus 2.4+ can auto-generate BM25 sparse vectors server-side
    via Function-based SPARSE_FLOAT_VECTOR fields. This client-side
    function is a placeholder. Real BM25 embedding requires:
      pip install milvus-model
      from milvus_model.sparse import BM25EmbeddingFunction
    """
    # Placeholder: return empty sparse vectors
    # The actual BM25 embedding will be generated by Milvus server-side
    # when we define the collection with a BM25 function.
    return [{} for _ in texts]
```

- [ ] **Step 2: Update ingestion/embedding.py to re-export from storage**

Read `agent-service/src/ingestion/embedding.py`. Replace its contents with a re-export:

```python
# src/ingestion/embedding.py
"""Re-export from src.storage.embedding for backward compatibility."""
from src.storage.embedding import embed_texts, embed_single

__all__ = ["embed_texts", "embed_single"]
```

- [ ] **Step 3: Run existing embedding tests to verify no breakage**

```bash
cd agent-service && python -m pytest tests/test_embedding.py -v
```

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add agent-service/src/storage/embedding.py agent-service/src/ingestion/embedding.py
git commit -m "feat: consolidate embedding client to storage/embedding.py"
```

---

### Task A4: Neo4j client — connection and profile CRUD

**Files:**
- Create: `agent-service/src/storage/neo4j_client.py`
- Create: `agent-service/tests/storage/test_neo4j_client.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/storage/test_neo4j_client.py
"""Integration tests for Neo4jClient. Requires Neo4j running via Docker."""
import pytest
import asyncio
from src.storage.neo4j_client import Neo4jClient
from src.storage.models import (
    TastePreference, CuisinePreference, DietaryPreference,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def neo4j():
    """Create a Neo4jClient connected to the test instance."""
    client = Neo4jClient(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="pick-neo4j-dev",
    )
    await client.connect()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_write_and_read_taste_preference(neo4j):
    """Write a TastePreference then read it back."""
    user_id = "test_user_1"
    tp = TastePreference(
        user_id=user_id,
        property="spicy",
        value="avoid",
        confidence=0.9,
        reinforce_count=3,
    )

    # Write
    profile_id = await neo4j.write_profile(user_id, tp)
    assert profile_id is not None

    # Read back
    profiles = await neo4j.read_profiles(user_id, types=["TastePreference"])
    assert len(profiles) >= 1
    found = [p for p in profiles if p.property == "spicy"]
    assert len(found) == 1
    assert found[0].value == "avoid"
    assert found[0].confidence == 0.9
    assert found[0].reinforce_count == 3

    # Cleanup
    await neo4j.delete_profile(profile_id)


@pytest.mark.asyncio
async def test_update_profile_confidence(neo4j):
    """Update a profile's confidence after REINFORCE."""
    user_id = "test_user_2"
    tp = TastePreference(user_id=user_id, property="sweet", value="like", confidence=0.6)

    profile_id = await neo4j.write_profile(user_id, tp)

    # Update
    await neo4j.update_profile(profile_id, {"confidence": 0.7, "reinforce_count": 1})

    profiles = await neo4j.read_profiles(user_id, types=["TastePreference"])
    found = [p for p in profiles if p.property == "sweet"]
    assert found[0].confidence == 0.7
    assert found[0].reinforce_count == 1

    await neo4j.delete_profile(profile_id)


@pytest.mark.asyncio
async def test_hard_constraints_always_returned(neo4j):
    """get_hard_constraints should return DietaryPreferences."""
    user_id = "test_user_3"
    dp = DietaryPreference(user_id=user_id, constraint="清真", type="religious")

    pid = await neo4j.write_profile(user_id, dp)
    hard = await neo4j.get_hard_constraints(user_id)
    assert len(hard) >= 1
    assert any(p.constraint == "清真" for p in hard)

    await neo4j.delete_profile(pid)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd agent-service && python -m pytest tests/storage/test_neo4j_client.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'src.storage.neo4j_client'`

- [ ] **Step 3: Write neo4j_client.py**

```python
# src/storage/neo4j_client.py
"""Neo4j client for profile atoms and entity graph operations.

Handles:
- Profile CRUD (write, read, update, delete)
- Entity graph (User, Shop, Area, Category nodes + relationships)
- Reference nodes (EventRef, SessionRef, AgentCaseRef)
- Subgraph traversal for entity boost (used by Plan C)
- Hard constraint retrieval (used by Plan C)
"""

import logging
from typing import Any
from neo4j import AsyncGraphDatabase, AsyncDriver

from src.storage.models import (
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    AnyProfile,
)

logger = logging.getLogger("pick.storage.neo4j")

# ── Node type → Python class mapping ─────────────────────────────────

NODE_TYPE_MAP = {
    "TastePreference": TastePreference,
    "DietaryPreference": DietaryPreference,
    "BudgetPreference": BudgetPreference,
    "CuisinePreference": CuisinePreference,
    "AreaPreference": AreaPreference,
    "ScenePreference": ScenePreference,
    "ConstraintPreference": ConstraintPreference,
}

RELATIONSHIP_MAP = {
    "TastePreference": "PREFERS_TASTE",
    "DietaryPreference": "PREFERS_DIETARY",
    "BudgetPreference": "HAS_BUDGET",
    "CuisinePreference": "PREFERS_CUISINE",
    "AreaPreference": "PREFERS_AREA",
    "ScenePreference": "PREFERS_SCENE",
    "ConstraintPreference": "HAS_CONSTRAINT",
}


class Neo4jClient:
    """Async Neo4j client for agent memory graph operations."""

    def __init__(self, uri: str, user: str, password: str):
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: AsyncDriver | None = None

    async def connect(self):
        """Initialize the driver and verify connectivity."""
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        await self._driver.verify_connectivity()
        logger.info("Neo4j connected: %s", self._uri)

    async def close(self):
        if self._driver:
            await self._driver.close()

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4jClient not connected. Call connect() first.")
        return self._driver

    # ── Profile CRUD ──────────────────────────────────────────────

    async def write_profile(self, user_id: str, profile: AnyProfile) -> str:
        """Create or merge a User node + Profile atom node + relationship.

        Returns the profile node's elementId.
        """
        node_type = profile.node_type()
        rel_type = RELATIONSHIP_MAP[node_type]

        # Convert dataclass to dict, excluding None values and Python internals
        props = _profile_to_neo4j_props(profile)
        props["user_id"] = user_id

        query = f"""
        MERGE (u:User {{user_id: $user_id}})
        CREATE (p:{node_type} $props)
        CREATE (u)-[:{rel_type}]->(p)
        RETURN elementId(p) AS profile_id
        """
        async with self.driver.session() as session:
            result = await session.run(query, user_id=user_id, props=props)
            record = await result.single()
            return record["profile_id"] if record else ""

    async def read_profiles(
        self, user_id: str, types: list[str] | None = None
    ) -> list[AnyProfile]:
        """Read all active profiles for a user, optionally filtered by type.

        Excludes expired profiles and those with confidence < 0.3.
        """
        if types is None:
            types = list(NODE_TYPE_MAP.keys())

        results = []
        for nt in types:
            rel_type = RELATIONSHIP_MAP.get(nt)
            if rel_type is None:
                continue
            query = f"""
            MATCH (u:User {{user_id: $user_id}})-[:{rel_type}]->(p:{nt})
            WHERE p.confidence >= 0.3
              AND (p.expires_at IS NULL OR p.expires_at > timestamp() / 1000)
            RETURN p
            """
            async with self.driver.session() as session:
                cursor = await session.run(query, user_id=user_id)
                async for record in cursor:
                    node = record["p"]
                    profile = _neo4j_node_to_profile(nt, dict(node))
                    if profile:
                        results.append(profile)
        return results

    async def update_profile(self, profile_id: str, updates: dict) -> None:
        """Update properties on an existing profile node by elementId."""
        set_clauses = ", ".join(f"p.{k} = ${k}" for k in updates)
        query = f"""
        MATCH (p) WHERE elementId(p) = $profile_id
        SET {set_clauses}, p.updated_at = timestamp() / 1000
        """
        async with self.driver.session() as session:
            await session.run(query, profile_id=profile_id, **updates)

    async def delete_profile(self, profile_id: str) -> None:
        """Delete a profile node and its relationships by elementId."""
        query = """
        MATCH (p) WHERE elementId(p) = $profile_id
        DETACH DELETE p
        """
        async with self.driver.session() as session:
            await session.run(query, profile_id=profile_id)

    async def get_hard_constraints(self, user_id: str) -> list[AnyProfile]:
        """Get all hard constraints (is_hard=true) for a user.

        These are always injected into the system prompt, never decayed.
        Includes DietaryPreference (always hard) and any other is_hard atoms.
        """
        results = []
        # DietaryPreference are always hard
        query = """
        MATCH (u:User {user_id: $user_id})-[:PREFERS_DIETARY]->(dp:DietaryPreference)
        WHERE dp.confidence >= 0.3
        RETURN dp
        """
        async with self.driver.session() as session:
            cursor = await session.run(query, user_id=user_id)
            async for record in cursor:
                profile = _neo4j_node_to_profile("DietaryPreference", dict(record["dp"]))
                if profile:
                    results.append(profile)

        # Any other profile with is_hard=true
        for nt in ["TastePreference", "ConstraintPreference"]:
            rel = RELATIONSHIP_MAP[nt]
            query = f"""
            MATCH (u:User {{user_id: $user_id}})-[:{rel}]->(p:{nt})
            WHERE p.is_hard = true AND p.confidence >= 0.3
            RETURN p
            """
            async with self.driver.session() as session:
                cursor = await session.run(query, user_id=user_id)
                async for record in cursor:
                    profile = _neo4j_node_to_profile(nt, dict(record["p"]))
                    if profile:
                        results.append(profile)

        return results

    # ── Entity Graph / Subgraph Traversal ──────────────────────────

    async def subgraph_search(
        self,
        user_id: str,
        entities: dict,
        limit: int = 20,
    ) -> list[dict]:
        """Traverse the entity graph for entity-boosted retrieval.

        ``entities`` is a dict with optional keys:
          areas: list[str], cuisines: list[str], shop_ids: list[str]

        Returns list of {memory_id, boost_score, memory_type} dicts.
        Used by Plan C's EntityBoost module.
        """
        areas = entities.get("areas", [])
        cuisines = entities.get("cuisines", [])
        shop_ids = entities.get("shop_ids", [])

        # Build dynamic WHERE clauses
        where_clauses = []
        params: dict[str, Any] = {"user_id": user_id, "limit": limit}

        if areas:
            where_clauses.append("ap.area IN $areas")
            params["areas"] = areas
        if cuisines:
            where_clauses.append("cp.cuisine IN $cuisines")
            params["cuisines"] = cuisines

        where_str = " OR ".join(where_clauses) if where_clauses else "TRUE"

        query = f"""
        MATCH (u:User {{user_id: $user_id}})
        OPTIONAL MATCH (u)-[:PREFERS_AREA]->(ap:AreaPreference)
          WHERE ap.confidence >= 0.3
        OPTIONAL MATCH (u)-[:PREFERS_CUISINE]->(cp:CuisinePreference)
          WHERE cp.confidence >= 0.3
        OPTIONAL MATCH (u)-[:PREFERS_DIETARY]->(dp:DietaryPreference)
          WHERE dp.confidence >= 0.3
        OPTIONAL MATCH (u)-[:PERFORMED]->(er:EventRef)
        OPTIONAL MATCH (er)-[:TARGETED]->(target)
        WHERE {where_str}
        RETURN
          ap.area AS matched_area,
          cp.cuisine AS matched_cuisine,
          dp.constraint AS matched_dietary,
          er.event_id AS event_id,
          coalesce(ap.confidence, 0) * coalesce(ap.weight, 0.5) AS area_boost,
          coalesce(cp.confidence, 0) * coalesce(cp.weight, 0.5) AS cuisine_boost,
          coalesce(dp.confidence, 0) AS dietary_boost
        LIMIT $limit
        """
        results = []
        async with self.driver.session() as session:
            cursor = await session.run(query, **params)
            async for record in cursor:
                data = dict(record)
                boost = max(
                    data.get("area_boost") or 0,
                    data.get("cuisine_boost") or 0,
                    data.get("dietary_boost") or 0,
                )
                results.append({
                    "event_id": data.get("event_id"),
                    "matched_area": data.get("matched_area"),
                    "matched_cuisine": data.get("matched_cuisine"),
                    "matched_dietary": data.get("matched_dietary"),
                    "boost_score": round(boost, 4),
                })
        return results

    # ── Reference Node Management ──────────────────────────────────

    async def write_event_ref(
        self, user_id: str, event_id: str, targets: list[dict]
    ) -> None:
        """Create an EventRef node and link it to User + target entities.

        targets: list of {type: "Shop"|"Area"|"Category", id: str}
        """
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (u:User {user_id: $user_id})
                MERGE (er:EventRef {event_id: $event_id})
                SET er.user_id = $user_id
                MERGE (u)-[:PERFORMED]->(er)
                """,
                user_id=user_id,
                event_id=event_id,
            )
            for target in targets:
                target_type = target["type"]
                target_id = target["id"]
                await session.run(
                    f"""
                    MATCH (er:EventRef {{event_id: $event_id}})
                    MATCH (t:{target_type} {{{target_type.lower()}_id: $target_id}})
                    MERGE (er)-[:TARGETED]->(t)
                    """,
                    event_id=event_id,
                    target_id=target_id,
                )

    async def write_session_ref(
        self, user_id: str, session_id: str, shop_ids: list[str]
    ) -> None:
        """Create a SessionRef node and link to mentioned shops."""
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (u:User {user_id: $user_id})
                MERGE (sr:SessionRef {session_id: $session_id})
                SET sr.user_id = $user_id
                MERGE (u)-[:HAS_SESSION]->(sr)
                """,
                user_id=user_id,
                session_id=session_id,
            )
            for shop_id in shop_ids:
                await session.run(
                    """
                    MATCH (sr:SessionRef {session_id: $session_id})
                    MERGE (s:Shop {shop_id: $shop_id})
                    MERGE (sr)-[:MENTIONED]->(s)
                    """,
                    session_id=session_id,
                    shop_id=shop_id,
                )

    async def write_agent_case_ref(
        self, user_id: str, case_id: str, involved: list[dict]
    ) -> None:
        """Create an AgentCaseRef node."""
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (u:User {user_id: $user_id})
                MERGE (ac:AgentCaseRef {case_id: $case_id})
                MERGE (u)-[:HAS_EXPERIENCE]->(ac)
                """,
                user_id=user_id,
                case_id=case_id,
            )

    # ── Entity Sync Helpers ────────────────────────────────────────

    async def upsert_shop(self, shop: dict) -> None:
        """Upsert a Shop node from sync data."""
        query = """
        MERGE (s:Shop {shop_id: $shop_id})
        SET s.name = $name, s.type = $type, s.sub_type = $sub_type,
            s.area = $area, s.address = $address,
            s.longitude = $longitude, s.latitude = $latitude,
            s.avg_price = $avg_price, s.score = $score
        """
        async with self.driver.session() as session:
            await session.run(query, **shop)

    async def upsert_area(self, name: str) -> None:
        """Upsert an Area node."""
        async with self.driver.session() as session:
            await session.run(
                "MERGE (a:Area {name: $name})", name=name
            )

    async def upsert_category(self, cat: dict) -> None:
        """Upsert a Category node with parent relationship."""
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (c:Category {category_id: $category_id})
                SET c.name = $name
                """,
                category_id=cat["category_id"],
                name=cat["name"],
            )
            if cat.get("parent_id"):
                await session.run(
                    """
                    MATCH (c:Category {category_id: $category_id})
                    MATCH (p:Category {category_id: $parent_id})
                    MERGE (c)-[:CHILD_OF]->(p)
                    """,
                    category_id=cat["category_id"],
                    parent_id=cat["parent_id"],
                )

    async def link_shop_area(self, shop_id: str, area_name: str) -> None:
        """Link a Shop to its Area."""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (s:Shop {shop_id: $shop_id})
                MERGE (a:Area {name: $area_name})
                MERGE (s)-[:LOCATED_IN]->(a)
                """,
                shop_id=shop_id,
                area_name=area_name,
            )

    async def link_shop_category(self, shop_id: str, category_id: str) -> None:
        """Link a Shop to its primary Category."""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (s:Shop {shop_id: $shop_id})
                MATCH (c:Category {category_id: $category_id})
                MERGE (s)-[:HAS_CATEGORY]->(c)
                """,
                shop_id=shop_id,
                category_id=category_id,
            )


# ── Internal Helpers ──────────────────────────────────────────────────


def _profile_to_neo4j_props(profile: AnyProfile) -> dict:
    """Convert a ProfileAtom dataclass to a Neo4j-safe properties dict.

    Skips None values and Python-internal fields.
    """
    from dataclasses import fields

    skip = {"user_id"}  # user_id is passed separately
    props = {}
    for f in fields(profile):
        if f.name in skip:
            continue
        value = getattr(profile, f.name)
        if value is not None:
            # Convert bool to Neo4j boolean
            if isinstance(value, bool):
                props[f.name] = value
            elif isinstance(value, (int, float, str)):
                props[f.name] = value
            elif isinstance(value, list):
                # Lists aren't used in Profile atoms currently
                pass
    return props


def _neo4j_node_to_profile(node_type: str, props: dict) -> AnyProfile | None:
    """Convert a Neo4j node properties dict to a ProfileAtom instance."""
    cls = NODE_TYPE_MAP.get(node_type)
    if cls is None:
        return None

    # Filter to only fields that exist on the dataclass
    from dataclasses import fields as dc_fields
    valid_keys = {f.name for f in dc_fields(cls)}
    filtered = {k: v for k, v in props.items() if k in valid_keys}
    return cls(**filtered)
```

- [ ] **Step 4: Run integration tests**

```bash
cd agent-service && python -m pytest tests/storage/test_neo4j_client.py -v
```

Expected: 3 tests PASS (requires Neo4j running from Task A1 Step 5).

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/storage/neo4j_client.py agent-service/tests/storage/test_neo4j_client.py
git commit -m "feat: Neo4j client with profile CRUD, hard constraint retrieval, subgraph search"
```

---

### Task A5: Milvus memory store — collection management

**Files:**
- Create: `agent-service/src/storage/milvus_store.py`
- Create: `agent-service/tests/storage/test_milvus_store.py`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/storage/test_milvus_store.py
"""Integration tests for MilvusMemoryStore. Requires Milvus running."""
import pytest
from src.storage.milvus_store import (
    MilvusMemoryStore,
    COLLECTION_USER_EVENT,
    COLLECTION_USER_SESSION,
    COLLECTION_AGENT_CASE,
)
from src.storage.models import MemoryEvent, SessionSummary, AgentCase

pytestmark = pytest.mark.integration


@pytest.fixture
def store():
    """Create MilvusMemoryStore connected to the test Milvus instance."""
    ms = MilvusMemoryStore(
        host="111.229.253.150",
        port=19530,
        embedding_dim=1024,
    )
    ms.connect()
    return ms


def test_create_collections(store):
    """All three collections should be creatable (idempotent)."""
    names = store.create_all_collections()
    assert COLLECTION_USER_EVENT in names
    assert COLLECTION_USER_SESSION in names
    assert COLLECTION_AGENT_CASE in names


def test_collections_have_dense_and_sparse_indexes(store):
    """Each collection should have HNSW (dense) + SPARSE_INVERTED_INDEX."""
    for coll in [COLLECTION_USER_EVENT, COLLECTION_USER_SESSION, COLLECTION_AGENT_CASE]:
        desc = store.client.describe_collection(coll)
        field_names = {f["name"] for f in desc["fields"]}
        assert "embedding" in field_names, f"{coll} missing embedding field"
        # Sparse field name may vary; check index exists
        index_names = {idx["field_name"] for idx in desc.get("indexes", [])}
        has_dense = any("embedding" in idx for idx in index_names)
        assert has_dense, f"{coll} missing dense index"


def test_insert_and_search_event(store):
    """Insert a MemoryEvent and retrieve it via dense search."""
    store.create_all_collections()

    event = MemoryEvent(
        user_id="test_user_milvus",
        event_type="search",
        description="在春熙路搜索川渝火锅，人均预算80元",
        payload={"query": "火锅", "area": "春熙路"},
        session_id="sess_test",
    )

    # Insert with a dummy embedding (1024-dim)
    import random
    event.embedding = [random.random() for _ in range(1024)]
    eid = store.insert_event(event)
    assert eid is not None

    # Search
    results = store.search_dense(
        collection=COLLECTION_USER_EVENT,
        embedding=event.embedding,
        filter_expr=f'user_id == "test_user_milvus"',
        top_k=5,
    )
    assert len(results) > 0

    # Cleanup
    store.delete_by_id(COLLECTION_USER_EVENT, eid)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd agent-service && python -m pytest tests/storage/test_milvus_store.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write milvus_store.py**

```python
# src/storage/milvus_store.py
"""Milvus memory store for Event, Session, and AgentCase collections.

Provides:
- Collection creation (idempotent) with HNSW + SPARSE_INVERTED_INDEX
- Insert/upsert operations
- Dense vector search
- Sparse (BM25) vector search
- Delete by ID or filter
"""

import logging
import os
from pymilvus import MilvusClient, DataType

logger = logging.getLogger("pick.storage.milvus")

# ── Collection Names ──────────────────────────────────────────────────

COLLECTION_USER_EVENT = "user_event"
COLLECTION_USER_SESSION = "user_session"
COLLECTION_AGENT_CASE = "agent_case"

ALL_COLLECTIONS = [COLLECTION_USER_EVENT, COLLECTION_USER_SESSION, COLLECTION_AGENT_CASE]

# ── Embedding Config ──────────────────────────────────────────────────

EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

# Common HNSW index params
HNSW_PARAMS = {"M": 16, "efConstruction": 200}

# ── Collection Schemas ────────────────────────────────────────────────


def _make_event_schema(dim: int) -> dict:
    return {
        "fields": [
            {"name": "id", "dtype": DataType.VARCHAR, "is_primary": True, "max_length": 128},
            {"name": "user_id", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "event_type", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "description", "dtype": DataType.VARCHAR, "max_length": 4096},
            {"name": "payload", "dtype": DataType.VARCHAR, "max_length": 8192},
            {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": dim},
            {"name": "sparse_embedding", "dtype": DataType.SPARSE_FLOAT_VECTOR},
            {"name": "session_id", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "compressed", "dtype": DataType.BOOL},
            {"name": "compressed_from", "dtype": DataType.VARCHAR, "max_length": 4096},
            {"name": "ttl_seconds", "dtype": DataType.INT64},
            {"name": "expires_at", "dtype": DataType.INT64},
            {"name": "created_at", "dtype": DataType.INT64},
        ],
    }


def _make_session_schema(dim: int) -> dict:
    return {
        "fields": [
            {"name": "id", "dtype": DataType.VARCHAR, "is_primary": True, "max_length": 128},
            {"name": "user_id", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "summary", "dtype": DataType.VARCHAR, "max_length": 8192},
            {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": dim},
            {"name": "sparse_embedding", "dtype": DataType.SPARSE_FLOAT_VECTOR},
            {"name": "key_shops", "dtype": DataType.VARCHAR, "max_length": 4096},
            {"name": "key_areas", "dtype": DataType.VARCHAR, "max_length": 2048},
            {"name": "intent", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "is_complete", "dtype": DataType.BOOL},
            {"name": "created_at", "dtype": DataType.INT64},
            {"name": "updated_at", "dtype": DataType.INT64},
        ],
    }


def _make_agent_case_schema(dim: int) -> dict:
    return {
        "fields": [
            {"name": "id", "dtype": DataType.VARCHAR, "is_primary": True, "max_length": 128},
            {"name": "user_id", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "case_type", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "description", "dtype": DataType.VARCHAR, "max_length": 4096},
            {"name": "context", "dtype": DataType.VARCHAR, "max_length": 4096},
            {"name": "action", "dtype": DataType.VARCHAR, "max_length": 2048},
            {"name": "outcome", "dtype": DataType.VARCHAR, "max_length": 64},
            {"name": "outcome_reason", "dtype": DataType.VARCHAR, "max_length": 2048},
            {"name": "lesson", "dtype": DataType.VARCHAR, "max_length": 4096},
            {"name": "embedding", "dtype": DataType.FLOAT_VECTOR, "dim": dim},
            {"name": "sparse_embedding", "dtype": DataType.SPARSE_FLOAT_VECTOR},
            {"name": "created_at", "dtype": DataType.INT64},
            {"name": "ttl_seconds", "dtype": DataType.INT64},
        ],
    }


# ── Index Definitions ─────────────────────────────────────────────────


def _dense_index_params() -> dict:
    return {
        "field_name": "embedding",
        "index_type": "HNSW",
        "metric_type": "COSINE",
        "params": HNSW_PARAMS,
    }


def _sparse_index_params() -> dict:
    return {
        "field_name": "sparse_embedding",
        "index_type": "SPARSE_INVERTED_INDEX",
        "metric_type": "IP",  # Inner Product for sparse
        "params": {"drop_ratio_build": 0.2},
    }


# ── Store Class ───────────────────────────────────────────────────────


class MilvusMemoryStore:
    """Manages three Milvus collections for agent memory: user_event,
    user_session, agent_case. Each has dense (HNSW/COSINE) and sparse
    (INVERTED_INDEX/IP) search capability."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        embedding_dim: int = 1024,
    ):
        self._host = host
        self._port = port
        self._dim = embedding_dim
        self.client: MilvusClient | None = None

    def connect(self):
        """Initialize the MilvusClient connection."""
        uri = f"http://{self._host}:{self._port}"
        self.client = MilvusClient(uri=uri)
        logger.info("MilvusMemoryStore connected: %s", uri)

    # ── Collection Management ─────────────────────────────────────

    def create_all_collections(self) -> list[str]:
        """Create all three collections if they don't exist. Idempotent."""
        schemas = {
            COLLECTION_USER_EVENT: _make_event_schema(self._dim),
            COLLECTION_USER_SESSION: _make_session_schema(self._dim),
            COLLECTION_AGENT_CASE: _make_agent_case_schema(self._dim),
        }
        created = []
        for name, schema in schemas.items():
            if self.client.has_collection(name):
                logger.info("Collection %s already exists", name)
                created.append(name)
                continue
            self.client.create_collection(
                collection_name=name,
                schema=schema["fields"],
                # Enable dynamic schema for future field additions
                enable_dynamic_field=True,
            )
            # Create dense HNSW index
            self.client.create_index(
                collection_name=name,
                index_params=_dense_index_params(),
            )
            # Create sparse inverted index
            self.client.create_index(
                collection_name=name,
                index_params=_sparse_index_params(),
            )
            self.client.load_collection(name)
            logger.info("Created collection %s with HNSW + sparse indexes", name)
            created.append(name)
        return created

    def drop_all_collections(self):
        """Drop all three collections. Use with caution — for testing."""
        for name in ALL_COLLECTIONS:
            if self.client.has_collection(name):
                self.client.drop_collection(name)

    # ── Insert Operations ─────────────────────────────────────────

    def insert_event(self, event) -> str:
        """Insert a MemoryEvent into user_event collection."""
        from src.storage.models import MemoryEvent
        data = event.to_milvus_dict()
        data["id"] = event.id
        data["embedding"] = event.embedding or []
        self.client.insert(
            collection_name=COLLECTION_USER_EVENT,
            data=[data],
        )
        return event.id

    def insert_session(self, session) -> str:
        """Insert or upsert a SessionSummary into user_session."""
        from src.storage.models import SessionSummary
        data = session.to_milvus_dict()
        data["id"] = session.id
        data["embedding"] = session.embedding or []
        self.client.upsert(
            collection_name=COLLECTION_USER_SESSION,
            data=[data],
        )
        return session.id

    def insert_agent_case(self, case) -> str:
        """Insert an AgentCase into agent_case collection."""
        from src.storage.models import AgentCase
        data = case.to_milvus_dict()
        data["id"] = case.id
        data["embedding"] = case.embedding or []
        self.client.insert(
            collection_name=COLLECTION_AGENT_CASE,
            data=[data],
        )
        return case.id

    # ── Search Operations ─────────────────────────────────────────

    def search_dense(
        self,
        collection: str,
        embedding: list[float],
        filter_expr: str,
        top_k: int = 20,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """Dense vector search (HNSW/COSINE)."""
        if output_fields is None:
            output_fields = ["id", "user_id", "description", "created_at"]
        results = self.client.search(
            collection_name=collection,
            data=[embedding],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
        )
        return results[0] if results else []

    def search_sparse(
        self,
        collection: str,
        sparse_vector: dict[int, float],
        filter_expr: str,
        top_k: int = 20,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """Sparse vector search (BM25/IP)."""
        if output_fields is None:
            output_fields = ["id", "user_id", "description", "created_at"]
        results = self.client.search(
            collection_name=collection,
            data=[sparse_vector],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": "IP"},
        )
        return results[0] if results else []

    # ── Delete Operations ─────────────────────────────────────────

    def delete_by_id(self, collection: str, entity_id: str) -> None:
        """Delete a single entity by primary key."""
        self.client.delete(
            collection_name=collection,
            filter=f'id == "{entity_id}"',
        )

    def delete_by_filter(self, collection: str, filter_expr: str) -> None:
        """Delete entities matching a filter expression."""
        self.client.delete(
            collection_name=collection,
            filter=filter_expr,
        )

    def delete_expired(self, collection: str) -> int:
        """Delete all expired entities. Returns count deleted."""
        now = int(__import__("time").time())
        filter_expr = f"expires_at > 0 and expires_at <= {now}"
        # Milvus delete doesn't return count easily; we estimate
        self.client.delete(
            collection_name=collection,
            filter=filter_expr,
        )
        return 0  # Milvus doesn't return delete count
```

- [ ] **Step 4: Run integration tests**

```bash
cd agent-service && python -m pytest tests/storage/test_milvus_store.py -v
```

Expected: All tests PASS (requires Milvus access).

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/storage/milvus_store.py agent-service/tests/storage/test_milvus_store.py
git commit -m "feat: MilvusMemoryStore with user_event/user_session/agent_case collections"
```

---

### Task A6: PostgresSaver — LangGraph checkpoint persistence

**Files:**
- Create: `agent-service/src/storage/postgres_saver.py`
- Create: `agent-service/tests/storage/test_postgres_saver.py`

- [ ] **Step 1: Write postgres_saver.py**

```python
# src/storage/postgres_saver.py
"""PostgresSaver for LangGraph checkpoint persistence.

Replaces InMemorySaver. Checkpoints survive process restarts.
Session history no longer needs Redis — it's in the checkpointer.
"""

import logging
import os
from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger("pick.storage.postgres_saver")

# ── Config ────────────────────────────────────────────────────────────

PG_CHECKPOINT_URI = os.environ.get(
    "PG_CHECKPOINT_URI",
    "postgresql://pick:pick-pg-dev@localhost:5433/pick_agent_checkpoint",
)


class PostgresSaverManager:
    """Manages the lifecycle of a PostgresSaver instance.

    Usage:
        manager = PostgresSaverManager()
        await manager.setup()
        saver = manager.create_saver()
        # Pass saver to agent builder
    """

    def __init__(self, conn_string: str | None = None):
        self._conn_string = conn_string or PG_CHECKPOINT_URI
        self._saver: PostgresSaver | None = None

    async def setup(self) -> None:
        """Create the checkpoint tables if they don't exist."""
        saver = PostgresSaver.from_conn_string(self._conn_string)
        await saver.setup()
        logger.info("PostgresSaver tables initialized")
        self._saver = saver

    def create_saver(self) -> PostgresSaver:
        """Return a PostgresSaver instance for use with LangGraph.

        Must be called after setup().
        """
        if self._saver is not None:
            return self._saver
        # Create new instance; setup() is idempotent but we prefer explicit
        saver = PostgresSaver.from_conn_string(self._conn_string)
        logger.info("PostgresSaver created")
        return saver

    async def close(self) -> None:
        """Close the saver connection pool."""
        if self._saver:
            # PostgresSaver manages its own pool
            pass
        self._saver = None
```

- [ ] **Step 2: Write basic integration test**

```python
# tests/storage/test_postgres_saver.py
"""Integration tests for PostgresSaver. Requires Postgres running."""
import pytest
from src.storage.postgres_saver import PostgresSaverManager

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_setup_creates_tables():
    """setup() should not raise — tables created idempotently."""
    manager = PostgresSaverManager()
    await manager.setup()
    saver = manager.create_saver()
    assert saver is not None
    await manager.close()


@pytest.mark.asyncio
async def test_saver_can_checkpoint():
    """PostgresSaver should store and retrieve state."""
    from langgraph.graph import StateGraph, START, END
    from langgraph.checkpoint.base import empty_checkpoint

    manager = PostgresSaverManager()
    await manager.setup()
    saver = manager.create_saver()

    # Build a minimal graph to test checkpoint
    builder = StateGraph(dict)
    builder.add_node("echo", lambda s: s)
    builder.add_edge(START, "echo")
    builder.add_edge("echo", END)
    graph = builder.compile(checkpointer=saver)

    config = {"configurable": {"thread_id": "test_thread_1"}}
    result = await graph.ainvoke({"msg": "hello"}, config)
    assert result["msg"] == "hello"

    # Verify state persists
    state = graph.get_state(config)
    assert state is not None
    assert state.values["msg"] == "hello"

    await manager.close()
```

- [ ] **Step 3: Run integration test**

```bash
cd agent-service && python -m pytest tests/storage/test_postgres_saver.py -v
```

Expected: 2 tests PASS (requires Postgres from Task A1 Step 5).

- [ ] **Step 4: Commit**

```bash
git add agent-service/src/storage/postgres_saver.py agent-service/tests/storage/test_postgres_saver.py
git commit -m "feat: PostgresSaver for LangGraph checkpoint persistence"
```

---

### Task A7: Entity graph sync — seed Neo4j from MySQL

**Files:**
- Create: `agent-service/src/sync/__init__.py`
- Create: `agent-service/src/sync/entity_sync.py`
- Create: `agent-service/tests/sync/__init__.py`
- Create: `agent-service/tests/sync/test_entity_sync.py`

- [ ] **Step 1: Write entity_sync.py**

```python
# src/sync/entity_sync.py
"""One-time entity graph seeder: syncs Shop, Area, Category from MySQL → Neo4j.

Uses the existing Java sync endpoints (GET /api/sync/shops, etc.).
Also syncs ShopType (category) data from the Java API.
"""

import logging
import httpx
from src.storage.neo4j_client import Neo4jClient

logger = logging.getLogger("pick.sync.entity_sync")

# ── Config ────────────────────────────────────────────────────────────

JAVA_BASE_URL = "http://localhost:8085"
SYNC_TOKEN = "internal-dev-token"


async def sync_all_entities(neo4j: Neo4jClient, java_base_url: str = JAVA_BASE_URL) -> dict:
    """Run full entity graph sync. Returns counts of synced entities."""
    counts = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Sync shops (includes area and category info from JOIN)
        counts["shops"] = await _sync_shops(neo4j, client, java_base_url)

        # 2. Derive distinct areas from shops (area is a string field)
        counts["areas"] = await _sync_areas(neo4j, client, java_base_url)

        # 3. Sync categories from ShopType (need a new endpoint or extract from shops)
        counts["categories"] = await _sync_categories_from_shops(neo4j, client, java_base_url)

    return counts


async def _sync_shops(neo4j: Neo4jClient, client: httpx.AsyncClient, base_url: str) -> int:
    """Fetch all shops from Java sync endpoint and upsert to Neo4j."""
    count = 0
    headers = {"X-Internal-Token": SYNC_TOKEN}

    try:
        resp = await client.get(f"{base_url}/api/sync/shops", params={"since": 0}, headers=headers)
        resp.raise_for_status()
        shops = resp.json()
    except Exception:
        logger.exception("Failed to fetch shops from Java")
        return 0

    for shop in shops:
        try:
            shop_data = {
                "shop_id": str(shop["shopId"]),
                "name": shop.get("name", ""),
                "type": shop.get("type", ""),
                "sub_type": shop.get("subType", ""),
                "area": shop.get("area", ""),
                "address": shop.get("address", ""),
                "longitude": shop.get("longitude") or 0.0,
                "latitude": shop.get("latitude") or 0.0,
                "avg_price": shop.get("avgPrice") or 0,
                "score": shop.get("score") or 0,
            }
            await neo4j.upsert_shop(shop_data)

            # Link to Area
            if shop_data["area"]:
                await neo4j.upsert_area(shop_data["area"])
                await neo4j.link_shop_area(shop_data["shop_id"], shop_data["area"])

            count += 1
        except Exception:
            logger.exception("Failed to sync shop %s", shop.get("shopId"))

    logger.info("Synced %d shops to Neo4j", count)
    return count


async def _sync_areas(neo4j: Neo4jClient, client: httpx.AsyncClient, base_url: str) -> int:
    """Extract distinct areas from the shop list and create Area nodes.

    Since area is just a string field on Shop (not a separate table),
    we derive distinct area names from the shop data.
    """
    headers = {"X-Internal-Token": SYNC_TOKEN}
    try:
        resp = await client.get(f"{base_url}/api/sync/shops", params={"since": 0}, headers=headers)
        resp.raise_for_status()
        shops = resp.json()
    except Exception:
        logger.exception("Failed to fetch shops for area extraction")
        return 0

    areas = {shop.get("area") for shop in shops if shop.get("area")}
    for area_name in areas:
        await neo4j.upsert_area(area_name)
    logger.info("Synced %d areas to Neo4j", len(areas))
    return len(areas)


async def _sync_categories_from_shops(neo4j: Neo4jClient, client: httpx.AsyncClient, base_url: str) -> int:
    """Extract category hierarchy from shop data (type + subType).

    The Shop sync already JOINs ShopType to get type (parent) and subType (child).
    We extract distinct pairs from the shop list to build the Category tree.
    """
    headers = {"X-Internal-Token": SYNC_TOKEN}
    try:
        resp = await client.get(f"{base_url}/api/sync/shops", params={"since": 0}, headers=headers)
        resp.raise_for_status()
        shops = resp.json()
    except Exception:
        logger.exception("Failed to fetch shops for category extraction")
        return 0

    # Collect type → subType pairs
    cat_pairs = set()
    for shop in shops:
        main_type = shop.get("type", "")
        sub_type = shop.get("subType", "")
        if main_type and sub_type:
            cat_pairs.add((main_type, sub_type))

    # Assign synthetic IDs since ShopType IDs aren't in the sync DTO
    cat_id = 0
    parent_ids = {}  # name → id
    count = 0
    for main_type, sub_type in sorted(cat_pairs):
        # Ensure parent category exists
        if main_type not in parent_ids:
            cat_id += 1
            parent_ids[main_type] = cat_id
            await neo4j.upsert_category({
                "category_id": str(cat_id),
                "name": main_type,
                "parent_id": None,
            })
            count += 1

        # Create child category
        cat_id += 1
        await neo4j.upsert_category({
            "category_id": str(cat_id),
            "name": sub_type,
            "parent_id": str(parent_ids[main_type]),
        })
        count += 1

    logger.info("Synced %d categories to Neo4j", count)
    return count
```

- [ ] **Step 2: Write entity sync test**

```python
# tests/sync/test_entity_sync.py
"""Tests for entity graph sync."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.sync.entity_sync import sync_all_entities, _sync_shops, _sync_areas


@pytest.mark.asyncio
async def test_sync_shops_empty():
    """Sync should handle empty shop list gracefully."""
    neo4j = AsyncMock()
    neo4j.upsert_shop = AsyncMock()
    neo4j.upsert_area = AsyncMock()
    neo4j.link_shop_area = AsyncMock()

    import httpx
    # Mock httpx to return empty list
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        count = await _sync_shops(neo4j, mock_client, "http://test")
        assert count == 0


@pytest.mark.asyncio
async def test_sync_shops_with_data():
    """Sync should upsert each shop from the API response."""
    neo4j = AsyncMock()
    neo4j.upsert_shop = AsyncMock()
    neo4j.upsert_area = AsyncMock()
    neo4j.link_shop_area = AsyncMock()

    shop_data = [
        {
            "shopId": 1, "name": "蜀大侠火锅", "type": "美食",
            "subType": "川渝火锅", "area": "春熙路", "address": "春熙路88号",
            "longitude": 104.08, "latitude": 30.66,
            "avgPrice": 80, "score": 4.5,
        },
        {
            "shopId": 2, "name": "点都德", "type": "美食",
            "subType": "粤菜", "area": "太古里", "address": "太古里10号",
            "longitude": 104.09, "latitude": 30.65,
            "avgPrice": 60, "score": 4.2,
        },
    ]

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.json.return_value = shop_data
        mock_resp.raise_for_status = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value.__aenter__.return_value = mock_client

        count = await _sync_shops(neo4j, mock_client, "http://test")
        assert count == 2
        assert neo4j.upsert_shop.call_count == 2
        assert neo4j.upsert_area.call_count == 2
        assert neo4j.link_shop_area.call_count == 2
```

- [ ] **Step 3: Run tests**

```bash
cd agent-service && python -m pytest tests/sync/test_entity_sync.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 4: Write sync __init__.py**

```python
# src/sync/__init__.py
"""Data sync module: MySQL → Neo4j entity graph seeding."""
from src.sync.entity_sync import sync_all_entities

__all__ = ["sync_all_entities"]
```

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/sync/ agent-service/tests/sync/
git commit -m "feat: entity graph sync from MySQL to Neo4j (Shop, Area, Category)"
```

---

### Task A8: Replace InMemorySaver with PostgresSaver

**Files:**
- Modify: `agent-service/src/agent/agent.py`
- Modify: `agent-service/src/main.py`

- [ ] **Step 1: Update agent.py to use PostgresSaver**

In `agent.py`, change the `create_pick_agent()` function to accept a checkpointer parameter:

Replace lines 196-297 of `agent.py`. The key change is modifying `create_pick_agent()` to accept an optional `checkpointer` argument:

```python
# In agent.py, replace the function signature and the checkpointer line:

def create_pick_agent(checkpointer=None) -> "CompiledStateGraph":
    """Build and compile the Pick AI Shopping Guide agent graph.

    Args:
        checkpointer: A LangGraph checkpointer instance.
                     If None, falls back to InMemorySaver.

    The compiled graph exposes:
    - .astream(input, config)  → async streaming iterator
    - .ainvoke(input, config)  → async single invocation
    - .get_state(config)       → retrieve current conversation state
    """
    model = get_model()

    if checkpointer is None:
        checkpointer = InMemorySaver()
        logger.warning("No checkpointer provided, using InMemorySaver (not persistent)")

    # ... rest of the function stays the same, just use `checkpointer` variable
    # Replace the line: checkpointer = InMemorySaver()
    # With the parameter passed in

    # At the end: return builder.compile(checkpointer=checkpointer)
```

The edit is minimal — just change the function to accept a `checkpointer` parameter. Read the full `agent.py` first, then apply these changes:

1. Change function signature: `def create_pick_agent(checkpointer=None) -> "CompiledStateGraph":`
2. Replace `checkpointer = InMemorySaver()` with:
   ```python
   if checkpointer is None:
       checkpointer = InMemorySaver()
       logger.warning("No checkpointer provided, using InMemorySaver (not persistent)")
   ```

- [ ] **Step 2: Update main.py to initialize PostgresSaver in lifespan**

In `main.py`, modify the lifespan to initialize PostgresSaver:

```python
# Add imports at top of main.py:
from src.storage.postgres_saver import PostgresSaverManager

# Modify the lifespan:
@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: startup and shutdown."""
    global _agent

    # Initialize PostgresSaver
    pg_manager = PostgresSaverManager()
    try:
        await pg_manager.setup()
        saver = pg_manager.create_saver()
        logger.info("PostgresSaver initialized")
    except Exception:
        logger.exception("PostgresSaver setup failed, falling back to InMemorySaver")
        saver = None

    logger.info("Initializing Pick AI agent...")
    _agent = create_pick_agent(checkpointer=saver)
    logger.info("Agent initialized successfully")
    app.state.pg_manager = pg_manager
    yield
    logger.info("Shutting down Pick AI agent...")
    await pg_manager.close()
    _agent = None
```

- [ ] **Step 3: Remove redis_history imports and calls from main.py**

Remove these lines from `main.py`:
```python
# Remove:
from src.agent.memory.redis_history import (
    generate_session_id,
    load_history,
    save_history,
)
```

Replace `generate_session_id()` with `uuid.uuid4().hex` (add `import uuid` at top).

Replace `load_history(session_id)` calls — since PostgresSaver now persists checkpoints, the load/save history logic is no longer needed. Remove all `await load_history(...)` and `await save_history(...)` and `await _save_history_safe(...)` calls.

The simplified `chat()` endpoint becomes:

```python
@app.post("/chat")
async def chat(request: ChatRequest, agent=Depends(get_agent)):
    import uuid
    session_id = request.session_id or uuid.uuid4().hex
    config = {"configurable": {"thread_id": session_id}}

    async def _generate():
        async for sse_event in stream_agent_response(
            query=request.query,
            history=[],  # Checkpointer handles history now
            agent=agent,
            config=config,
        ):
            yield sse_event

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"content-type": "text/event-stream"},
    )
```

Similarly simplify `chat_resume()` — remove all `load_history()` calls, the checkpointer handles state restoration.

- [ ] **Step 4: Run existing chat tests to verify no breakage**

```bash
cd agent-service && python -m pytest tests/test_chat.py -v
```

Expected: Tests may need minor adjustment (session_id format changes). Fix any failures. Core chat functionality must still work.

- [ ] **Step 5: Commit**

```bash
git add agent-service/src/agent/agent.py agent-service/src/main.py
git commit -m "feat: replace InMemorySaver with PostgresSaver, remove redis_history dependency"
```

---

### Task A9: Delete redis_history.py and clean up

**Files:**
- Delete: `agent-service/src/agent/memory/redis_history.py`
- Modify: `agent-service/src/agent/memory/__init__.py`

- [ ] **Step 1: Delete redis_history.py**

```bash
rm agent-service/src/agent/memory/redis_history.py
```

- [ ] **Step 2: Update memory __init__.py**

```python
# src/agent/memory/__init__.py
"""Memory module — DEPRECATED.

Redis-based session history has been replaced by PostgresSaver.
This module is kept for backward compatibility; new code should use
src.storage.postgres_saver and src.storage.neo4j_client.
"""
```

- [ ] **Step 3: Verify no imports reference redis_history**

```bash
cd agent-service && grep -r "redis_history" src/ tests/ || echo "No references found"
```

Expected: "No references found" (or only this __init__.py comment).

- [ ] **Step 4: Commit**

```bash
git rm agent-service/src/agent/memory/redis_history.py
git add agent-service/src/agent/memory/__init__.py
git commit -m "refactor: delete redis_history.py (replaced by PostgresSaver)"
```

---

### Task A10: Integration verification — run entity sync end-to-end

**Files:**
- Create: `agent-service/scripts/sync_entities.py`

- [ ] **Step 1: Write the sync runner script**

```python
# scripts/sync_entities.py
"""One-shot script: sync MySQL → Neo4j entity graph.

Usage:
    python scripts/sync_entities.py

Requires:
- Java backend running on localhost:8085
- Neo4j running on localhost:7687
"""

import asyncio
import logging
from src.storage.neo4j_client import Neo4jClient
from src.sync.entity_sync import sync_all_entities

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_entities")


async def main():
    neo4j = Neo4jClient(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="pick-neo4j-dev",
    )
    await neo4j.connect()
    try:
        counts = await sync_all_entities(neo4j)
        logger.info("Sync complete: %s", counts)
    finally:
        await neo4j.close()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Run the sync (requires Java backend running)**

```bash
cd agent-service && python scripts/sync_entities.py
```

Expected: Log output showing shop/area/category counts synced.

- [ ] **Step 3: Verify Neo4j has data**

```bash
docker exec pick-neo4j cypher-shell -u neo4j -p pick-neo4j-dev "MATCH (s:Shop) RETURN count(s) AS shop_count"
```

Expected: `shop_count` > 0.

- [ ] **Step 4: Commit**

```bash
git add agent-service/scripts/sync_entities.py
git commit -m "feat: entity sync runner script"
```

---

## Plan A Completion Checklist

- [ ] Docker services running: Neo4j (7687), Postgres (5433)
- [ ] Neo4j constraints and indexes created
- [ ] Three Milvus collections exist with HNSW + sparse indexes
- [ ] Data models importable: `from src.storage.models import TastePreference, MemoryEvent, ...`
- [ ] Neo4jClient CRUD works (integration tests pass)
- [ ] MilvusMemoryStore insert/search works (integration tests pass)
- [ ] PostgresSaver checkpoints survive across agent invocations
- [ ] Entity sync seeds Shop/Area/Category nodes in Neo4j
- [ ] `agent.py` uses PostgresSaver instead of InMemorySaver
- [ ] `main.py` no longer imports from `redis_history`
- [ ] `redis_history.py` is deleted
- [ ] Existing chat tests still pass

**Plan B and Plan C can start once:**
1. Task A2 (data models) is complete — they need `src/storage/models.py`
2. Task A4 (Neo4jClient interface) is complete — they code against its API
3. Task A5 (MilvusMemoryStore interface) is complete — they code against its API

They can develop against the interfaces defined here while the rest of Plan A is still in progress.
