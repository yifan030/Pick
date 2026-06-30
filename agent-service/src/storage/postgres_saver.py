# src/storage/postgres_saver.py
"""PostgresSaver for LangGraph checkpoint persistence.

Replaces InMemorySaver. Checkpoints survive process restarts.
Session history no longer needs Redis — it's in the checkpointer.
"""

import logging
import os
from langgraph.checkpoint.postgres import PostgresSaver

logger = logging.getLogger("pick.storage.postgres_saver")

# ── Config ────────────────────────────────────────────────────────────

PG_CHECKPOINT_URI = os.environ.get(
    "PG_CHECKPOINT_URI",
    "postgresql://pick:pick-pg-dev@localhost:5433/pick_agent_checkpoint",
)


class PostgresSaverManager:
    """Manages the lifecycle of a PostgresSaver instance.

    Usage:
        manager = PostgresSaverManager()
        await manager.setup()
        saver = manager.create_saver()
        # Pass saver to agent builder
    """

    def __init__(self, conn_string: str | None = None):
        self._conn_string = conn_string or PG_CHECKPOINT_URI
        self._saver: PostgresSaver | None = None

    async def setup(self) -> None:
        """Create the checkpoint tables if they don't exist."""
        saver = PostgresSaver.from_conn_string(self._conn_string)
        await saver.setup()
        logger.info("PostgresSaver tables initialized")
        self._saver = saver

    def create_saver(self) -> PostgresSaver:
        """Return a PostgresSaver instance for use with LangGraph.

        Must be called after setup().
        """
        if self._saver is not None:
            return self._saver
        # Create new instance; setup() is idempotent but we prefer explicit
        saver = PostgresSaver.from_conn_string(self._conn_string)
        logger.info("PostgresSaver created")
        return saver

    async def close(self) -> None:
        """Close the saver connection pool."""
        if self._saver:
            # PostgresSaver manages its own pool
            pass
        self._saver = None
