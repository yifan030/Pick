# src/memory/extractor.py
"""Event Extractor: converts conversation turns to structured MemoryEvents.

Uses a small/cheap LLM to extract behavioral events from user messages,
assistant responses, and tool call results. Events are typed (search,
purchase, view, feedback, constraint, dietary) with structured payloads.

This runs asynchronously after each SSE stream completes — it does NOT
block the user-facing response.
"""

import json
import logging
from typing import Any
from src.storage.models import MemoryEvent
from src.memory.prompts import EVENT_EXTRACTION_PROMPT

logger = logging.getLogger("pick.memory.extractor")


class EventExtractor:
    """Extracts structured behavioral events from conversation turns."""

    def __init__(self, model: Any = None):
        """Args:
            model: A LangChain BaseChatModel instance. If None, uses config.get_model().
        """
        if model is None:
            from src.agent.config import get_model
            model = get_model()
        self._model = model

    def extract(
        self,
        user_message: str,
        assistant_response: str,
        tool_calls: str = "",
        user_id: str = "",
        session_id: str = "",
    ) -> list[MemoryEvent]:
        """Extract events from a single conversation turn.

        Args:
            user_message: The user's query text.
            assistant_response: The agent's response text.
            tool_calls: String representation of tool invocations.
            user_id: The user's ID (for attribution).
            session_id: The current session ID.

        Returns:
            List of MemoryEvent objects (may be empty).
        """
        prompt = EVENT_EXTRACTION_PROMPT.format(
            user_message=user_message,
            assistant_response=assistant_response,
            tool_calls=tool_calls or "(无)",
        )

        try:
            from langchain_core.messages import HumanMessage
            response = self._model.invoke([HumanMessage(content=prompt)])
            raw = response.content.strip()
        except Exception:
            logger.exception("Event extraction LLM call failed")
            return []

        return self._parse_response(raw, user_id, session_id)

    def _parse_response(
        self, raw: str, user_id: str, session_id: str
    ) -> list[MemoryEvent]:
        """Parse the LLM response (one JSON object per line) into MemoryEvents."""
        events = []
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping malformed event JSON: %.100s", line)
                continue

            try:
                event = MemoryEvent(
                    user_id=user_id,
                    event_type=data.get("event_type", "unknown"),
                    description=data.get("description", ""),
                    payload=data.get("payload", {}),
                    session_id=session_id,
                    ttl_seconds=data.get("ttl_seconds"),
                )
                events.append(event)
            except Exception:
                logger.exception("Failed to create MemoryEvent from %s", data)

        return events
