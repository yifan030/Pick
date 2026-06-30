from __future__ import annotations

"""End-to-end tests for the complete memory system.

Tests the full cycle: extract, store, retrieve, inject.
Uses mocked LLM calls and storage interfaces (Neo4j, Milvus).
"""
import pytest
from unittest.mock import AsyncMock
from src.retrieval.prompt_builder import PromptBuilder
from src.storage.models import (
    TastePreference,
    CuisinePreference,
    DietaryPreference,
)

pytestmark = pytest.mark.integration


class TestPromptBuilderE2E:
    """End-to-end prompt building tests (real PromptBuilder, mocked storage)."""

    def test_full_prompt_building_with_all_sections(self):
        """PromptBuilder should produce complete memory context."""
        builder = PromptBuilder()

        context = builder.build(
            profiles=[
                TastePreference(
                    user_id="u1", property="spicy", value="avoid",
                    confidence=0.9,
                ),
                CuisinePreference(
                    user_id="u1", cuisine="川渝火锅",
                    confidence=0.85, weight=0.9,
                ),
            ],
            hard_constraints=[
                DietaryPreference(
                    user_id="u1", constraint="清真", type="religious",
                ),
            ],
            memories=[
                {
                    "id": "evt_1",
                    "final_score": 0.85,
                    "description": "在春熙路搜索川渝火锅",
                },
            ],
        )

        assert "避免" in context or "spicy" in context
        assert "川渝火锅" in context
        assert "清真" in context
        assert "## 用户记忆" in context
        assert "### 偏好" in context
        assert "### 🔒 硬约束" in context
        assert "### 近期行为" in context

    def test_prompt_builder_empty_graceful(self):
        """Empty memory should produce a graceful placeholder."""
        builder = PromptBuilder()
        context = builder.build([], [], [])
        assert len(context) > 0
        assert "暂无" in context or "记忆" in context

    def test_prompt_builder_profiles_only(self):
        """Only profiles, no constraints or memories."""
        builder = PromptBuilder()
        context = builder.build(
            profiles=[
                TastePreference(
                    user_id="u1", property="salty", value="like",
                    confidence=0.8,
                ),
            ],
            hard_constraints=[],
            memories=[],
        )
        assert "### 偏好" in context
        assert "salty" in context
        assert "硬约束" not in context

    def test_prompt_builder_hard_constraints_only(self):
        """Only hard constraints."""
        builder = PromptBuilder()
        context = builder.build(
            profiles=[],
            hard_constraints=[
                DietaryPreference(
                    user_id="u1", constraint="素食", type="lifestyle",
                ),
            ],
            memories=[],
        )
        assert "硬约束" in context
        assert "素食" in context
        assert "### 偏好" not in context

    def test_prompt_builder_memories_only(self):
        """Only recent memories."""
        builder = PromptBuilder()
        context = builder.build(
            profiles=[],
            hard_constraints=[],
            memories=[
                {
                    "id": "evt_1",
                    "final_score": 0.9,
                    "description": "浏览了多家火锅店",
                },
                {
                    "id": "evt_2",
                    "final_score": 0.7,
                    "description": "搜索日料",
                },
            ],
        )
        assert "### 近期行为" in context
        assert "火锅" in context
        assert "日料" in context


class TestRetrievalImportChain:
    """Verify the retrieval module import chain is intact."""

    def test_all_public_api_importable(self):
        """All public API classes should be importable from their modules."""
        from src.retrieval.semantic_search import SemanticSearch
        from src.retrieval.bm25_search import BM25Search
        from src.retrieval.entity_boost import EntityBoost
        from src.retrieval.fusion import ScoreNormalizer, RankFusion
        from src.retrieval.gateway import RetrievalGateway
        from src.retrieval.prompt_builder import PromptBuilder
        from src.retrieval.feedback import FeedbackProcessor
        from src.retrieval.consistency import ConsistencyChecker

        # All imports succeeded
        assert SemanticSearch is not None
        assert BM25Search is not None
        assert EntityBoost is not None
        assert ScoreNormalizer is not None
        assert RankFusion is not None
        assert RetrievalGateway is not None
        assert PromptBuilder is not None
        assert FeedbackProcessor is not None
        assert ConsistencyChecker is not None

    def test_retrieval_package_exports(self):
        """Verify retrieval __init__.py exports the expected classes."""
        from src.retrieval import (
            RetrievalGateway,
            ScoreNormalizer,
            RankFusion,
            PromptBuilder,
            FeedbackProcessor,
            ConsistencyChecker,
            SemanticSearch,
            BM25Search,
            EntityBoost,
        )
        assert RetrievalGateway is not None
        assert SemanticSearch is not None
        assert BM25Search is not None
        assert EntityBoost is not None


class TestEntityBoostE2E:
    """Entity extraction and boost computation tests."""

    def test_extract_entities_from_query(self):
        """EntityBoost should extract known entities from query text."""
        from src.retrieval.entity_boost import EntityBoost
        # EntityBoost needs a neo4j_client, but extract_entities doesn't use it
        mock_neo4j = AsyncMock()
        boost = EntityBoost(mock_neo4j)

        entities = boost.extract_entities("我想在春熙路吃火锅")
        assert "春熙路" in entities["areas"]
        assert "火锅" in entities["cuisines"]

    def test_extract_no_entities(self):
        """Query with no known entities should return empty lists."""
        from src.retrieval.entity_boost import EntityBoost
        mock_neo4j = AsyncMock()
        boost = EntityBoost(mock_neo4j)

        entities = boost.extract_entities("帮我推荐一下")
        assert entities["areas"] == []
        assert entities["cuisines"] == []

    def test_compute_boost_direct_match(self):
        """Direct entity match should get DIRECT_ENTITY_BOOST."""
        from src.retrieval.entity_boost import EntityBoost

        entity_data = {
            "boost_results": [
                {
                    "event_id": "evt_123",
                    "boost_score": 0.30,
                    "matched_entity": "火锅",
                },
            ],
        }
        score = EntityBoost.compute_boost(entity_data, "evt_123")
        assert score == 0.30  # DIRECT_ENTITY_BOOST

    def test_compute_boost_no_match_with_profiles(self):
        """No direct match but profiles exist to indirect boost."""
        from src.retrieval.entity_boost import EntityBoost

        entity_data = {
            "boost_results": [
                {"event_id": "evt_999", "boost_score": 0.30},
            ],
            "profiles": [{"type": "cuisine"}],
        }
        score = EntityBoost.compute_boost(entity_data, "evt_123")
        assert score == 0.15  # PROFILE_INDIRECT_BOOST

    def test_compute_boost_no_data(self):
        """No boost results or profiles to 0.0."""
        from src.retrieval.entity_boost import EntityBoost

        score = EntityBoost.compute_boost({}, "evt_123")
        assert score == 0.0
