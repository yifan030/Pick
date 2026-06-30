"""Tests for EventExtractor."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.memory.extractor import EventExtractor
from src.storage.models import MemoryEvent


@pytest.fixture
def mock_llm():
    """Mock LangChain chat model that returns a controlled JSON response."""
    model = MagicMock()
    response = MagicMock()
    response.content = (
        '{"event_type":"search","description":"用户在春熙路搜索火锅",'
        '"payload":{"query":"火锅","area":"春熙路"},"ttl_seconds":null}\n'
        '{"event_type":"constraint","description":"用户表示不吃辣",'
        '"payload":{"constraint":"不吃辣"},"ttl_seconds":null}'
    )
    model.invoke = MagicMock(return_value=response)
    return model


@pytest.fixture
def extractor(mock_llm):
    return EventExtractor(model=mock_llm)


def test_extract_events_parses_multiline_json(extractor):
    """EventExtractor should parse multiple JSON lines into MemoryEvents."""
    events = extractor.extract(
        user_message="我想在春熙路找火锅，不吃辣",
        assistant_response="为您推荐以下火锅店...",
        tool_calls="search_shops(query=火锅, area=春熙路)",
    )
    assert len(events) == 2
    assert events[0].event_type == "search"
    assert events[0].description == "用户在春熙路搜索火锅"
    assert events[1].event_type == "constraint"
    assert events[1].payload["constraint"] == "不吃辣"


def test_extract_events_empty_response(extractor):
    """When LLM returns empty, extractor should return empty list."""
    extractor._model.invoke.return_value.content = ""
    events = extractor.extract("你好", "你好！有什么可以帮您的？", "")
    assert events == []


def test_extract_events_handles_malformed_json(extractor):
    """Malformed JSON lines should be skipped gracefully."""
    extractor._model.invoke.return_value.content = (
        "not json\n"
        '{"event_type":"search","description":"valid event","payload":{}}\n'
        "also not json"
    )
    events = extractor.extract("test", "response", "")
    assert len(events) == 1
    assert events[0].event_type == "search"


def test_event_has_correct_defaults(extractor):
    """Extracted events should have correct default fields."""
    extractor._model.invoke.return_value.content = (
        '{"event_type":"search","description":"测试搜索","payload":{"q":"test"},"ttl_seconds":null}'
    )
    events = extractor.extract("test", "response", "", user_id="u1", session_id="s1")
    assert len(events) == 1
    e = events[0]
    assert e.user_id == "u1"
    assert e.session_id == "s1"
    assert e.compressed is False
    assert e.compressed_from == []
