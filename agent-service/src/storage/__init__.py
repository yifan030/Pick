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
