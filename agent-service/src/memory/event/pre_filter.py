# src/memory/pre_filter.py
"""Vector Pre-Filter: reduces LLM context by pre-screening existing profiles.

Motivation (from VikingMem): injecting ALL user profiles into the LLM prompt
for delta computation grows linearly with profile count. Instead:
1. Embed the current turn's events
2. Search Milvus for similar historical events
3. Trace those events back to associated Profile atoms via Neo4j
4. Only inject those relevant profiles + hard constraints into the LLM prompt
"""

from __future__ import annotations

import logging

from src.storage.embedding import embed_texts
from src.storage.models import (
    AnyProfile,
    DietaryPreference,
    MemoryEvent,
)

logger = logging.getLogger("pick.memory.pre_filter")

# ── Event type → relevant profile types ─────────────────────────────────

EVENT_TYPE_TO_PROFILE_TYPES: dict[str, list[str]] = {
    "search":      ["CuisinePreference", "AreaPreference", "BudgetPreference"],
    "purchase":    ["BudgetPreference", "CuisinePreference"],
    "reservation": ["AreaPreference", "ScenePreference"],
    "view":        ["CuisinePreference", "AreaPreference"],
    "feedback":    [
        "TastePreference", "BudgetPreference", "ConstraintPreference",
        "CuisinePreference", "AreaPreference", "ScenePreference",
    ],
    "constraint":  ["ConstraintPreference"],
    "dietary":     ["DietaryPreference"],
}
"""Maps behavioural event types to the Profile node types they can affect.

Used by :class:`VectorPreFilter` to select which existing profiles are
relevant for the current conversation turn — only profiles whose types
match the event types in the turn are returned (plus hard constraints,
which are always included).
"""


class VectorPreFilter:
    """Pre-filters existing profiles by relevance to the current conversation.

    Uses semantic similarity search over historical events in Milvus to
    identify which existing profiles are relevant to update.
    """

    def __init__(self, neo4j_client, milvus_store):
        """
        Args:
            neo4j_client: Neo4jClient instance for profile lookup.
            milvus_store: MilvusMemoryStore instance for event search.
        """
        self._neo4j = neo4j_client
        self._milvus = milvus_store

    def filter(
        self,
        user_id: str,
        events: list[MemoryEvent],
        top_k: int = 10,
    ) -> list[AnyProfile]:
        """Find existing profiles relevant to the current conversation turn.

        Returns a deduplicated list of profiles for LLM delta computation.
        Hard constraints (is_hard=true) are always included.

        Args:
            user_id: The user's ID.
            events: Events extracted from the current turn.
            top_k: Max similar historical events to consider.

        Returns:
            List of relevant ProfileAtom instances.
        """
        if not events:
            return []

        # Build a combined description from all events for embedding
        combined_text = " ".join(e.description for e in events if e.description)
        stripped = combined_text.strip()

        if not stripped:
            return []

        # 1. Embed the combined text
        try:
            embedding = embed_texts([stripped])[0]
        except Exception:
            logger.exception("Embedding failed for pre-filter, falling back to all profiles")
            return self._neo4j.read_profiles(user_id)

        # 2. Search Milvus for similar historical events
        try:
            safe_uid = user_id.replace('"', '\\"')
            results = self._milvus.search_dense(
                collection="user_event",
                embedding=embedding,
                filter_expr=f'user_id == "{safe_uid}"',
                top_k=top_k,
                output_fields=["id", "event_type", "description"],
            )
        except Exception:
            logger.exception("Milvus search failed in pre-filter")
            results = []

        # 3. Collect event IDs from results
        event_ids = []
        for r in results:
            rid = r.get("id") or (r.get("entity") or {}).get("id")
            if rid:
                event_ids.append(rid)

        # 4. Read all existing profiles from Neo4j
        try:
            all_profiles = self._neo4j.read_profiles(user_id)
        except Exception:
            logger.exception("Failed to read profiles in pre-filter")
            all_profiles = []

        # 5. Always include hard constraints
        try:
            hard_constraints = self._neo4j.get_hard_constraints(user_id)
        except Exception:
            logger.exception("Failed to fetch hard constraints")
            hard_constraints = []

        # 6. Deduplicate: combine matched profiles + hard constraints
        result_ids = set()
        result: list[AnyProfile] = []

        # Add hard constraints first (always included)
        for p in hard_constraints:
            pid = self._profile_key(p)
            if pid not in result_ids:
                result_ids.add(pid)
                result.append(p)

        # Determine relevant profile types from current + historical events.
        # When there are matching historical events, only return profiles
        # whose types are relevant to the event types in play — plus hard
        # constraints (always included).  When there are *no* matches
        # (cold start), return hard constraints only.
        if event_ids:
            relevant_types = self._get_relevant_profile_types(events, results)
            for p in all_profiles:
                if p.node_type() in relevant_types:
                    pid = self._profile_key(p)
                    if pid not in result_ids:
                        result_ids.add(pid)
                        result.append(p)

        logger.debug(
            "Pre-filter: %d events -> %d matching event IDs -> %d profiles (%d hard)",
            len(events),
            len(event_ids),
            len(result),
            len(hard_constraints),
        )
        return result

    def _get_relevant_profile_types(
        self,
        current_events: list[MemoryEvent],
        matching_results: list[dict],
    ) -> set[str]:
        """Derive the set of relevant profile types from current and historical events.

        Iterates over the event types in *current_events* and the event types
        found in *matching_results* (historical Milvus events), maps each
        type to a set of profile node type names via
        :data:`EVENT_TYPE_TO_PROFILE_TYPES`, and returns the union.

        Unknown event types are silently ignored (they map to the empty set).
        """
        relevant: set[str] = set()

        # 1. Current turn events
        for event in current_events:
            mapped = EVENT_TYPE_TO_PROFILE_TYPES.get(event.event_type, [])
            relevant.update(mapped)

        # 2. Matching historical events
        for result in matching_results:
            entity = result.get("entity", {})
            event_type = entity.get("event_type", "") or result.get("event_type", "")
            if event_type:
                mapped = EVENT_TYPE_TO_PROFILE_TYPES.get(event_type, [])
                relevant.update(mapped)

        return relevant

    @staticmethod
    def _profile_key(profile: AnyProfile) -> str:
        """Generate a unique key for a profile atom for deduplication."""
        nt = profile.node_type()
        if nt == "TastePreference":
            return "{}:{}:{}".format(
                nt, getattr(profile, "property", ""), getattr(profile, "value", "")
            )
        elif nt == "DietaryPreference":
            return "{}:{}".format(nt, getattr(profile, "constraint", ""))
        elif nt == "CuisinePreference":
            return "{}:{}".format(nt, getattr(profile, "cuisine", ""))
        elif nt == "AreaPreference":
            return "{}:{}".format(nt, getattr(profile, "area", ""))
        elif nt == "ScenePreference":
            return "{}:{}".format(nt, getattr(profile, "scene", ""))
        elif nt == "BudgetPreference":
            return "{}:{}".format(nt, getattr(profile, "type", ""))
        elif nt == "ConstraintPreference":
            return "{}:{}".format(nt, getattr(profile, "constraint", ""))
        return "{}:{}".format(nt, id(profile))
