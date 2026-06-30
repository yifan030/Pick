from __future__ import annotations

"""Tests for ScoreNormalizer and RankFusion."""
import pytest
from src.retrieval.fusion import ScoreNormalizer, RankFusion

# ── ScoreNormalizer tests ─────────────────────────────────────────────


def test_normalize_single_result():
    """Single result should normalize to 1.0."""
    normalizer = ScoreNormalizer()
    results = [{"id": "e1", "score": 0.85}]
    normalized = normalizer.normalize_semantic(results)
    assert normalized[0]["normalized_score"] == 1.0


def test_normalize_multiple_results():
    """Multiple results should normalize to [0, 1] range."""
    normalizer = ScoreNormalizer()
    results = [
        {"id": "e1", "score": 0.9},
        {"id": "e2", "score": 0.5},
        {"id": "e3", "score": 0.1},
    ]
    normalized = normalizer.normalize_semantic(results)
    assert normalized[0]["normalized_score"] == 1.0
    assert normalized[2]["normalized_score"] == 0.0
    # Middle result should be between 0 and 1
    assert 0 < normalized[1]["normalized_score"] < 1


def test_normalize_bm25():
    """BM25 scores should be divided by max."""
    normalizer = ScoreNormalizer()
    results = [
        {"id": "e1", "score": 5.0},
        {"id": "e2", "score": 2.0},
    ]
    normalized = normalizer.normalize_bm25(results)
    assert normalized[0]["normalized_score"] == 1.0
    assert normalized[1]["normalized_score"] == 0.4


def test_normalize_empty():
    """Empty results should stay empty."""
    normalizer = ScoreNormalizer()
    assert normalizer.normalize_semantic([]) == []
    assert normalizer.normalize_bm25([]) == []


# ── RankFusion tests ──────────────────────────────────────────────────


def test_fusion_weights():
    """Default weights should sum to 1.0."""
    fusion = RankFusion()
    total = fusion.semantic_weight + fusion.bm25_weight + fusion.entity_weight
    assert abs(total - 1.0) < 0.001


def test_fusion_combines_three_channels():
    """Fusion should merge and score results from all three channels."""
    fusion = RankFusion()

    semantic_results = {"user_event": [{"id": "e1", "score": 0.9}]}
    bm25_results = {"user_event": [{"id": "e2", "score": 0.5}]}
    entity_boosts = {"boost_results": [{"event_id": "e1", "boost_score": 0.30}]}

    # Normalize first
    normalizer = ScoreNormalizer()
    sem_norm = normalizer.normalize_semantic(semantic_results["user_event"])
    bm25_norm = normalizer.normalize_bm25(bm25_results["user_event"])

    fused = fusion.fuse(
        semantic_hits=sem_norm,
        bm25_hits=bm25_norm,
        entity_boost_data=entity_boosts,
    )

    assert len(fused) > 0
    # e1 should score higher than e2 (has entity boost)
    e1_score = next((r["final_score"] for r in fused if r["id"] == "e1"), 0)
    e2_score = next((r["final_score"] for r in fused if r["id"] == "e2"), 0)
    assert e1_score > e2_score


def test_fusion_top_k_limit():
    """Fusion should limit results to top_k."""
    fusion = RankFusion(top_k=5)
    sem = [{"id": f"e{i}", "score": 1.0 - i * 0.1} for i in range(20)]
    fused = fusion.fuse(semantic_hits=sem, bm25_hits=[], entity_boost_data={})
    assert len(fused) <= 5
