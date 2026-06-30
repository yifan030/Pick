from __future__ import annotations

"""Score normalization and rank fusion for multi-channel retrieval.

Implements the mem0 v3 approach:
1. Normalize each channel's scores to [0, 1]
2. Fuse with weighted sum: semantic x 0.45 + BM25 x 0.25 + entity x 0.30
3. Return top-K results (default 10)
"""

import logging

logger = logging.getLogger("pick.retrieval.fusion")

# ── Default Weights ───────────────────────────────────────────────────

DEFAULT_SEMANTIC_WEIGHT = 0.45
DEFAULT_BM25_WEIGHT = 0.25
DEFAULT_ENTITY_WEIGHT = 0.30
DEFAULT_TOP_K = 10

# ── Per-type limits in final results ──────────────────────────────────

PER_TYPE_LIMITS = {
    "event": 3,
    "session": 2,
    "profile": 5,     # Profiles come from EntityBoost, not fusion
}


class ScoreNormalizer:
    """Normalizes search scores from different channels to [0, 1]."""

    @staticmethod
    def normalize_semantic(results: list[dict]) -> list[dict]:
        """Normalize semantic (cosine) scores via min-max scaling.

        normalized = (score - min) / (max - min)
        Single result -> 1.0
        """
        if not results:
            return []
        scores = [r.get("score", r.get("distance", 0)) for r in results]
        min_s = min(scores)
        max_s = max(scores)
        if max_s == min_s:
            # All same score -> all 1.0
            for r in results:
                r["normalized_score"] = 1.0
            return results
        for r in results:
            s = r.get("score", r.get("distance", 0))
            r["normalized_score"] = (s - min_s) / (max_s - min_s)
        return results

    @staticmethod
    def normalize_bm25(results: list[dict]) -> list[dict]:
        """Normalize BM25 scores by dividing by max.

        normalized = score / max_score
        """
        if not results:
            return []
        scores = [r.get("score", 0) for r in results]
        max_s = max(scores)
        if max_s == 0:
            for r in results:
                r["normalized_score"] = 0.0
            return results
        for r in results:
            r["normalized_score"] = r.get("score", 0) / max_s
        return results

    @staticmethod
    def normalize(results: list[dict], channel: str = "semantic") -> list[dict]:
        """Convenience method: normalize by channel type."""
        if channel == "bm25":
            return ScoreNormalizer.normalize_bm25(results)
        return ScoreNormalizer.normalize_semantic(results)


class RankFusion:
    """Fuses results from semantic, BM25, and entity boost channels."""

    def __init__(
        self,
        semantic_weight: float = DEFAULT_SEMANTIC_WEIGHT,
        bm25_weight: float = DEFAULT_BM25_WEIGHT,
        entity_weight: float = DEFAULT_ENTITY_WEIGHT,
        top_k: int = DEFAULT_TOP_K,
    ):
        self.semantic_weight = semantic_weight
        self.bm25_weight = bm25_weight
        self.entity_weight = entity_weight
        self.top_k = top_k

    def fuse(
        self,
        semantic_hits: list[dict],
        bm25_hits: list[dict],
        entity_boost_data: dict | None = None,
    ) -> list[dict]:
        """Fuse results from all three channels.

        Args:
            semantic_hits: Normalized semantic search results.
            bm25_hits: Normalized BM25 search results.
            entity_boost_data: Entity boost search output (with boost_results).

        Returns:
            List of fused results sorted by final_score descending,
            limited to top_k. Each result has: id, final_score, source_channels,
            description (from the highest-scoring source), and entity_boost.
        """
        # Build a unified map: memory_id -> accumulated scores
        fused_map: dict[str, dict] = {}

        # ── Add semantic hits ──────────────────────────────────────
        for hit in semantic_hits:
            mid = hit.get("id", "")
            if not mid:
                continue
            score = hit.get("normalized_score", 0) * self.semantic_weight
            self._add_to_map(fused_map, mid, hit, score, "semantic")

        # ── Add BM25 hits ──────────────────────────────────────────
        for hit in bm25_hits:
            mid = hit.get("id", "")
            if not mid:
                continue
            score = hit.get("normalized_score", 0) * self.bm25_weight
            self._add_to_map(fused_map, mid, hit, score, "bm25")

        # ── Add entity boost ───────────────────────────────────────
        if entity_boost_data:
            boost_results = entity_boost_data.get("boost_results", [])
            for br in boost_results:
                mid = br.get("event_id", "")
                if not mid:
                    continue
                boost = br.get("boost_score", 0)
                if mid in fused_map:
                    fused_map[mid]["entity_boost"] = boost
                    fused_map[mid]["final_score"] += boost
                # Don't add new entries from entity boost alone — it's a boost,
                # not a standalone retrieval channel.

        # ── Sort by final score ────────────────────────────────────
        sorted_results = sorted(
            fused_map.values(),
            key=lambda x: x["final_score"],
            reverse=True,
        )

        # Apply per-type limits
        limited = self._apply_per_type_limits(sorted_results)

        return limited[:self.top_k]

    @staticmethod
    def _add_to_map(
        fused_map: dict, mid: str, hit: dict, score: float, source: str
    ):
        """Add or update a result in the fusion map."""
        if mid not in fused_map:
            fused_map[mid] = {
                "id": mid,
                "final_score": score,
                "source_channels": [source],
                "description": hit.get("entity", {}).get("description", "")
                            or hit.get("description", ""),
                "entity_boost": 0.0,
                "hit_data": hit,
            }
        else:
            fused_map[mid]["final_score"] += score
            fused_map[mid]["source_channels"].append(source)

    @staticmethod
    def _apply_per_type_limits(results: list[dict]) -> list[dict]:
        """Apply per-type result limits to prevent one type dominating."""
        counts: dict[str, int] = {}
        limited = []
        for r in results:
            # Determine type from ID prefix
            if r["id"].startswith("evt_"):
                mem_type = "event"
            elif r["id"].startswith("sess_"):
                mem_type = "session"
            elif r["id"].startswith("case_"):
                mem_type = "agent_case"
            else:
                mem_type = "unknown"

            limit = PER_TYPE_LIMITS.get(mem_type, 10)
            counts.setdefault(mem_type, 0)
            if counts[mem_type] < limit:
                counts[mem_type] += 1
                limited.append(r)

        return limited
