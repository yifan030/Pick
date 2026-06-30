"""Profile atom and memory event models — to be fully implemented by Plans A & B.

Current minimal definitions are sufficient for Plan C retrieval pipeline
development and testing. Plan B will add full validation, Neo4j/Cypher
mapping, and the complete merge/revise/expiry lifecycle.
"""

from __future__ import annotations
from typing import Union, Dict, List, Optional

# ── Confidence & Delta Constants ────────────────────────────────────────

DELTA_REINFORCE = 0.10
DELTA_DELETE = -1.0
DELTA_REVISE = 0.05
MAX_CONFIDENCE = 0.95


# ── Base Profile Atom ───────────────────────────────────────────────────

class BaseProfile:
    """Base class for all profile atoms stored in Neo4j."""

    __node_type__: str = "BaseProfile"

    @classmethod
    def node_type(cls) -> str:
        return cls.__node_type__


# ── Profile Atom Classes ────────────────────────────────────────────────

class TastePreference(BaseProfile):
    """User taste preference. e.g. spicy=avoid, sweet=like."""

    __node_type__ = "TastePreference"

    def __init__(
        self,
        user_id: str,
        property: str = "",
        value: str = "like",
        confidence: float = 0.5,
        reinforce_count: int = 0,
        is_hard: bool = False,
    ):
        self.user_id = user_id
        self.property = property
        self.value = value  # "like" | "avoid" | "neutral"
        self.confidence = confidence
        self.reinforce_count = reinforce_count
        self.is_hard = is_hard


class DietaryPreference(BaseProfile):
    """Dietary constraint. e.g. 清真, 素食."""

    __node_type__ = "DietaryPreference"

    def __init__(
        self,
        user_id: str,
        constraint: str = "",
        type: str = "",
        confidence: float = 0.5,
    ):
        self.user_id = user_id
        self.constraint = constraint
        self.type = type  # "religious" | "health" | "lifestyle" | "allergy"
        self.confidence = confidence


class BudgetPreference(BaseProfile):
    """Per-person budget range."""

    __node_type__ = "BudgetPreference"

    def __init__(
        self,
        user_id: str,
        range_min: float = 0,
        range_max: float = 0,
        confidence: float = 0.5,
    ):
        self.user_id = user_id
        self.range_min = range_min
        self.range_max = range_max
        self.confidence = confidence


class CuisinePreference(BaseProfile):
    """Cuisine type preference. e.g. 川渝火锅, 粤菜."""

    __node_type__ = "CuisinePreference"

    def __init__(
        self,
        user_id: str,
        cuisine: str = "",
        confidence: float = 0.5,
        weight: float = 0.5,
    ):
        self.user_id = user_id
        self.cuisine = cuisine
        self.confidence = confidence
        self.weight = weight


class AreaPreference(BaseProfile):
    """Business district preference. e.g. 春熙路, 太古里."""

    __node_type__ = "AreaPreference"

    def __init__(
        self,
        user_id: str,
        area: str = "",
        confidence: float = 0.5,
        weight: float = 0.5,
    ):
        self.user_id = user_id
        self.area = area
        self.confidence = confidence
        self.weight = weight


class ScenePreference(BaseProfile):
    """Dining scene preference. e.g. 约会, 聚餐, 一人食."""

    __node_type__ = "ScenePreference"

    def __init__(
        self,
        user_id: str,
        scene: str = "",
        confidence: float = 0.5,
        weight: float = 0.5,
    ):
        self.user_id = user_id
        self.scene = scene
        self.confidence = confidence
        self.weight = weight


class ConstraintPreference(BaseProfile):
    """Free-form constraint. e.g. "不要排队太久", "必须有包间"."""

    __node_type__ = "ConstraintPreference"

    def __init__(
        self,
        user_id: str,
        constraint: str = "",
        confidence: float = 0.5,
    ):
        self.user_id = user_id
        self.constraint = constraint
        self.confidence = confidence


# ── Union type for all profile atoms ─────────────────────────────────────

AnyProfile = Union[
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
]


# ── Memory Event / Session / Agent Case stubs ───────────────────────────

class MemoryEvent:
    """A single user interaction event stored in Milvus."""

    def __init__(
        self,
        id: str = "",
        user_id: str = "",
        event_type: str = "",
        description: str = "",
        payload: dict | None = None,
        created_at: str = "",
    ):
        self.id = id
        self.user_id = user_id
        self.event_type = event_type
        self.description = description
        self.payload = payload or {}
        self.created_at = created_at


class SessionSummary:
    """Summary of a conversation session stored in Milvus."""

    def __init__(
        self,
        id: str = "",
        user_id: str = "",
        summary: str = "",
        key_shops: list[str] | None = None,
        key_areas: list[str] | None = None,
        intent: str = "",
        is_complete: bool = False,
        created_at: str = "",
    ):
        self.id = id
        self.user_id = user_id
        self.summary = summary
        self.key_shops = key_shops or []
        self.key_areas = key_areas or []
        self.intent = intent
        self.is_complete = is_complete
        self.created_at = created_at


class AgentCase:
    """An agent decision case stored for experience-based retrieval."""

    def __init__(
        self,
        id: str = "",
        user_id: str = "",
        case_type: str = "",
        description: str = "",
        context: dict | None = None,
        action: str = "",
        outcome: str = "",
        outcome_reason: str = "",
        lesson: str = "",
        created_at: str = "",
    ):
        self.id = id
        self.user_id = user_id
        self.case_type = case_type
        self.description = description
        self.context = context or {}
        self.action = action
        self.outcome = outcome
        self.outcome_reason = outcome_reason
        self.lesson = lesson
        self.created_at = created_at
