from __future__ import annotations

"""ColdStartManager: detects new users and provides onboarding experience.

When a user has no profile/memory data in Neo4j, the retrieval pipeline
returns an onboarding prompt instead of empty search results. The manager
also attempts to import user behavior data from the Java backend to warm
the user's profile on first contact.
"""

import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger("pick.memory.cold_start")

# ── Onboarding prompt ──────────────────────────────────────────────────

ONBOARDING_PROMPT = """你是一个生活方式推荐助手，可以帮助用户发现好吃的、好玩的、优惠的。

你好！我是你的 AI 导购助手。我注意到你是新用户，暂时还没有你的偏好和记忆数据。

请告诉我：
- 你喜欢什么类型的餐厅或美食？（比如火锅、日料、川菜）
- 你的预算范围是多少？
- 有没有特别的饮食要求？（比如清真、素食）
- 你经常活动的商圈或区域？

这样我就能为你提供更精准的推荐了！或者你也可以直接告诉我你想吃什么、想买什么，我会尽力帮你找到最好的选择。"""


class ColdStartManager:
    """Detects cold-start users and orchestrates onboarding.

    A user is "cold" when they have no active profiles AND no event
    references in Neo4j.  On detection, the manager attempts to import
    behavior data (orders, bookmarks) from the Java backend. If the
    user remains cold after import, an onboarding prompt is returned.
    """

    def __init__(self, neo4j_client, java_client=None):
        """Initialize the cold start manager.

        Args:
            neo4j_client: Neo4jClient instance for profile/event queries.
            java_client: Optional httpx.Client (or factory) for Java API calls.
                         If None, uses ``get_java_client()`` from services.
        """
        self._neo4j = neo4j_client
        self._java_client = java_client

    async def is_cold_start(self, user_id: str) -> bool:
        """Check whether a user has no active data in Neo4j.

        Considers both profiles (read_profiles) and event references.
        Returns True if the user is cold (nothing found).
        """
        try:
            # 1. Check profile atoms
            profiles = await self._neo4j.read_profiles(user_id)
            if profiles:
                return False

            # 2. Check event references (imported behaviors, past turns)
            event_count = await self._count_event_refs(user_id)
            if event_count > 0:
                return False

            return True
        except Exception:
            logger.exception("Cold start check failed for user=%s", user_id)
            # On error, treat as cold for graceful degradation
            return True

    async def _count_event_refs(self, user_id: str) -> int:
        """Count EventRef nodes for a user via direct Cypher query."""
        query = """
        MATCH (u:User {user_id: $user_id})-[:PERFORMED]->(er:EventRef)
        RETURN count(er) AS cnt
        """
        async with self._neo4j.driver.session() as session:
            result = await session.run(query, user_id=user_id)
            record = await result.single()
            return record["cnt"] if record else 0

    async def run_behavior_import(self, user_id: str) -> bool:
        """Attempt to import user behavior data from the Java backend.

        Fetches order history and bookmarks, then creates EventRef
        nodes linking the user to the entities they interacted with.
        This warms the user from "cold" to "warm" so that subsequent
        retrieval has context to work with.

        Returns True if any data was imported.
        """
        imported = False

        try:
            bookmarks = await self._fetch_bookmarks(user_id)
            if bookmarks:
                await self._ingest_bookmarks(user_id, bookmarks)
                imported = True
                logger.info(
                    "Imported %d bookmarks for user=%s", len(bookmarks), user_id
                )
        except Exception:
            logger.exception("Bookmark import failed for user=%s", user_id)

        try:
            orders = await self._fetch_orders(user_id)
            if orders:
                await self._ingest_orders(user_id, orders)
                imported = True
                logger.info(
                    "Imported %d orders for user=%s", len(orders), user_id
                )
        except Exception:
            logger.exception("Order import failed for user=%s", user_id)

        return imported

    # ── Java backend fetch helpers ────────────────────────────────────

    async def _fetch_bookmarks(self, user_id: str) -> list[dict]:
        """Fetch user bookmarks from Java backend.

        Calls GET /api/bookmarks/internal/{userId}.
        """
        from src.agent.services.java_client import get_java_client

        client_factory = self._java_client or get_java_client
        with client_factory() as client:
            response = client.get(f"/api/bookmarks/internal/{user_id}")
            if response.status_code == 200:
                data = response.json()
                # Result<T> wrapper: {"success": true, "data": [...]}
                if isinstance(data, dict) and data.get("success"):
                    return data.get("data", [])
                return data if isinstance(data, list) else []
            logger.warning(
                "Bookmark fetch returned %d for user=%s",
                response.status_code, user_id,
            )
            return []

    async def _fetch_orders(self, user_id: str) -> list[dict]:
        """Fetch user order history from Java backend.

        Calls GET /api/orders/internal/user/{userId}.
        """
        from src.agent.services.java_client import get_java_client

        client_factory = self._java_client or get_java_client
        with client_factory() as client:
            response = client.get(f"/api/orders/internal/user/{user_id}")
            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and data.get("success"):
                    return data.get("data", [])
                return data if isinstance(data, list) else []
            logger.warning(
                "Order fetch returned %d for user=%s",
                response.status_code, user_id,
            )
            return []

    # ── Ingestion helpers ─────────────────────────────────────────────

    async def _ingest_bookmarks(self, user_id: str, bookmarks: list[dict]) -> None:
        """Convert bookmark rows into EventRef nodes in Neo4j.

        Each bookmark becomes an EventRef linking the user to a Shop
        entity, giving the retrieval pipeline context for first-time users.
        """
        for bm in bookmarks[:20]:  # cap to avoid flooding
            shop_id = bm.get("shop_id") or bm.get("shopId")
            if shop_id is None:
                continue
            event_id = f"import_bm_{user_id}_{uuid.uuid4().hex[:8]}"
            targets = [{"type": "Shop", "id": str(shop_id)}]
            await self._neo4j.write_event_ref(user_id, event_id, targets)

    async def _ingest_orders(self, user_id: str, orders: list[dict]) -> None:
        """Convert order rows into EventRef nodes in Neo4j.

        Each order becomes an EventRef linking the user to a Shop entity.
        Purchase signals are strong interest indicators.
        """
        for order in orders[:20]:  # cap to avoid flooding
            shop_id = order.get("shop_id") or order.get("shopId")
            if shop_id is None:
                continue
            event_id = f"import_ord_{user_id}_{uuid.uuid4().hex[:8]}"
            targets = [{"type": "Shop", "id": str(shop_id)}]
            await self._neo4j.write_event_ref(user_id, event_id, targets)

    @property
    def onboarding_prompt(self) -> str:
        """Return the onboarding prompt for cold-start users."""
        return ONBOARDING_PROMPT
