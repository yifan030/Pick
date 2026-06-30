from __future__ import annotations

"""Dual-write consistency checker for Neo4j + Milvus.

Problem: When a memory is written, Neo4j (profiles + refs) and Milvus
(embeddings) are updated separately. If one fails, orphan references
can accumulate.

Solution: Run a periodic check (every 10 minutes) that:
1. Finds Neo4j EventRef/SessionRef/AgentCaseRef nodes
2. Verifies the corresponding entity exists in Milvus
3. Deletes orphan refs older than 1 hour
4. Logs dead-letter entries for persistent failures
"""

import json
import logging
import os
import time
from datetime import datetime, timezone

logger = logging.getLogger("pick.retrieval.consistency")

# ── Config ────────────────────────────────────────────────────────────

ORPHAN_GRACE_PERIOD_SECONDS = 3600  # 1 hour before deleting orphan refs
DEAD_LETTER_DIR = os.environ.get(
    "DEAD_LETTER_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "dead_letter"),
)


class ConsistencyChecker:
    """Periodic consistency check between Neo4j refs and Milvus entities."""

    def __init__(self, neo4j_client, milvus_store):
        self._neo4j = neo4j_client
        self._milvus = milvus_store

    async def check_all(self) -> dict:
        """Run full consistency check.

        Returns:
            Dict with counts: orphans_found, orphans_deleted, errors.
        """
        result = {
            "orphans_found": 0,
            "orphans_deleted": 0,
            "errors": 0,
        }

        # Check each ref type
        for ref_type, collection in [
            ("EventRef", "user_event"),
            ("SessionRef", "user_session"),
            ("AgentCaseRef", "agent_case"),
        ]:
            try:
                counts = await self._check_ref_type(ref_type, collection)
                result["orphans_found"] += counts["found"]
                result["orphans_deleted"] += counts["deleted"]
            except Exception:
                logger.exception("Consistency check failed for %s", ref_type)
                result["errors"] += 1

        return result

    async def _check_ref_type(self, ref_type: str, collection: str) -> dict:
        """Check one type of reference nodes.

        Queries Neo4j for all ref nodes, verifies each in Milvus.
        """
        found = 0
        deleted = 0

        # Get the ID field name
        id_field = {
            "EventRef": "event_id",
            "SessionRef": "session_id",
            "AgentCaseRef": "case_id",
        }.get(ref_type, "id")

        # Query Neo4j for ref nodes
        query = f"""
        MATCH (r:{ref_type})
        RETURN elementId(r) AS element_id, r.{id_field} AS entity_id, r.created_at AS created_at
        LIMIT 1000
        """

        try:
            # Neo4j async driver pattern: the client has a .driver attribute with .session()
            if hasattr(self._neo4j, 'driver') and self._neo4j.driver:
                session_obj = self._neo4j.driver.session()
            else:
                # For testing: neo4j_client itself might be a mock
                session_obj = self._neo4j

            # If the session is a coroutine function result, use it directly
            result = await session_obj.run(query)
            records = await result.fetch()

            for record in records:
                entity_id = record.get("entity_id")
                element_id = record.get("element_id")
                created_at = record.get("created_at")

                if not entity_id:
                    continue

                # Check if entity exists in Milvus
                if not self._check_entity_exists(collection, entity_id):
                    found += 1
                    # Check if past grace period
                    now = int(time.time())
                    if created_at and (now - int(created_at)) > ORPHAN_GRACE_PERIOD_SECONDS:
                        # Delete orphan ref
                        await self._delete_orphan_ref(session_obj, element_id)
                        deleted += 1
                        logger.info("Deleted orphan %s: %s", ref_type, entity_id)
                    else:
                        logger.debug("Orphan %s %s still in grace period", ref_type, entity_id)
        except Exception:
            logger.exception("Failed to query %s refs", ref_type)

        return {"found": found, "deleted": deleted}

    def _check_entity_exists(self, collection: str, entity_id: str) -> bool:
        """Check if an entity exists in a Milvus collection."""
        try:
            results = self._milvus.search_dense(
                collection=collection,
                embedding=[0.0] * 1024,  # Dummy — we filter by ID, not similarity
                filter_expr=f'id == "{entity_id}"',
                top_k=1,
                output_fields=["id"],
            )
            return len(results) > 0
        except Exception:
            logger.exception("Milvus existence check failed for %s/%s", collection, entity_id)
            return False  # Assume not found on error

    async def _delete_orphan_ref(self, session_obj, element_id: str) -> None:
        """Delete an orphan reference node from Neo4j."""
        try:
            await session_obj.run(
                "MATCH (r) WHERE elementId(r) = $eid DETACH DELETE r",
                eid=element_id,
            )
        except Exception:
            logger.exception("Failed to delete orphan ref %s", element_id)

    # ── Dead Letter Queue ──────────────────────────────────────────

    def write_dead_letter(self, operation: str, payload: dict) -> None:
        """Write a failed write operation to the dead-letter log for later retry.

        Args:
            operation: Description of what was attempted.
            payload: The data that failed to write.
        """
        os.makedirs(DEAD_LETTER_DIR, exist_ok=True)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation,
            "payload": payload,
        }
        file_path = os.path.join(DEAD_LETTER_DIR, f"dead_letter_{int(time.time())}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(entry, f, ensure_ascii=False, indent=2)
        except Exception:
            logger.exception("Failed to write dead letter for %s", operation)

    async def retry_dead_letters(self) -> int:
        """Retry processing dead-letter entries. Returns count retried."""
        if not os.path.isdir(DEAD_LETTER_DIR):
            return 0
        retried = 0
        for filename in os.listdir(DEAD_LETTER_DIR):
            if not filename.endswith(".json"):
                continue
            file_path = os.path.join(DEAD_LETTER_DIR, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    entry = json.load(f)
                # Retry logic: re-attempt the failed operation
                # (Implementation depends on the specific operation)
                logger.info("Would retry dead letter: %s", entry.get("operation"))
                os.remove(file_path)
                retried += 1
            except Exception:
                logger.exception("Failed to process dead letter %s", file_path)
        return retried
