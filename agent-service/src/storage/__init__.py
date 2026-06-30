"""Storage layer: data models, embedding, and database client interfaces.

These types are used by both Plan B (memory write pipeline) and Plan C (memory read pipeline).
"""

from src.storage.models import (
    # Profile atoms
    ProfileBase,
    # Events
    MemoryEvent,
    # Profile subtypes
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    AnyProfile,
    # Session & Agent Cases
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
    "ProfileBase",
    "MemoryEvent",
    "TastePreference",
    "DietaryPreference",
    "BudgetPreference",
    "CuisinePreference",
    "AreaPreference",
    "ScenePreference",
    "ConstraintPreference",
    "AnyProfile",
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
