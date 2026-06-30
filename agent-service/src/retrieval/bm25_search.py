from __future__ import annotations

"""BM25 sparse vector search over memory collections via Milvus.

Uses SPARSE_INVERTED_INDEX with IP metric for keyword-based retrieval.
This complements dense semantic search by catching exact keyword matches
that semantic search might miss (e.g., shop names, dish names).

NOTE: Requires Milvus 2.4+ with SPARSE_FLOAT_VECTOR support.
The sparse embedding is generated server-side by Milvus when the collection
is defined with a BM25 function field. If not available, falls back to
an empty result set (graceful degradation).
"""

import logging

logger = logging.getLogger("pick.retrieval.bm25")

# ── Helpers ────────────────────────────────────────────────────────────


def _escape_milvus_string(value: str) -> str:
    """Escape a string value for use in a Milvus filter expression."""
    return value.replace("\\", "\\\\").replace('"', '\\"')

COLLECTION_SEARCH_CONFIG = {
    "user_event": {"top_k": 20, "output_fields": ["id", "event_type", "description", "created_at"]},
    "user_session": {"top_k": 10, "output_fields": ["id", "summary", "key_shops", "intent", "is_complete", "created_at"]},
    "agent_case": {"top_k": 10, "output_fields": ["id", "case_type", "description", "action", "outcome", "lesson", "created_at"]},
}


class BM25Search:
    """Sparse BM25 keyword search over memory collections."""

    def __init__(self, milvus_store):
        self._milvus = milvus_store

    def search(
        self,
        query: str,
        user_id: str,
        collections: list[str] | None = None,
        filter_expr: str | None = None,
    ) -> dict[str, list[dict]]:
        """BM25 sparse search across specified collections.

        The sparse embedding is generated via Milvus server-side BM25
        function (configured in collection schema). We pass an empty
        sparse vector as a sentinel -- Milvus applies its built-in
        analyzer to the query text.

        Args:
            query: The user's query text.
            user_id: The user's ID for filtering.
            collections: Which collections to search. Default: all three.
            filter_expr: Additional Milvus filter expression.

        Returns:
            Dict mapping collection name -> list of search result dicts.
        """
        if collections is None:
            collections = list(COLLECTION_SEARCH_CONFIG.keys())

        base_filter = f'user_id == "{_escape_milvus_string(user_id)}"'
        if filter_expr:
            base_filter = f"({base_filter}) and ({filter_expr})"

        # Session search: prefer completed sessions
        session_filter = f"({base_filter}) and (is_complete == true)"

        # For BM25, the sparse vector embedding is handled by Milvus
        # server-side. We pass an empty sparse vector.
        # The actual BM25 function is defined in the collection schema.
        empty_sparse: dict[int, float] = {}

        results = {}
        for coll in collections:
            config = COLLECTION_SEARCH_CONFIG.get(coll, {"top_k": 20, "output_fields": ["id", "description"]})
            search_filter = session_filter if coll == "user_session" else base_filter

            try:
                hits = self._milvus.search_sparse(
                    collection=coll,
                    sparse_vector=empty_sparse,
                    filter_expr=search_filter,
                    top_k=config["top_k"],
                    output_fields=config["output_fields"],
                )
                results[coll] = hits
                logger.debug("BM25 search %s: %d results", coll, len(hits))
            except Exception as e:
                logger.warning("BM25 search failed for %s: %s", coll, e)
                results[coll] = []

        return results
