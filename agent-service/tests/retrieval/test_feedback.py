from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.retrieval.feedback import FeedbackProcessor


@pytest.fixture
def mock_neo4j():
    neo4j = AsyncMock()
    neo4j.update_profile = AsyncMock()
    neo4j.read_profiles = AsyncMock(return_value=[])
    neo4j.delete_profile = AsyncMock()
    return neo4j


@pytest.fixture
def processor(mock_neo4j):
    return FeedbackProcessor(neo4j_client=mock_neo4j)


def test_process_shop_card_click(processor):
    """Click on a recommended shop should REINFORCE related profiles."""
    result = processor.process_signal(
        user_id="u1",
        signal_type="shop_card_click",
        payload={"shop_id": "shop_1", "shop_category": "川渝火锅", "shop_area": "春克路"},
        related_profiles=["profile_cuisine_1", "profile_area_1"],
    )
    assert result["action"] == "reinforce"
    assert result["profiles_affected"] == 2


def test_process_purchase_success(processor):
    """Purchase should give a larger REINFORCE boost."""
    result = processor.process_signal(
        user_id="u1",
        signal_type="chat_purchase_success",
        payload={"shop_id": "shop_1", "amount": 80},
        related_profiles=["profile_budget_1"],
    )
    assert result["action"] == "reinforce_strong"
    assert result["confidence_delta"] == 0.15


def test_process_explicit_rejection(processor):
    """User rejection should lower confidence."""
    result = processor.process_signal(
        user_id="u1",
        signal_type="explicit_rejection",
        payload={"reason": "太贵了", "shop_id": "shop_1"},
        related_profiles=["profile_budget_1"],
    )
    assert result["action"] == "weaken"


def test_process_user_correction(processor, mock_neo4j):
    """User correction should trigger DELETE."""
    result = processor.process_signal(
        user_id="u1",
        signal_type="user_correction",
        payload={"correction": "我说错了，其实是春克路不是太古里"},
        related_profiles=["profile_area_old"],
    )
    assert result["action"] == "delete"
