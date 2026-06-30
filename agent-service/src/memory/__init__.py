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
"""

from src.memory import prompts

# Lazy imports for modules that don't exist yet (B2-B10)
try:
    from src.memory.pipeline import MemoryPipeline
except ModuleNotFoundError:
    MemoryPipeline = None  # type: ignore

try:
    from src.memory.extractor import EventExtractor
except ModuleNotFoundError:
    EventExtractor = None  # type: ignore

try:
    from src.memory.profile_updater import ProfileUpdater
except ModuleNotFoundError:
    ProfileUpdater = None  # type: ignore

try:
    from src.memory.session_summarizer import SessionSummarizer
except ModuleNotFoundError:
    SessionSummarizer = None  # type: ignore

try:
    from src.memory.agent_case_extractor import AgentCaseExtractor
except ModuleNotFoundError:
    AgentCaseExtractor = None  # type: ignore

try:
    from src.memory.consolidation import ConsolidationJob
except ModuleNotFoundError:
    ConsolidationJob = None  # type: ignore

try:
    from src.memory.cleanup import CleanupJob
except ModuleNotFoundError:
    CleanupJob = None  # type: ignore

__all__ = [
    "prompts",
    "MemoryPipeline",
    "EventExtractor",
    "ProfileUpdater",
    "SessionSummarizer",
    "AgentCaseExtractor",
    "ConsolidationJob",
    "CleanupJob",
]
