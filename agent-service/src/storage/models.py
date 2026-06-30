"""Memory data models for the write pipeline.

These dataclasses represent the structured memory types that flow through
the extraction → filtering → update → audit pipeline.

All types are defined here so importers only need src.storage.models.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Union

# ── Delta Operation Constants ────────────────────────────────────────────

DELTA_ADD = "ADD"
DELTA_REINFORCE = "REINFORCE"
DELTA_REVISE = "REVISE"
DELTA_DELETE = "DELETE"
DELTA_MERGE = "MERGE"
DELTA_NOCHANGE = "NOCHANGE"
DELTA_EXPIRE = "EXPIRE"

# ── Base Profile ─────────────────────────────────────────────────────────

@dataclass
class ProfileBase:
    """Common fields and behaviour for all profile atom types."""

    user_id: str = ""
    confidence: float = 0.6
    created_at: int = field(default_factory=lambda: int(time.time()))
    updated_at: int = field(default_factory=lambda: int(time.time()))
    ttl_seconds: int | None = None  # None = permanent
    expires_at: int | None = None

    def node_type(self) -> str:
        """Return the Neo4j-friendly node type name."""
        return type(self).__name__

    def is_expired(self) -> bool:
        """Check whether this profile atom has passed its TTL."""
        if self.expires_at is None:
            return False
        return int(time.time()) >= self.expires_at

    def is_hard(self) -> bool:
        """Override in subclasses that represent hard constraints."""
        return getattr(self, "is_hard", False)


# ── Profile Subtypes ─────────────────────────────────────────────────────

@dataclass
class TastePreference(ProfileBase):
    """Taste preference: e.g. spicy=like, sweet=avoid."""

    property: str = ""
    value: str = ""          # "like" | "avoid"
    reinforce_count: int = 0


@dataclass
class DietaryPreference(ProfileBase):
    """Dietary hard constraint: e.g. halal, vegetarian, allergen."""

    constraint: str = ""
    type: str = ""           # "religious" | "health" | "allergy" | "ethical"
    is_hard: bool = True
    confidence: float = 1.0  # Hard constraints start at max confidence


@dataclass
class BudgetPreference(ProfileBase):
    """Budget range: e.g. per_person 50-100 CNY."""

    range_min: int = 0
    range_max: int = 9999
    type: str = "per_person"  # "per_person" | "total"


@dataclass
class CuisinePreference(ProfileBase):
    """Cuisine preference: e.g. Sichuan, Cantonese."""

    cuisine: str = ""
    weight: float = 0.7
    reinforce_count: int = 0


@dataclass
class AreaPreference(ProfileBase):
    """Area preference: e.g. Chunxi Road, Taikoo Li."""

    area: str = ""
    weight: float = 0.7


@dataclass
class ScenePreference(ProfileBase):
    """Scene preference: e.g. date, family dinner, business."""

    scene: str = ""
    weight: float = 0.7


@dataclass
class ConstraintPreference(ProfileBase):
    """Soft constraint: e.g. "no spicy", "quiet environment"."""

    constraint: str = ""
    type: str = ""


# ── Union type ───────────────────────────────────────────────────────────

AnyProfile = Union[
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
]


# ── Memory Event ─────────────────────────────────────────────────────────

@dataclass
class MemoryEvent:
    """A single behavioural event extracted from a conversation turn.

    Events are stored in Milvus collection `user_event` for semantic
    similarity search by VectorPreFilter.
    """

    user_id: str = ""
    event_type: str = "unknown"
    description: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    session_id: str = ""
    ttl_seconds: int | None = None
    compressed: bool = False
    compressed_from: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return int(time.time()) >= self.expires_at


# ── Delta Operation ──────────────────────────────────────────────────────

@dataclass
class DeltaOperation:
    """A single profile delta computed by ProfileUpdater.

    One of: ADD, REINFORCE, REVISE, DELETE, MERGE, NOCHANGE, EXPIRE.
    """

    op: str = DELTA_NOCHANGE
    target_type: str = ""
    target_id: str | None = None
    old_value: AnyProfile | None = None
    new_value: AnyProfile | None = None
    reason: str = ""

    def to_audit_dict(self) -> dict:
        """Convert to a dict suitable for AuditLogger JSONL output."""
        d: dict[str, Any] = {
            "op": self.op,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "reason": self.reason,
        }
        if self.old_value is not None:
            d["old_value"] = {
                k: v for k, v in self.old_value.__dict__.items()
                if not k.startswith("_")
            }
        if self.new_value is not None:
            d["new_value"] = {
                k: v for k, v in self.new_value.__dict__.items()
                if not k.startswith("_")
            }
        return d


# ── Session Summary ──────────────────────────────────────────────────────

@dataclass
class SessionSummary:
    """An incremental or final session summary stored in Milvus."""

    user_id: str = ""
    summary: str = ""
    key_shops: list[str] = field(default_factory=list)
    key_areas: list[str] = field(default_factory=list)
    intent: str = ""
    is_complete: bool = False
    embedding: list[float] | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: int = field(default_factory=lambda: int(time.time()))


# ── Agent Case ───────────────────────────────────────────────────────────

@dataclass
class AgentCase:
    """An agent experience case extracted from a recommendation outcome.

    Stored in Milvus collection `agent_case` with 180-day TTL.
    """

    user_id: str = ""
    case_type: str = "recommendation"
    description: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    action: str = ""
    outcome: str = "unknown"  # "success" | "failure" | "ignored" | "rejected"
    outcome_reason: str = ""
    lesson: str = ""
    ttl_seconds: int = 15552000  # 180 days
    embedding: list[float] | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    created_at: int = field(default_factory=lambda: int(time.time()))
