from __future__ import annotations

"""Retrieval Gateway: orchestrates three-way parallel memory retrieval.

On new sessions only (existing sessions reuse LangGraph checkpoint):
1. SemanticSearch: dense vector search across all memory collections
2. BM25Search: sparse keyword search across all memory collections
3. EntityBoost: Neo4j subgraph traversal + profile/hard-constraint lookup
4. ScoreNormalizer + RankFusion: merge and rank results
5. Returns structured memory context for system prompt injection
"""

import logging
from src.retrieval.semantic_search import SemanticSearch
from src.retrieval.bm25_search import BM25Search
from src.retrieval.entity_boost import EntityBoost
from src.retrieval.fusion import ScoreNormalizer, RankFusion

logger = logging.getLogger("pick.retrieval.gateway")


class RetrievalGateway:
    """Orchestrates three-way memory retrieval for new sessions."""

    def __init__(
        self,
        milvus_store,
        neo4j_client,
        top_k: int = 10,
        cold_start_manager=None,
    ):
        self._milvus = milvus_store
        self._neo4j = neo4j_client
        self._top_k = top_k
        self._cold_start = cold_start_manager

        # Lazy-init searchers
        self._semantic: SemanticSearch | None = None
        self._bm25: BM25Search | None = None
        self._entity_boost: EntityBoost | None = None
        self._normalizer = ScoreNormalizer()
        self._fusion = RankFusion(top_k=top_k)

    @property
    def semantic(self) -> SemanticSearch:
        if self._semantic is None:
            self._semantic = SemanticSearch(self._milvus)
        return self._semantic

    @property
    def bm25(self) -> BM25Search:
        if self._bm25 is None:
            self._bm25 = BM25Search(self._milvus)
        return self._bm25

    @property
    def entity_boost(self) -> EntityBoost:
        if self._entity_boost is None:
            self._entity_boost = EntityBoost(self._neo4j)
        return self._entity_boost

    async def retrieve(
        self,
        user_id: str,
        query: str,
        is_new_session: bool = True,
    ) -> dict:
        """Run memory retrieval for a conversation turn.

        Args:
            user_id: The user's ID.
            query: The user's query text.
            is_new_session: Whether this is a new session. If False,
                           retrieval is skipped (context is in checkpoint).

        Returns:
            Dict with:
            - memories: list of fused memory results (top_k)
            - profiles: list of profile atoms for prompt injection
            - hard_constraints: list of hard constraint atoms
            - entity_data: entity extraction results
            - retrieval_skipped: bool
        """
        if not is_new_session:
            logger.debug("Existing session — skipping retrieval")
            return {
                "memories": [],
                "profiles": [],
                "hard_constraints": [],
                "entity_data": {},
                "retrieval_skipped": True,
                "cold_start": False,
                "onboarding_prompt": "",
            }

        # ── 0. Cold start detection (before three-way search) ─────
        if self._cold_start is not None:
            try:
                is_cold = await self._cold_start.is_cold_start(user_id)
                if is_cold:
                    logger.info("Cold start detected for user=%s", user_id)
                    await self._cold_start.run_behavior_import(user_id)

                    # Re-check after behavior import
                    still_cold = await self._cold_start.is_cold_start(user_id)
                    if still_cold:
                        logger.info(
                            "User=%s still cold after behavior import — "
                            "returning onboarding prompt", user_id
                        )
                        return {
                            "memories": [],
                            "profiles": [],
                            "hard_constraints": [],
                            "entity_data": {},
                            "retrieval_skipped": False,
                            "cold_start": True,
                            "onboarding_prompt": self._cold_start.onboarding_prompt,
                        }
                    logger.info(
                        "User=%s warmed by behavior import", user_id
                    )
            except Exception:
                logger.exception(
                    "Cold start check failed for user=%s — "
                    "proceeding with normal retrieval", user_id
                )
                # On error, fall through to normal retrieval

        # ── 1. Run three-way search in parallel ────────────────────
        # Semantic and BM25 are synchronous Milvus calls
        sem_results = self.semantic.search(query, user_id)

        bm25_results = self.bm25.search(query, user_id)

        # Entity boost is async (Neo4j)
        entity_data = await self.entity_boost.search(user_id, query)

        # ── 2. Normalize scores per channel ────────────────────────
        # Flatten collection results into single lists
        sem_hits = []
        for coll_results in sem_results.values():
            sem_hits.extend(coll_results)
        sem_hits = self._normalizer.normalize_semantic(sem_hits)

        bm25_hits = []
        for coll_results in bm25_results.values():
            bm25_hits.extend(coll_results)
        bm25_hits = self._normalizer.normalize_bm25(bm25_hits)

        # ── 3. Fuse ────────────────────────────────────────────────
        fused = self._fusion.fuse(
            semantic_hits=sem_hits,
            bm25_hits=bm25_hits,
            entity_boost_data=entity_data,
        )

        logger.info(
            "Retrieval: sem=%d bm25=%d entity=%d → fused=%d for user=%s query=%.50s",
            len(sem_hits), len(bm25_hits),
            len(entity_data.get("boost_results", [])),
            len(fused), user_id, query,
        )

        return {
            "memories": fused,
            "profiles": entity_data.get("profiles", []),
            "hard_constraints": entity_data.get("hard_constraints", []),
            "entity_data": entity_data.get("extracted_entities", {}),
            "retrieval_skipped": False,
            "cold_start": False,
            "onboarding_prompt": "",
        }
