"""Agent Case Extractor: captures agent experience patterns from outcomes.

After each recommendation interaction, extracts what worked/failed as a
reusable AgentCase for future similar scenarios.

These cases are stored in Milvus collection ``agent_case`` with 180-day TTL.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.messages import HumanMessage

from src.memory.prompts import AGENT_CASE_EXTRACTION_PROMPT
from src.storage.models import AgentCase

logger = logging.getLogger("pick.memory.agent_case_extractor")


class AgentCaseExtractor:
    """Extracts agent experience cases from recommendation outcomes.

    Uses an LLM to analyse the interaction (user query, recommendations given,
    and the user's feedback) and produces a structured AgentCase that records
    what was tried, what happened, and what lesson the agent can learn.

    The resulting cases are later embedded, stored in Milvus, and retrieved
    via vector similarity in future sessions so the agent can recall what
    worked in similar contexts.
    """

    def __init__(self, model: Any = None) -> None:
        """Initialise with a LangChain-compatible chat model.

        If *model* is ``None``, one is created via ``src.agent.config.get_model()``
        (which reads ``LLM_MODEL`` / ``LLM_API_KEY`` / ``LLM_BASE_URL`` from the
        environment).
        """
        if model is None:
            from src.agent.config import get_model

            model = get_model()
        self._model = model

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extract(
        self,
        user_id: str,
        user_query: str,
        recommendations: str,
        user_feedback: str,
    ) -> AgentCase | None:
        """Extract an agent case from a recommendation interaction.

        Parameters
        ----------
        user_id:
            The end-user identifier the case is associated with.
        user_query:
            The user's original query (e.g. "春熙路火锅").
        recommendations:
            What the agent recommended (shop names, voucher names, etc.).
        user_feedback:
            Observed or explicit feedback describing what the user actually did
            (clicked, purchased, ignored, rejected, etc.).

        Returns
        -------
        An ``AgentCase`` if the LLM produced a valid extraction, or ``None``
        when feedback is empty or the LLM returns an empty / invalid response.
        """
        if not user_feedback.strip():
            return None

        prompt = AGENT_CASE_EXTRACTION_PROMPT.format(
            user_query=user_query,
            recommendations=recommendations,
            user_feedback=user_feedback,
        )

        try:
            response = self._model.invoke([HumanMessage(content=prompt)])
            data = json.loads(response.content.strip())
        except Exception:
            logger.exception("Agent case extraction failed")
            return None

        if not data or not data.get("case_type"):
            return None

        return AgentCase(
            user_id=user_id,
            case_type=data.get("case_type", "recommendation"),
            description=data.get("description", ""),
            context=data.get("context", {}),
            action=data.get("action", ""),
            outcome=data.get("outcome", "unknown"),
            outcome_reason=data.get("outcome_reason", ""),
            lesson=data.get("lesson", ""),
        )

    def should_extract(self, user_feedback: str) -> bool:
        """Determine whether extraction is warranted based on feedback content.

        Returns ``True`` when the feedback contains strong-signal keywords
        that indicate a meaningful outcome (positive or negative), so that
        callers can avoid making an LLM call for trivial or ambiguous feedback.
        """
        if not user_feedback.strip():
            return False

        strong_signals = [
            "不喜欢",
            "太贵",
            "太远",
            "不错",
            "喜欢",
            "就这家",
            "下单",
            "买",
            "不要",
            "不行",
            "not interested",
            "too expensive",
            "like",
        ]
        feedback_lower = user_feedback.lower()
        return any(signal in feedback_lower for signal in strong_signals)
