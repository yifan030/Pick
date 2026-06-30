# src/sync/entity_sync.py
"""One-time entity graph seeder: syncs Shop, Area, Category from MySQL → Neo4j.

Uses the existing Java sync endpoints (GET /api/sync/shops, etc.).
Also syncs ShopType (category) data from the Java API.
"""

import logging
import httpx
from src.storage.neo4j_client import Neo4jClient

logger = logging.getLogger("pick.sync.entity_sync")

# ── Config ────────────────────────────────────────────────────────────

JAVA_BASE_URL = "http://localhost:8085"
SYNC_TOKEN = "internal-dev-token"


async def sync_all_entities(neo4j: Neo4jClient, java_base_url: str = JAVA_BASE_URL) -> dict:
    """Run full entity graph sync. Returns counts of synced entities."""
    counts = {}

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Sync shops (includes area and category info from JOIN)
        counts["shops"] = await _sync_shops(neo4j, client, java_base_url)

        # 2. Derive distinct areas from shops (area is a string field)
        counts["areas"] = await _sync_areas(neo4j, client, java_base_url)

        # 3. Sync categories from ShopType (need a new endpoint or extract from shops)
        counts["categories"] = await _sync_categories_from_shops(neo4j, client, java_base_url)

    return counts


async def _sync_shops(neo4j: Neo4jClient, client: httpx.AsyncClient, base_url: str) -> int:
    """Fetch all shops from Java sync endpoint and upsert to Neo4j."""
    count = 0
    headers = {"X-Internal-Token": SYNC_TOKEN}

    try:
        resp = await client.get(f"{base_url}/api/sync/shops", params={"since": 0}, headers=headers)
        resp.raise_for_status()
        shops = resp.json()
    except Exception:
        logger.exception("Failed to fetch shops from Java")
        return 0

    for shop in shops:
        try:
            shop_data = {
                "shop_id": str(shop["shopId"]),
                "name": shop.get("name", ""),
                "type": shop.get("type", ""),
                "sub_type": shop.get("subType", ""),
                "area": shop.get("area", ""),
                "address": shop.get("address", ""),
                "longitude": shop.get("longitude") or 0.0,
                "latitude": shop.get("latitude") or 0.0,
                "avg_price": shop.get("avgPrice") or 0,
                "score": shop.get("score") or 0,
            }
            await neo4j.upsert_shop(shop_data)

            # Link to Area
            if shop_data["area"]:
                await neo4j.upsert_area(shop_data["area"])
                await neo4j.link_shop_area(shop_data["shop_id"], shop_data["area"])

            count += 1
        except Exception:
            logger.exception("Failed to sync shop %s", shop.get("shopId"))

    logger.info("Synced %d shops to Neo4j", count)
    return count


async def _sync_areas(neo4j: Neo4jClient, client: httpx.AsyncClient, base_url: str) -> int:
    """Extract distinct areas from the shop list and create Area nodes.

    Since area is just a string field on Shop (not a separate table),
    we derive distinct area names from the shop data.
    """
    headers = {"X-Internal-Token": SYNC_TOKEN}
    try:
        resp = await client.get(f"{base_url}/api/sync/shops", params={"since": 0}, headers=headers)
        resp.raise_for_status()
        shops = resp.json()
    except Exception:
        logger.exception("Failed to fetch shops for area extraction")
        return 0

    areas = {shop.get("area") for shop in shops if shop.get("area")}
    for area_name in areas:
        await neo4j.upsert_area(area_name)
    logger.info("Synced %d areas to Neo4j", len(areas))
    return len(areas)


async def _sync_categories_from_shops(neo4j: Neo4jClient, client: httpx.AsyncClient, base_url: str) -> int:
    """Extract category hierarchy from shop data (type + subType).

    The Shop sync already JOINs ShopType to get type (parent) and subType (child).
    We extract distinct pairs from the shop list to build the Category tree.
    """
    headers = {"X-Internal-Token": SYNC_TOKEN}
    try:
        resp = await client.get(f"{base_url}/api/sync/shops", params={"since": 0}, headers=headers)
        resp.raise_for_status()
        shops = resp.json()
    except Exception:
        logger.exception("Failed to fetch shops for category extraction")
        return 0

    # Collect type → subType pairs
    cat_pairs = set()
    for shop in shops:
        main_type = shop.get("type", "")
        sub_type = shop.get("subType", "")
        if main_type and sub_type:
            cat_pairs.add((main_type, sub_type))

    # Assign synthetic IDs since ShopType IDs aren't in the sync DTO
    cat_id = 0
    parent_ids = {}  # name → id
    count = 0
    for main_type, sub_type in sorted(cat_pairs):
        # Ensure parent category exists
        if main_type not in parent_ids:
            cat_id += 1
            parent_ids[main_type] = cat_id
            await neo4j.upsert_category({
                "category_id": str(cat_id),
                "name": main_type,
                "parent_id": None,
            })
            count += 1

        # Create child category
        cat_id += 1
        await neo4j.upsert_category({
            "category_id": str(cat_id),
            "name": sub_type,
            "parent_id": str(parent_ids[main_type]),
        })
        count += 1

    logger.info("Synced %d categories to Neo4j", count)
    return count
