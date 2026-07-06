# src/memory/__init__.py
"""Memory write pipeline — extraction, updating, lifecycle management.

Organised by memory type (per the five-type memory model):
- event/    — behavioural events (Milvus: user_event)
- profile/  — user preference atoms (Neo4j: 7 Profile node types)
- session/  — session summaries (Milvus: user_session)
- case/     — agent experience cases (Milvus: agent_case)
- control/  — user-facing memory CRUD
- lifecycle/— cross-type cleanup & maintenance
- audit/    — change audit logging

Public API:
- MemoryPipeline: orchestrates all extractors (use this from main.py)
- EventExtractor: conversation turn -> structured events
- ProfileUpdater: events + existing profiles -> delta operations
- SessionSummarizer: incremental session summaries
- AgentCaseExtractor: recommendation outcomes -> agent patterns
- ConsolidationJob: profile dedup scheduled task
- CleanupJob: TTL expiry + event compression + anti-bloat
- ColdStartManager: behaviour data import for new users
"""

from src.memory import prompts

# Lazy imports for modules that don't exist yet (B2-B10 / D3)
try:
    from src.memory.pipeline import MemoryPipeline
except (ModuleNotFoundError, TypeError):
    MemoryPipeline = None  # type: ignore

try:
    from src.memory.event.extractor import EventExtractor
except (ModuleNotFoundError, TypeError):
    EventExtractor = None  # type: ignore

try:
    from src.memory.profile.updater import ProfileUpdater
except (ModuleNotFoundError, TypeError):
    ProfileUpdater = None  # type: ignore

try:
    from src.memory.session.summarizer import SessionSummarizer
except (ModuleNotFoundError, TypeError):
    SessionSummarizer = None  # type: ignore

try:
    from src.memory.case.extractor import AgentCaseExtractor
except (ModuleNotFoundError, TypeError):
    AgentCaseExtractor = None  # type: ignore

try:
    from src.memory.profile.consolidation import ConsolidationJob
except (ModuleNotFoundError, TypeError):
    ConsolidationJob = None  # type: ignore

try:
    from src.memory.lifecycle.cleanup import CleanupJob
except (ModuleNotFoundError, TypeError):
    CleanupJob = None  # type: ignore

try:
    from src.memory.profile.cold_start import ColdStartManager
except (ModuleNotFoundError, TypeError):
    ColdStartManager = None  # type: ignore

__all__ = [
    "prompts",
    "MemoryPipeline",
    "EventExtractor",
    "ProfileUpdater",
    "SessionSummarizer",
    "AgentCaseExtractor",
    "ConsolidationJob",
    "CleanupJob",
    "ColdStartManager",
]
