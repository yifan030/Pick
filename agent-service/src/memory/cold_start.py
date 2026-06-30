# src/memory/cold_start.py
"""Cold start manager — imports user behavior data into profile atoms.

When a user has no existing profiles (cold start), this module fetches
historical behavior data (favorites, orders) from the Java backend and
converts them into initial profile atoms with moderate confidence.

This is triggered by MemoryControlHandler (D4) before the main write
pipeline runs for a new user.
"""

from __future__ import annotations

import logging
from typing import Any

from src.storage.models import (
    AreaPreference,
    BudgetPreference,
    CuisinePreference,
)

logger = logging.getLogger("pick.memory.cold_start")


class ColdStartManager:
    """Manages cold-start profile initialization from behavioral data.

    Orchestrates the cold-start flow:
      1. Check whether the user has existing profiles (is_cold_start).
      2. Fetch historical behavior data from the Java backend (favorites + orders).
      3. Convert behavior data into typed profile atoms with moderate confidence.
      4. Write all profiles to Neo4j and return the count written.

    Parameters
    ----------
    neo4j_client :
        An async Neo4j client with ``read_profiles(user_id)`` and
        ``write_profile(user_id, profile)`` methods.
    java_client :
        An optional async Java API client with ``get_user_favorites(user_id)``
        and ``get_user_orders(user_id)`` methods.  When *None*,
        ``fetch_behavior_data`` returns ``{}``.
    """

    def __init__(self, neo4j_client: Any = None, java_client: Any = None) -> None:
        self._neo4j = neo4j_client
        self._java_client = java_client

    # ── Public API ────────────────────────────────────────────────────

    async def is_cold_start(self, user_id: str) -> bool:
        """Return True when the user has *no* existing profile atoms.

        Delegates to :meth:`Neo4jClient.read_profiles` and returns
        ``True`` when the result list is empty.
        """
        if self._neo4j is None:
            logger.warning("Neo4j client not configured — assuming cold start")
            return True
        profiles = await self._neo4j.read_profiles(user_id)
        return len(profiles) == 0

    async def fetch_behavior_data(self, user_id: str) -> dict:
        """Fetch favorites and orders from the Java backend.

        Returns a dict with keys ``"favorites"`` and ``"orders"`` (each a
        list of dicts).  Returns ``{}`` when *java_client* is ``None``
        or when the API calls fail.
        """
        if self._java_client is None:
            return {}

        result: dict[str, list[dict]] = {"favorites": [], "orders": []}
        try:
            favorites = await self._java_client.get_user_favorites(user_id)
            result["favorites"] = favorites or []
        except Exception:
            logger.exception("Failed to fetch favorites for user %s", user_id)

        try:
            orders = await self._java_client.get_user_orders(user_id)
            result["orders"] = orders or []
        except Exception:
            logger.exception("Failed to fetch orders for user %s", user_id)

        return result

    def build_profiles_from_behavior(
        self,
        user_id: str,
        behavior_data: dict,
    ) -> list:
        """Convert behavior data dict into a list of profile atoms.

        Each profile carries ``source="behavior_import"`` and a confidence
        between 0.4 and 0.6, reflecting the heuristic nature of the data.

        Rules
        -----
        * **CuisinePreference** — extracted from ``cuisine`` or
          ``shop_type`` fields of favorites (confidence 0.5) and orders
          (confidence 0.4).  Duplicates across both sources are deduplicated
          (favorites take priority).
        * **AreaPreference** — extracted from ``area`` fields with the
          same confidence scheme as cuisine.
        * **BudgetPreference** — computed as the average order price
          +/-30 %, confidence 0.5.  Only created when at least one order
          has a non-zero ``price``.
        """
        profiles: list = []

        favorites = behavior_data.get("favorites", []) or []
        orders = behavior_data.get("orders", []) or []

        # ── CuisinePreference ─────────────────────────────────────────
        seen_cuisines: set[str] = set()

        for item in favorites:
            cuisine = item.get("cuisine") or item.get("shop_type")
            if cuisine and cuisine not in seen_cuisines:
                seen_cuisines.add(cuisine)
                p = CuisinePreference(
                    user_id=user_id,
                    cuisine=cuisine,
                    confidence=0.5,
                    weight=0.7,
                )
                p.source = "behavior_import"
                profiles.append(p)

        for item in orders:
            cuisine = item.get("cuisine") or item.get("shop_type")
            if cuisine and cuisine not in seen_cuisines:
                seen_cuisines.add(cuisine)
                p = CuisinePreference(
                    user_id=user_id,
                    cuisine=cuisine,
                    confidence=0.4,
                    weight=0.6,
                )
                p.source = "behavior_import"
                profiles.append(p)

        # ── AreaPreference ────────────────────────────────────────────
        seen_areas: set[str] = set()

        for item in favorites:
            area = item.get("area")
            if area and area not in seen_areas:
                seen_areas.add(area)
                p = AreaPreference(
                    user_id=user_id,
                    area=area,
                    confidence=0.5,
                    weight=0.7,
                )
                p.source = "behavior_import"
                profiles.append(p)

        for item in orders:
            area = item.get("area")
            if area and area not in seen_areas:
                seen_areas.add(area)
                p = AreaPreference(
                    user_id=user_id,
                    area=area,
                    confidence=0.4,
                    weight=0.6,
                )
                p.source = "behavior_import"
                profiles.append(p)

        # ── BudgetPreference (only from orders) ───────────────────────
        prices = [
            o["price"]
            for o in orders
            if isinstance(o.get("price"), (int, float)) and o["price"] > 0
        ]
        if prices:
            avg_price = sum(prices) / len(prices)
            bp = BudgetPreference(
                user_id=user_id,
                range_min=max(0, int(avg_price * 0.7)),
                range_max=int(avg_price * 1.3),
                confidence=0.5,
                type="per_person",
            )
            bp.source = "behavior_import"
            profiles.append(bp)

        return profiles

    async def run_behavior_import(self, user_id: str) -> int:
        """Run the full cold-start import pipeline for *user_id*.

        1. Fetch behavior data from the Java backend.
        2. Convert it into profile atoms.
        3. Write each atom to Neo4j, skipping failures per-profile.
        4. Return the total number of profiles successfully written.

        Returns 0 when the Neo4j client is not configured.
        """
        if self._neo4j is None:
            logger.warning("Neo4j client not configured — skipping behavior import")
            return 0

        behavior_data = await self.fetch_behavior_data(user_id)
        profiles = self.build_profiles_from_behavior(user_id, behavior_data)

        count = 0
        for profile in profiles:
            try:
                await self._neo4j.write_profile(user_id, profile)
                count += 1
            except Exception:
                logger.exception(
                    "Failed to write %s for user %s",
                    type(profile).__name__,
                    user_id,
                )

        logger.info(
            "Cold start: imported %d/%d profiles for user %s",
            count,
            len(profiles),
            user_id,
        )
        return count
