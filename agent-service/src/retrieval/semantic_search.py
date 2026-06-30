from __future__ import annotations

"""Dense semantic search over memory collections via Milvus HNSW/COSINE.

Searches across user_event, user_session, and agent_case collections
with configurable per-collection limits.
"""

import logging
from src.storage.embedding import embed_single

logger = logging.getLogger("pick.retrieval.semantic")

# ── Helpers ────────────────────────────────────────────────────────────


def _escape_milvus_string(value: str) -> str:
    """Escape a string value for use in a Milvus filter expression."""
    return value.replace("\\", "\\\\").replace('"', '\\"')

# ── Collection search config ──────────────────────────────────────────

COLLECTION_SEARCH_CONFIG = {
    "user_event": {"top_k": 20, "output_fields": ["id", "event_type", "description", "payload", "created_at"]},
    "user_session": {"top_k": 10, "output_fields": ["id", "summary", "key_shops", "key_areas", "intent", "is_complete", "created_at"]},
    "agent_case": {"top_k": 10, "output_fields": ["id", "case_type", "description", "action", "outcome", "lesson", "created_at"]},
}


class SemanticSearch:
    """Dense vector search over memory collections."""

    def __init__(self, milvus_store):
        self._milvus = milvus_store

    def search(
        self,
        query: str,
        user_id: str,
        collections: list[str] | None = None,
        filter_expr: str | None = None,
    ) -> dict[str, list[dict]]:
        """Dense semantic search across specified collections.

        Args:
            query: The user's query text (will be embedded).
            user_id: The user's ID for filtering.
            collections: Which collections to search. Default: all three.
            filter_expr: Additional Milvus filter expression.

        Returns:
            Dict mapping collection name -> list of search result dicts.
            Each result has: id, score (cosine distance), entity (field values).
        """
        if collections is None:
            collections = list(COLLECTION_SEARCH_CONFIG.keys())

        # Build base filter
        base_filter = f'user_id == "{_escape_milvus_string(user_id)}"'
        if filter_expr:
            base_filter = f"({base_filter}) and ({filter_expr})"

        # Session search: prefer completed sessions
        session_filter = f'({base_filter}) and (is_complete == true)'

        # Embed query
        try:
            query_embedding = embed_single(query)
        except Exception:
            logger.exception("Query embedding failed")
            return {c: [] for c in collections}

        results = {}
        for coll in collections:
            config = COLLECTION_SEARCH_CONFIG.get(coll, {"top_k": 20, "output_fields": ["id", "description"]})
            search_filter = session_filter if coll == "user_session" else base_filter

            try:
                hits = self._milvus.search_dense(
                    collection=coll,
                    embedding=query_embedding,
                    filter_expr=search_filter,
                    top_k=config["top_k"],
                    output_fields=config["output_fields"],
                )
                results[coll] = hits
                logger.debug("Semantic search %s: %d results", coll, len(hits))
            except Exception:
                logger.exception("Semantic search failed for collection %s", coll)
                results[coll] = []

        return results
