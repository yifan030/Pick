# src/storage/models.py
"""Shared data models for the agent memory system.

These dataclasses are the canonical in-memory representation of all memory
types. They are used by Plans A, B, and C. Storage backends (Neo4j, Milvus)
convert to/from these types.

Profile atoms live in Neo4j as labeled nodes.
Events, Sessions, and AgentCases live in Milvus as vector-searchable documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import json
import time
from typing import Any, Union


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
AnyProfile = Union[
    TastePreference, DietaryPreference, BudgetPreference,
    CuisinePreference, AreaPreference, ScenePreference,
    ConstraintPreference,
]


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
    context: dict[str, Any] = field(default_factory=dict)
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
