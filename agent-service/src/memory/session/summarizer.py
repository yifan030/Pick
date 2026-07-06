# src/memory/session_summarizer.py
"""Session Summarizer: incremental session summaries every 3 turns.

Summaries are stored in Milvus collection ``user_session``.
- is_complete=false: ongoing session, updated every 3 turns
- is_complete=true: final summary, written when session ends

Retention:
- 0-30 days: full (with embedding)
- 30-90 days: text only (embedding removed by cleanup job)
- >90 days: hard delete (by cleanup job)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from src.memory.prompts import SESSION_FINAL_MERGE_PROMPT, SESSION_SUMMARY_PROMPT
from src.storage.models import SessionSummary

logger = logging.getLogger("pick.memory.session_summarizer")

INCREMENTAL_INTERVAL = 3  # Write incremental summary every N rounds


class SessionSummarizer:
    """Manages incremental and final session summaries."""

    def __init__(self, model: Any = None, milvus_store=None):
        if model is None:
            from src.agent.config import get_extractor_model

            model = get_extractor_model()
        self._model = model
        self._milvus = milvus_store
        # In-memory cache: session_id -> list of round_summary strings
        self._round_cache: dict[str, list[str]] = {}

    def summarize_round(
        self,
        round_content: str,
        user_id: str,
        session_id: str = "",
    ) -> SessionSummary | None:
        """Generate a single-round summary."""
        prompt = SESSION_SUMMARY_PROMPT.format(round_content=round_content)
        try:
            response = self._model.invoke([HumanMessage(content=prompt)])
            data = json.loads(response.content.strip())
        except Exception:
            logger.exception("Session summarization failed")
            return None

        summary = SessionSummary(
            user_id=user_id,
            summary=data.get("summary", round_content[:200]),
            key_shops=data.get("key_shops", []),
            key_areas=data.get("key_areas", []),
            intent=data.get("intent", ""),
            is_complete=False,
        )
        # Cache the round summary text
        if session_id:
            self._round_cache.setdefault(session_id, []).append(summary.summary)

        return summary

    def should_write_incremental(self, round_index: int) -> bool:
        """Check if an incremental write is due (every 3 rounds)."""
        return round_index > 0 and round_index % INCREMENTAL_INTERVAL == 0

    def get_cached_rounds(self, session_id: str) -> list[str]:
        """Get cached round summary texts for a session."""
        return self._round_cache.get(session_id, [])

    def merge_final_summary(
        self, session_id: str, user_id: str
    ) -> SessionSummary | None:
        """Merge all cached round summaries into one final summary."""
        rounds = self._round_cache.get(session_id, [])
        if not rounds:
            return None

        if len(rounds) == 1:
            merged_text = rounds[0]
        else:
            prompt = SESSION_FINAL_MERGE_PROMPT.format(
                round_summaries="\n---\n".join(rounds)
            )
            try:
                response = self._model.invoke([HumanMessage(content=prompt)])
                data = json.loads(response.content.strip())
                merged_text = data.get("summary", rounds[-1])
            except Exception:
                logger.exception("Final merge failed, using last round summary")
                merged_text = rounds[-1]

        # Clean up cache
        self._round_cache.pop(session_id, None)

        return SessionSummary(
            user_id=user_id,
            summary=merged_text,
            key_shops=[],
            key_areas=[],
            intent="",
            is_complete=True,
        )
