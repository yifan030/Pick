"""Tests for SessionSummarizer."""
import pytest
from unittest.mock import MagicMock
from src.memory.session_summarizer import SessionSummarizer
from src.storage.models import SessionSummary


@pytest.fixture
def mock_llm():
    model = MagicMock()
    response = MagicMock()
    response.content = (
        '{"summary":"用户在春熙路搜索火锅，预算人均100，查看了蜀大侠",'
        '"key_shops":["shop_1"],"key_areas":["春熙路"],"intent":"recommend_shop"}'
    )
    model.invoke = MagicMock(return_value=response)
    return model


@pytest.fixture
def summarizer(mock_llm):
    return SessionSummarizer(model=mock_llm)


def test_summarize_round(summarizer):
    """summarize_round should parse LLM response into a SessionSummary."""
    summary = summarizer.summarize_round(
        "用户：春熙路火锅\n助手：推荐蜀大侠...",
        user_id="u1",
    )
    assert summary is not None
    assert "春熙路" in summary.summary
    assert "shop_1" in summary.key_shops
    assert summary.intent == "recommend_shop"
    assert summary.is_complete is False


def test_should_write_incremental(summarizer):
    """should_write_incremental returns True every 3 rounds starting from round 3."""
    assert summarizer.should_write_incremental(3) is True   # round 3 -> write
    assert summarizer.should_write_incremental(4) is False  # round 4 -> skip
    assert summarizer.should_write_incremental(6) is True   # round 6 -> write
    assert summarizer.should_write_incremental(0) is False  # round 0 is invalid
