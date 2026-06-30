from __future__ import annotations

"""Storage layer stubs — to be fully implemented by Plan A.

Provides the interfaces that the retrieval pipeline (Plan C) depends on.
"""

from src.storage.models import (  # noqa: F401
    # Profile atoms
    AnyProfile,
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    # Event/session models
    MemoryEvent,
    SessionSummary,
    AgentCase,
    # Deltas
    DELTA_REINFORCE,
    DELTA_DELETE,
    DELTA_REVISE,
)
