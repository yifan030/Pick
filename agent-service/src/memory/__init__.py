# src/memory/__init__.py
"""Memory write pipeline — extraction, updating, lifecycle management.

Public API:
- MemoryPipeline: orchestrates all extractors (use this from main.py)
- EventExtractor: conversation turn → structured events
- ProfileUpdater: events + existing profiles → delta operations
- SessionSummarizer: incremental session summaries
- AgentCaseExtractor: recommendation outcomes → agent patterns
- ConsolidationJob: profile dedup scheduled task
- CleanupJob: TTL expiry + event compression + anti-bloat
- ColdStartManager: behavior data import for new users
"""

from src.memory import prompts

# Lazy imports for modules that don't exist yet (B2-B10 / D3)
try:
    from src.memory.pipeline import MemoryPipeline
except (ModuleNotFoundError, TypeError):
    MemoryPipeline = None  # type: ignore

try:
    from src.memory.extractor import EventExtractor
except (ModuleNotFoundError, TypeError):
    EventExtractor = None  # type: ignore

try:
    from src.memory.profile_updater import ProfileUpdater
except (ModuleNotFoundError, TypeError):
    ProfileUpdater = None  # type: ignore

try:
    from src.memory.session_summarizer import SessionSummarizer
except (ModuleNotFoundError, TypeError):
    SessionSummarizer = None  # type: ignore

try:
    from src.memory.agent_case_extractor import AgentCaseExtractor
except (ModuleNotFoundError, TypeError):
    AgentCaseExtractor = None  # type: ignore

try:
    from src.memory.consolidation import ConsolidationJob
except (ModuleNotFoundError, TypeError):
    ConsolidationJob = None  # type: ignore

try:
    from src.memory.cleanup import CleanupJob
except (ModuleNotFoundError, TypeError):
    CleanupJob = None  # type: ignore

try:
    from src.memory.cold_start import ColdStartManager
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
