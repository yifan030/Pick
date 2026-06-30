"""Storage layer: data models, embedding, and database client interfaces.

These types are used by the memory write pipeline (src.memory.*).
"""

from src.storage.models import (
    # Events
    MemoryEvent,
    # Profile atoms
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    AnyProfile,
    # Delta operations
    DeltaOperation,
    DELTA_ADD,
    DELTA_REINFORCE,
    DELTA_REVISE,
    DELTA_DELETE,
    DELTA_MERGE,
    DELTA_NOCHANGE,
    DELTA_EXPIRE,
    # Session & Agent Cases
    SessionSummary,
    AgentCase,
)

__all__ = [
    "MemoryEvent",
    "TastePreference",
    "DietaryPreference",
    "BudgetPreference",
    "CuisinePreference",
    "AreaPreference",
    "ScenePreference",
    "ConstraintPreference",
    "AnyProfile",
    "DeltaOperation",
    "DELTA_ADD",
    "DELTA_REINFORCE",
    "DELTA_REVISE",
    "DELTA_DELETE",
    "DELTA_MERGE",
    "DELTA_NOCHANGE",
    "DELTA_EXPIRE",
    "SessionSummary",
    "AgentCase",
]
