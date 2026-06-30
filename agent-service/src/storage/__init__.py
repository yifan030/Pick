"""Storage layer: data models, embedding, database clients, and data sync.

This module provides:
- Data models for all memory types (Profile atoms, Events, Sessions, AgentCases)
- Embedding client (text + multimodal)
- Neo4j client (profile CRUD + entity graph)
- Milvus memory store (collections + search)
- Postgres checkpoint saver
- Data sync pipelines (shop desc, user notes from Java)
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

from src.storage.embedding import embed_texts, embed_single

__all__ = [
    # Models
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
    # Embedding
    "embed_texts",
    "embed_single",
]
