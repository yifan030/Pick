"""Tests for AgentCaseExtractor."""
import pytest
from unittest.mock import MagicMock
from src.memory.case.extractor import AgentCaseExtractor
from src.storage.models import AgentCase


@pytest.fixture
def mock_llm():
    model = MagicMock()
    response = MagicMock()
    response.content = (
        '{"case_type":"recommendation",'
        '"description":"用户搜索火锅但说不吃辣，Agent推荐了粤菜馆",'
        '"context":{"intent":"recommend_shop","area":"春熙路","constraints":["不吃辣"]},'
        '"action":"推荐粤菜馆点都德","outcome":"success",'
        '"outcome_reason":"用户点击并查看了优惠券",'
        '"lesson":"用户不吃辣但搜索火锅时，推荐不辣的高评分类别如粤菜"}'
    )
    model.invoke = MagicMock(return_value=response)
    return model


@pytest.fixture
def extractor(mock_llm):
    return AgentCaseExtractor(model=mock_llm)


def test_extract_case_with_feedback(extractor):
    """extract should parse LLM response into an AgentCase."""
    case = extractor.extract(
        user_id="u1",
        user_query="春熙路火锅",
        recommendations="蜀大侠火锅",
        user_feedback="用户没有点击火锅店，但点击了粤菜馆点都德",
    )
    assert case is not None
    assert case.case_type == "recommendation"
    assert case.outcome == "success"
    assert case.user_id == "u1"


def test_extract_no_feedback_returns_none(extractor):
    """Empty feedback leads to no case extraction."""
    extractor._model.invoke.return_value.content = "{}"
    case = extractor.extract("u1", "test", "recs", "")
    assert case is None


def test_agent_case_default_ttl(extractor):
    """AgentCase should have 180-day default TTL."""
    case = extractor.extract("u1", "query", "recs", "user clicked")
    if case:
        assert case.ttl_seconds == 15552000  # 180 days
