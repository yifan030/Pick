# tests/retrieval/test_feedback_consumer.py
"""Tests for FeedbackConsumer — Kafka behaviour feedback → Neo4j Profile update."""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from src.retrieval.feedback_consumer import FeedbackConsumer, MAX_CONFIDENCE, MIN_CONFIDENCE

# ── Test helpers ──────────────────────────────────────────────────────────


def _make_profile(pid: str = "p1", confidence: float = 0.6, reinforce_count: int = 2):
    """Return a lightweight mock profile with .id, .confidence, .reinforce_count."""
    profile = MagicMock()
    profile.id = pid
    profile.confidence = confidence
    profile.reinforce_count = reinforce_count
    return profile


def _raw_message(overrides: dict | None = None) -> dict:
    """Build a realistic raw Kafka message dict."""
    base = {
        "event_id": "evt_behav_001",
        "user_id": "u123",
        "event_type": "shop_card_click",
        "trace_id": "trace_rec_abc",
        "shop_id": "shop_456",
        "timestamp": 1719696000,
        "context": {"session_id": "sess_xyz"},
    }
    if overrides:
        base.update(overrides)
    return base


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.get_profiles_by_trace = AsyncMock()
    neo4j.update_profile = AsyncMock()
    neo4j.delete_profile = AsyncMock()
    return neo4j


@pytest.fixture
def consumer(mock_neo4j):
    return FeedbackConsumer(neo4j_client=mock_neo4j)


# ── parse_message ─────────────────────────────────────────────────────────


class TestParseMessage:
    def test_extracts_all_fields(self, consumer):
        raw = _raw_message()
        parsed = consumer.parse_message(raw)
        assert parsed["user_id"] == "u123"
        assert parsed["event_type"] == "shop_card_click"
        assert parsed["trace_id"] == "trace_rec_abc"
        assert parsed["shop_id"] == "shop_456"
        assert parsed["session_id"] == "sess_xyz"
        assert parsed["timestamp"] == 1719696000

    def test_missing_context_defaults_session_id(self, consumer):
        raw = _raw_message()
        del raw["context"]
        parsed = consumer.parse_message(raw)
        assert parsed["session_id"] == ""

    def test_none_context_defaults_session_id(self, consumer):
        raw = _raw_message()
        raw["context"] = None
        parsed = consumer.parse_message(raw)
        assert parsed["session_id"] == ""


# ── get_reinforce_delta ───────────────────────────────────────────────────


class TestGetReinforceDelta:
    def test_shop_card_click(self, consumer):
        assert consumer.get_reinforce_delta("shop_card_click") == 0.1

    def test_purchase_success(self, consumer):
        assert consumer.get_reinforce_delta("purchase_success") == 0.15

    def test_explicit_rejection(self, consumer):
        assert consumer.get_reinforce_delta("explicit_rejection") == -0.1

    def test_unknown_event_type(self, consumer):
        assert consumer.get_reinforce_delta("unknown_type") == 0.0

    def test_empty_string(self, consumer):
        assert consumer.get_reinforce_delta("") == 0.0


# ── process_event ─────────────────────────────────────────────────────────


class TestProcessEvent:
    @pytest.mark.asyncio
    async def test_confidence_boost_on_click(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p1", confidence=0.5, reinforce_count=1)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "shop_card_click"}))
        await consumer.process_event(event)

        mock_neo4j.update_profile.assert_called_once_with("p1", {
            "confidence": 0.6,
            "reinforce_count": 2,
            "last_reinforced_at": 1719696000,
        })
        mock_neo4j.delete_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_confidence_boost_on_purchase(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p2", confidence=0.7, reinforce_count=3)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "purchase_success"}))
        await consumer.process_event(event)

        mock_neo4j.update_profile.assert_called_once_with("p2", {
            "confidence": 0.85,
            "reinforce_count": 4,
            "last_reinforced_at": 1719696000,
        })
        mock_neo4j.delete_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_confidence_decrease_on_rejection(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p3", confidence=0.5, reinforce_count=2)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "explicit_rejection"}))
        await consumer.process_event(event)

        assert mock_neo4j.update_profile.call_count == 1
        call_args = mock_neo4j.update_profile.call_args
        assert call_args[0][0] == "p3"
        assert call_args[0][1]["confidence"] == 0.4
        assert call_args[0][1]["reinforce_count"] == 3

    @pytest.mark.asyncio
    async def test_deletion_when_confidence_drops_below_threshold(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p4", confidence=0.35, reinforce_count=0)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "explicit_rejection"}))
        await consumer.process_event(event)

        # 0.35 - 0.1 = 0.25 → below MIN_CONFIDENCE (0.3) → delete
        mock_neo4j.delete_profile.assert_called_once_with("p4")
        mock_neo4j.update_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_deletion_does_not_fire_above_threshold(self, consumer, mock_neo4j):
        """Profile at 0.40 - 0.1 = 0.30 is NOT below 0.3, so update not delete."""
        profile = _make_profile(pid="p5", confidence=0.40, reinforce_count=0)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "explicit_rejection"}))
        await consumer.process_event(event)

        mock_neo4j.update_profile.assert_called_once()
        mock_neo4j.delete_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_clamps_at_max_confidence(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p6", confidence=0.90, reinforce_count=5)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "purchase_success"}))
        await consumer.process_event(event)

        call_args = mock_neo4j.update_profile.call_args
        assert call_args[0][1]["confidence"] == MAX_CONFIDENCE  # 0.95

    @pytest.mark.asyncio
    async def test_clamps_at_zero(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p7", confidence=0.05, reinforce_count=0)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "explicit_rejection"}))
        await consumer.process_event(event)

        # 0.05 - 0.1 = -0.05 → clamped to 0.0, which is < 0.3 → delete
        mock_neo4j.delete_profile.assert_called_once_with("p7")

    @pytest.mark.asyncio
    async def test_skipped_when_trace_id_is_none(self, consumer, mock_neo4j):
        event = consumer.parse_message(_raw_message({"trace_id": None}))
        await consumer.process_event(event)
        mock_neo4j.get_profiles_by_trace.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_profiles_found(self, consumer, mock_neo4j):
        mock_neo4j.get_profiles_by_trace.return_value = []
        event = consumer.parse_message(_raw_message())
        await consumer.process_event(event)
        mock_neo4j.update_profile.assert_not_called()
        mock_neo4j.delete_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiple_profiles_updated(self, consumer, mock_neo4j):
        p1 = _make_profile(pid="p1", confidence=0.5, reinforce_count=1)
        p2 = _make_profile(pid="p2", confidence=0.8, reinforce_count=2)
        mock_neo4j.get_profiles_by_trace.return_value = [p1, p2]

        event = consumer.parse_message(_raw_message({"event_type": "shop_card_click"}))
        await consumer.process_event(event)

        assert mock_neo4j.update_profile.call_count == 2
        mock_neo4j.update_profile.assert_has_calls([
            call("p1", {"confidence": 0.6, "reinforce_count": 2, "last_reinforced_at": 1719696000}),
            call("p2", {"confidence": 0.9, "reinforce_count": 3, "last_reinforced_at": 1719696000}),
        ])

    @pytest.mark.asyncio
    async def test_default_event_type_zero_delta_no_change(self, consumer, mock_neo4j):
        profile = _make_profile(pid="p8", confidence=0.6, reinforce_count=0)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        event = consumer.parse_message(_raw_message({"event_type": "unknown"}))
        await consumer.process_event(event)

        mock_neo4j.update_profile.assert_called_once_with("p8", {
            "confidence": 0.6,  # unchanged
            "reinforce_count": 1,
            "last_reinforced_at": 1719696000,
        })

    @pytest.mark.asyncio
    async def test_get_profiles_error_is_suppressed(self, consumer, mock_neo4j):
        mock_neo4j.get_profiles_by_trace.side_effect = RuntimeError("Neo4j down")
        event = consumer.parse_message(_raw_message())
        # Should not raise
        await consumer.process_event(event)
        mock_neo4j.update_profile.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_audit_jsonl(self, consumer, mock_neo4j, tmp_path):
        """Verify that an audit entry is appended to the correct path."""
        profile = _make_profile(pid="p1", confidence=0.5, reinforce_count=1)
        mock_neo4j.get_profiles_by_trace.return_value = [profile]

        # Patch the audit base to use a temp dir
        import src.retrieval.feedback_consumer as fcm
        with patch.object(fcm, "_AUDIT_BASE", str(tmp_path)):
            event = consumer.parse_message(_raw_message({"event_type": "shop_card_click"}))
            await consumer.process_event(event)

        # The entry should be at tmp_path/u123/YYYY-MM.jsonl
        user_dir = tmp_path / "u123"
        assert user_dir.is_dir()
        jsonl_files = list(user_dir.glob("*.jsonl"))
        assert len(jsonl_files) == 1, f"Expected 1 JSONL file, found {jsonl_files}"

        content = jsonl_files[0].read_text(encoding="utf-8")
        lines = [l for l in content.strip().split("\n") if l]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["agent_role"] == "feedback_loop"
        assert entry["user_id"] == "u123"
        assert entry["profiles_affected"] == 1
        assert entry["confidence_delta"] == 0.1
        assert entry["event_type"] == "shop_card_click"
