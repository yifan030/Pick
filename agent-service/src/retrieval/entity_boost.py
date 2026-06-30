from __future__ import annotations

"""Entity Boost: Neo4j subgraph traversal for entity-aware retrieval.

Extracts entities (areas, cuisines, shops) from the user query, then
traverses the Neo4j entity graph to find memories associated with those
entities. Scores are in [0, 0.30] range per the spec.

Also retrieves the user's full profile and hard constraints for injection
into the system prompt (separate from the rank fusion path).
"""

import logging
from src.storage.models import AnyProfile

logger = logging.getLogger("pick.retrieval.entity_boost")

# ── Entity boost weights ──────────────────────────────────────────────

DIRECT_ENTITY_BOOST = 0.30       # Direct entity match (shop, area, category)
PROFILE_INDIRECT_BOOST = 0.15    # Profile-based indirect association
NO_ASSOCIATION_BOOST = 0.0

# ── Known entities for extraction from queries ─────────────────────────

KNOWN_AREAS = [
    "春熙路", "太古里", "宽窄巷子", "玉林", "建设路", "锦里",
    "九眼桥", "科华北路", "桐梓林", "万象城", "大悦城",
]

KNOWN_CUISINES = [
    "火锅", "川渝火锅", "川菜", "粤菜", "湘菜", "鲁菜", "淮扬菜",
    "日料", "韩料", "泰式", "西餐", "烧烤", "串串", "冒菜",
    "面馆", "小吃", "甜品", "咖啡", "奶茶", "酒吧",
]


class EntityBoost:
    """Neo4j subgraph traversal for entity-aware memory retrieval."""

    def __init__(self, neo4j_client):
        self._neo4j = neo4j_client

    def extract_entities(self, query: str) -> dict:
        """Extract known entities from the user query.

        Simple keyword matching against known areas and cuisines.
        Can be enhanced with NER model later.

        Returns:
            Dict with keys: areas, cuisines (list of str).
        """
        areas = [a for a in KNOWN_AREAS if a in query]
        cuisines = [c for c in KNOWN_CUISINES if c in query]
        return {"areas": areas, "cuisines": cuisines, "shop_ids": []}

    async def search(self, user_id: str, query: str) -> dict:
        """Run entity boost search.

        Returns:
            Dict with:
            - boost_results: list of {event_id, boost_score, matched_entity}
            - profiles: list of all active profile atoms (for prompt injection)
            - hard_constraints: list of hard constraint profile atoms
        """
        entities = self.extract_entities(query)

        # 1. Subgraph traversal for entity-boosted memory references
        boost_results = []
        try:
            boost_results = await self._neo4j.subgraph_search(
                user_id=user_id,
                entities=entities,
                limit=20,
            )
        except Exception:
            logger.exception("Neo4j subgraph search failed")

        # 2. Get all profiles for system prompt injection
        profiles = []
        try:
            profiles = self._neo4j.read_profiles(user_id)
        except Exception:
            logger.exception("Failed to read profiles for prompt injection")

        # 3. Get hard constraints (always injected)
        hard_constraints = []
        try:
            hard_constraints = self._neo4j.get_hard_constraints(user_id)
        except Exception:
            logger.exception("Failed to read hard constraints")

        return {
            "boost_results": boost_results,
            "profiles": profiles,
            "hard_constraints": hard_constraints,
            "extracted_entities": entities,
        }

    @staticmethod
    def compute_boost(
        entity_search_result: dict,
        memory_id: str,
        memory_type: str = "event",
    ) -> float:
        """Compute entity boost score for a specific memory result.

        Args:
            entity_search_result: Output from EntityBoost.search().
            memory_id: The ID of the memory being scored.
            memory_type: "event" | "session" | "agent_case".

        Returns:
            Boost score in [0, 0.30].
        """
        boost_results = entity_search_result.get("boost_results", [])
        if not boost_results:
            return NO_ASSOCIATION_BOOST

        for br in boost_results:
            if br.get("event_id") == memory_id:
                # Direct match via entity link
                return DIRECT_ENTITY_BOOST

        # Check if any profile is associated
        profiles = entity_search_result.get("profiles", [])
        if profiles:
            return PROFILE_INDIRECT_BOOST

        return NO_ASSOCIATION_BOOST
