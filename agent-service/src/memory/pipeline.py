# src/memory/pipeline.py
"""Memory Pipeline: orchestrates all memory extractors.

Main entry point for the write path. Called asynchronously after each
SSE stream completes. Runs in background (asyncio.create_task).

Flow:
  1. EventExtractor: conversation → structured events
  2. VectorPreFilter: events → relevant existing profiles
  3. ProfileUpdater: events + profiles → delta operations → Neo4j
  4. AgentCaseExtractor: recommendations + feedback → agent cases
  5. SessionSummarizer: incrementally writes session summaries
  6. AuditLogger: records all profile changes → memory_diff.jsonl
"""

from __future__ import annotations

import logging
from typing import Any
from src.memory.event.extractor import EventExtractor
from src.memory.event.pre_filter import VectorPreFilter
from src.memory.profile.updater import ProfileUpdater
from src.memory.session.summarizer import SessionSummarizer
from src.memory.case.extractor import AgentCaseExtractor
from src.memory.audit.logger import AuditLogger
from src.storage.embedding import embed_texts

logger = logging.getLogger("pick.memory.pipeline")


class MemoryPipeline:
    """Orchestrates the full memory extraction pipeline."""

    def __init__(self, neo4j_client, milvus_store, model: Any = None):
        if model is None:
            from src.agent.config import get_extractor_model
            model = get_extractor_model()
        self._neo4j = neo4j_client
        self._milvus = milvus_store
        self._model = model
        self._event_extractor: EventExtractor | None = None
        self._pre_filter: VectorPreFilter | None = None
        self._profile_updater: ProfileUpdater | None = None
        self._session_summarizer: SessionSummarizer | None = None
        self._case_extractor: AgentCaseExtractor | None = None
        self._audit: AuditLogger | None = None

    @property
    def event_extractor(self) -> EventExtractor:
        if self._event_extractor is None:
            self._event_extractor = EventExtractor(model=self._model)
        return self._event_extractor

    @property
    def pre_filter(self) -> VectorPreFilter:
        if self._pre_filter is None:
            self._pre_filter = VectorPreFilter(neo4j_client=self._neo4j, milvus_store=self._milvus)
        return self._pre_filter

    @property
    def profile_updater(self) -> ProfileUpdater:
        if self._profile_updater is None:
            self._profile_updater = ProfileUpdater(model=self._model, neo4j_client=self._neo4j)
        return self._profile_updater

    @property
    def session_summarizer(self) -> SessionSummarizer:
        if self._session_summarizer is None:
            self._session_summarizer = SessionSummarizer(model=self._model, milvus_store=self._milvus)
        return self._session_summarizer

    @property
    def case_extractor(self) -> AgentCaseExtractor:
        if self._case_extractor is None:
            self._case_extractor = AgentCaseExtractor(model=self._model)
        return self._case_extractor

    @property
    def audit(self) -> AuditLogger:
        if self._audit is None:
            self._audit = AuditLogger()
        return self._audit

    async def extract_memories(
        self, user_id: str, session_id: str,
        user_message: str, assistant_response: str,
        tool_calls: str = "", round_index: int = 1,
        recommendations: str = "", user_feedback: str = "",
    ) -> dict:
        """Run the full extraction pipeline for one conversation turn."""
        result = {"events": [], "deltas": [], "session_summary": None, "agent_case": None, "audit_entries": []}

        # 1. Extract events
        try:
            events = self.event_extractor.extract(
                user_message=user_message, assistant_response=assistant_response,
                tool_calls=tool_calls, user_id=user_id, session_id=session_id,
            )
            result["events"] = events
        except Exception:
            logger.exception("Event extraction failed")

        # 2. Embed and store events
        for event in result["events"]:
            try:
                if event.description:
                    event.embedding = embed_texts([event.description])[0]
                    self._milvus.insert_event(event)
            except Exception:
                logger.exception("Failed to embed/store event %s", event.id)

        # 3. Vector Pre-Filter
        try:
            relevant_profiles = self.pre_filter.filter(user_id, result["events"])
        except Exception:
            logger.exception("Pre-filter failed")
            relevant_profiles = []

        # 4. Profile Update
        try:
            deltas = self.profile_updater.compute_delta(
                user_id=user_id, user_message=user_message,
                assistant_response=assistant_response, events=result["events"],
                existing_profiles=relevant_profiles,
            )
            if deltas:
                audit_entries = self.profile_updater.apply_delta(user_id, deltas)
                result["deltas"] = deltas
                result["audit_entries"] = audit_entries
                if audit_entries:
                    self.audit.log(user_id=user_id, session_id=session_id,
                                   trigger_message=user_message, round_index=round_index,
                                   operations=audit_entries)
        except Exception:
            logger.exception("Profile update failed")

        # 5. Session Summary
        try:
            round_text = f"用户: {user_message}\n助手: {assistant_response}"
            summary = self.session_summarizer.summarize_round(
                round_content=round_text, user_id=user_id, session_id=session_id,
            )
            if summary and self.session_summarizer.should_write_incremental(round_index):
                summary.embedding = embed_texts([summary.summary])[0]
                self._milvus.insert_session(summary)
                result["session_summary"] = summary
        except Exception:
            logger.exception("Session summarization failed")

        # 6. Agent Case Extraction
        if self.case_extractor.should_extract(user_feedback):
            try:
                case = self.case_extractor.extract(
                    user_id=user_id, user_query=user_message,
                    recommendations=recommendations, user_feedback=user_feedback,
                )
                if case:
                    case.embedding = embed_texts([case.description])[0]
                    self._milvus.insert_agent_case(case)
                    result["agent_case"] = case
            except Exception:
                logger.exception("Agent case extraction failed")

        return result

    async def finalize_session(self, user_id: str, session_id: str) -> None:
        """Called when a session ends. Writes final merged summary."""
        try:
            final_summary = self.session_summarizer.merge_final_summary(session_id, user_id)
            if final_summary:
                final_summary.embedding = embed_texts([final_summary.summary])[0]
                self._milvus.insert_session(final_summary)
        except Exception:
            logger.exception("Session finalization failed for %s", session_id)
