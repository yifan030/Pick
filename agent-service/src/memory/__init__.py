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

from src.memory.pipeline import MemoryPipeline
from src.memory.extractor import EventExtractor
from src.memory.profile_updater import ProfileUpdater
from src.memory.session_summarizer import SessionSummarizer
from src.memory.agent_case_extractor import AgentCaseExtractor
from src.memory.consolidation import ConsolidationJob
from src.memory.cleanup import CleanupJob

__all__ = [
    "MemoryPipeline",
    "EventExtractor",
    "ProfileUpdater",
    "SessionSummarizer",
    "AgentCaseExtractor",
    "ConsolidationJob",
    "CleanupJob",
]
