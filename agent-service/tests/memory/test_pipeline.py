# tests/memory/test_pipeline.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.memory.pipeline import MemoryPipeline


@pytest.fixture
def mock_deps():
    return {
        "neo4j": AsyncMock(),
        "milvus": MagicMock(),
        "embed": MagicMock(return_value=[[0.1] * 1024]),
        "audit": MagicMock(),
    }


@pytest.fixture
def pipeline(mock_deps):
    with patch("src.memory.pipeline.EventExtractor") as mock_extractor, \
         patch("src.memory.pipeline.VectorPreFilter") as mock_prefilter, \
         patch("src.memory.pipeline.ProfileUpdater") as mock_updater, \
         patch("src.memory.pipeline.SessionSummarizer") as mock_summarizer, \
         patch("src.memory.pipeline.AgentCaseExtractor") as mock_case_ext, \
         patch("src.memory.pipeline.AuditLogger") as mock_audit:
        mock_extractor.return_value.extract.return_value = []
        mock_prefilter.return_value.filter.return_value = []
        mock_updater.return_value.compute_delta.return_value = []
        mock_updater.return_value.apply_delta.return_value = []
        p = MemoryPipeline(
            neo4j_client=mock_deps["neo4j"],
            milvus_store=mock_deps["milvus"],
            model=MagicMock(),
        )
        return p


@pytest.mark.asyncio
async def test_extract_memories_noop(pipeline):
    """Pipeline should handle empty extraction gracefully."""
    result = await pipeline.extract_memories(
        user_id="u1", session_id="sess_1",
        user_message="你好", assistant_response="你好！",
        tool_calls="", round_index=1,
    )
    assert result is not None
    assert "events" in result
    assert "deltas" in result


def test_pipeline_creates_all_extractors(pipeline):
    """All extractors should be instantiated."""
    # Access properties to trigger lazy creation
    _ = pipeline.event_extractor
    _ = pipeline.pre_filter
    _ = pipeline.profile_updater
    _ = pipeline.session_summarizer
    _ = pipeline.case_extractor
    _ = pipeline.audit
    assert pipeline._event_extractor is not None
    assert pipeline._pre_filter is not None
    assert pipeline._profile_updater is not None
    assert pipeline._session_summarizer is not None
    assert pipeline._case_extractor is not None
    assert pipeline._audit is not None
