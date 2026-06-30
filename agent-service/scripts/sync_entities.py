# scripts/sync_entities.py
"""One-shot script: sync MySQL → Neo4j entity graph.

Usage:
    python scripts/sync_entities.py

Requires:
- Java backend running on localhost:8085
- Neo4j running on localhost:7687
"""

import asyncio
import logging
from src.storage.neo4j_client import Neo4jClient
from src.sync.entity_sync import sync_all_entities

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sync_entities")


async def main():
    neo4j = Neo4jClient(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="pick-neo4j-dev",
    )
    await neo4j.connect()
    try:
        counts = await sync_all_entities(neo4j)
        logger.info("Sync complete: %s", counts)
    finally:
        await neo4j.close()


if __name__ == "__main__":
    asyncio.run(main())
