# src/storage/neo4j_client.py
"""Neo4j client for profile atoms and entity graph operations.

Handles:
- Profile CRUD (write, read, update, delete)
- Entity graph (User, Shop, Area, Category nodes + relationships)
- Reference nodes (EventRef, SessionRef, AgentCaseRef)
- Subgraph traversal for entity boost (used by Plan C)
- Hard constraint retrieval (used by Plan C)
"""

import logging
from typing import Any
from neo4j import AsyncGraphDatabase, AsyncDriver

from src.storage.models import (
    TastePreference,
    DietaryPreference,
    BudgetPreference,
    CuisinePreference,
    AreaPreference,
    ScenePreference,
    ConstraintPreference,
    AnyProfile,
)

logger = logging.getLogger("pick.storage.neo4j")

# ── Node type → Python class mapping ─────────────────────────────────

NODE_TYPE_MAP = {
    "TastePreference": TastePreference,
    "DietaryPreference": DietaryPreference,
    "BudgetPreference": BudgetPreference,
    "CuisinePreference": CuisinePreference,
    "AreaPreference": AreaPreference,
    "ScenePreference": ScenePreference,
    "ConstraintPreference": ConstraintPreference,
}

RELATIONSHIP_MAP = {
    "TastePreference": "PREFERS_TASTE",
    "DietaryPreference": "PREFERS_DIETARY",
    "BudgetPreference": "HAS_BUDGET",
    "CuisinePreference": "PREFERS_CUISINE",
    "AreaPreference": "PREFERS_AREA",
    "ScenePreference": "PREFERS_SCENE",
    "ConstraintPreference": "HAS_CONSTRAINT",
}


class Neo4jClient:
    """Async Neo4j client for agent memory graph operations."""

    def __init__(self, uri: str, user: str, password: str):
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: AsyncDriver | None = None

    async def connect(self):
        """Initialize the driver and verify connectivity."""
        self._driver = AsyncGraphDatabase.driver(
            self._uri,
            auth=(self._user, self._password),
        )
        await self._driver.verify_connectivity()
        logger.info("Neo4j connected: %s", self._uri)

    async def close(self):
        if self._driver:
            await self._driver.close()

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("Neo4jClient not connected. Call connect() first.")
        return self._driver

    # ── Profile CRUD ──────────────────────────────────────────────

    async def write_profile(self, user_id: str, profile: AnyProfile) -> str:
        """Create or merge a User node + Profile atom node + relationship.

        Returns the profile node's elementId.
        """
        node_type = profile.node_type()
        rel_type = RELATIONSHIP_MAP[node_type]

        # Convert dataclass to dict, excluding None values and Python internals
        props = _profile_to_neo4j_props(profile)
        props["user_id"] = user_id

        query = f"""
        MERGE (u:User {{user_id: $user_id}})
        CREATE (p:{node_type} $props)
        CREATE (u)-[:{rel_type}]->(p)
        RETURN elementId(p) AS profile_id
        """
        async with self.driver.session() as session:
            result = await session.run(query, user_id=user_id, props=props)
            record = await result.single()
            return record["profile_id"] if record else ""

    async def read_profiles(
        self, user_id: str, types: list[str] | None = None
    ) -> list[AnyProfile]:
        """Read all active profiles for a user, optionally filtered by type.

        Excludes expired profiles and those with confidence < 0.3.
        """
        if types is None:
            types = list(NODE_TYPE_MAP.keys())

        results = []
        for nt in types:
            rel_type = RELATIONSHIP_MAP.get(nt)
            if rel_type is None:
                continue
            query = f"""
            MATCH (u:User {{user_id: $user_id}})-[:{rel_type}]->(p:{nt})
            WHERE p.confidence >= 0.3
              AND (p.expires_at IS NULL OR p.expires_at > timestamp() / 1000)
            RETURN p, elementId(p) AS element_id
            """
            async with self.driver.session() as session:
                cursor = await session.run(query, user_id=user_id)
                async for record in cursor:
                    node = record["p"]
                    elem_id = record["element_id"]
                    profile = _neo4j_node_to_profile(nt, dict(node), element_id=elem_id)
                    if profile:
                        results.append(profile)
        return results

    async def update_profile(self, profile_id: str, updates: dict) -> None:
        """Update properties on an existing profile node by elementId."""
        set_clauses = ", ".join(f"p.{k} = ${k}" for k in updates)
        query = f"""
        MATCH (p) WHERE elementId(p) = $profile_id
        SET {set_clauses}, p.updated_at = timestamp() / 1000
        """
        async with self.driver.session() as session:
            await session.run(query, profile_id=profile_id, **updates)

    async def delete_profile(self, profile_id: str) -> None:
        """Delete a profile node and its relationships by elementId."""
        query = """
        MATCH (p) WHERE elementId(p) = $profile_id
        DETACH DELETE p
        """
        async with self.driver.session() as session:
            await session.run(query, profile_id=profile_id)

    async def get_hard_constraints(self, user_id: str) -> list[AnyProfile]:
        """Get all hard constraints (is_hard=true) for a user.

        These are always injected into the system prompt, never decayed.
        Includes DietaryPreference (always hard) and any other is_hard atoms.
        """
        results = []
        # DietaryPreference are always hard
        query = """
        MATCH (u:User {user_id: $user_id})-[:PREFERS_DIETARY]->(dp:DietaryPreference)
        WHERE dp.confidence >= 0.3
        RETURN dp, elementId(dp) AS element_id
        """
        async with self.driver.session() as session:
            cursor = await session.run(query, user_id=user_id)
            async for record in cursor:
                profile = _neo4j_node_to_profile("DietaryPreference", dict(record["dp"]), element_id=record["element_id"])
                if profile:
                    results.append(profile)

        # Any other profile with is_hard=true
        for nt in ["TastePreference", "ConstraintPreference"]:
            rel = RELATIONSHIP_MAP[nt]
            query = f"""
            MATCH (u:User {{user_id: $user_id}})-[:{rel}]->(p:{nt})
            WHERE p.is_hard = true AND p.confidence >= 0.3
            RETURN p, elementId(p) AS element_id
            """
            async with self.driver.session() as session:
                cursor = await session.run(query, user_id=user_id)
                async for record in cursor:
                    profile = _neo4j_node_to_profile(nt, dict(record["p"]), element_id=record["element_id"])
                    if profile:
                        results.append(profile)

        return results

    # ── Entity Graph / Subgraph Traversal ──────────────────────────

    async def subgraph_search(
        self,
        user_id: str,
        entities: dict,
        limit: int = 20,
    ) -> list[dict]:
        """Traverse the entity graph for entity-boosted retrieval.

        ``entities`` is a dict with optional keys:
          areas: list[str], cuisines: list[str], shop_ids: list[str]

        Returns list of {memory_id, boost_score, memory_type} dicts.
        Used by Plan C's EntityBoost module.
        """
        areas = entities.get("areas", [])
        cuisines = entities.get("cuisines", [])
        shop_ids = entities.get("shop_ids", [])

        # Build dynamic WHERE clauses
        where_clauses = []
        params: dict[str, Any] = {"user_id": user_id, "limit": limit}

        if areas:
            where_clauses.append("ap.area IN $areas")
            params["areas"] = areas
        if cuisines:
            where_clauses.append("cp.cuisine IN $cuisines")
            params["cuisines"] = cuisines

        where_str = " OR ".join(where_clauses) if where_clauses else "TRUE"

        query = f"""
        MATCH (u:User {{user_id: $user_id}})
        OPTIONAL MATCH (u)-[:PREFERS_AREA]->(ap:AreaPreference)
          WHERE ap.confidence >= 0.3
        OPTIONAL MATCH (u)-[:PREFERS_CUISINE]->(cp:CuisinePreference)
          WHERE cp.confidence >= 0.3
        OPTIONAL MATCH (u)-[:PREFERS_DIETARY]->(dp:DietaryPreference)
          WHERE dp.confidence >= 0.3
        OPTIONAL MATCH (u)-[:PERFORMED]->(er:EventRef)
        OPTIONAL MATCH (er)-[:TARGETED]->(target)
        WHERE {where_str}
        RETURN
          ap.area AS matched_area,
          cp.cuisine AS matched_cuisine,
          dp.constraint AS matched_dietary,
          er.event_id AS event_id,
          coalesce(ap.confidence, 0) * coalesce(ap.weight, 0.5) AS area_boost,
          coalesce(cp.confidence, 0) * coalesce(cp.weight, 0.5) AS cuisine_boost,
          coalesce(dp.confidence, 0) AS dietary_boost
        LIMIT $limit
        """
        results = []
        async with self.driver.session() as session:
            cursor = await session.run(query, **params)
            async for record in cursor:
                data = dict(record)
                boost = max(
                    data.get("area_boost") or 0,
                    data.get("cuisine_boost") or 0,
                    data.get("dietary_boost") or 0,
                )
                results.append({
                    "event_id": data.get("event_id"),
                    "matched_area": data.get("matched_area"),
                    "matched_cuisine": data.get("matched_cuisine"),
                    "matched_dietary": data.get("matched_dietary"),
                    "boost_score": round(boost, 4),
                })
        return results

    # ── Reference Node Management ──────────────────────────────────

    async def write_event_ref(
        self, user_id: str, event_id: str, targets: list[dict]
    ) -> None:
        """Create an EventRef node and link it to User + target entities.

        targets: list of {type: "Shop"|"Area"|"Category", id: str}
        """
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (u:User {user_id: $user_id})
                MERGE (er:EventRef {event_id: $event_id})
                SET er.user_id = $user_id
                MERGE (u)-[:PERFORMED]->(er)
                """,
                user_id=user_id,
                event_id=event_id,
            )
            for target in targets:
                target_type = target["type"]
                target_id = target["id"]
                await session.run(
                    f"""
                    MATCH (er:EventRef {{event_id: $event_id}})
                    MATCH (t:{target_type} {{{target_type.lower()}_id: $target_id}})
                    MERGE (er)-[:TARGETED]->(t)
                    """,
                    event_id=event_id,
                    target_id=target_id,
                )

    async def write_session_ref(
        self,
        user_id: str,
        session_id: str,
        shop_ids: list[str],
        parent_thread_id: str | None = None,
    ) -> None:
        """Create a SessionRef node and link to mentioned shops.

        Args:
            parent_thread_id: Reserved for Supervisor + Worker multi-agent
                (Phase 15+). Worker sub-task session_ref points to the
                Supervisor's session_id. Currently always None.
        """
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (u:User {user_id: $user_id})
                MERGE (sr:SessionRef {session_id: $session_id})
                SET sr.user_id = $user_id, sr.parent_thread_id = $parent_thread_id
                MERGE (u)-[:HAS_SESSION]->(sr)
                """,
                user_id=user_id,
                session_id=session_id,
                parent_thread_id=parent_thread_id,
            )
            for shop_id in shop_ids:
                await session.run(
                    """
                    MATCH (sr:SessionRef {session_id: $session_id})
                    MERGE (s:Shop {shop_id: $shop_id})
                    MERGE (sr)-[:MENTIONED]->(s)
                    """,
                    session_id=session_id,
                    shop_id=shop_id,
                )

    async def write_agent_case_ref(
        self, user_id: str, case_id: str, involved: list[dict]
    ) -> None:
        """Create an AgentCaseRef node."""
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (u:User {user_id: $user_id})
                MERGE (ac:AgentCaseRef {case_id: $case_id})
                MERGE (u)-[:HAS_EXPERIENCE]->(ac)
                """,
                user_id=user_id,
                case_id=case_id,
            )

    # ── Entity Sync Helpers ────────────────────────────────────────

    async def upsert_shop(self, shop: dict) -> None:
        """Upsert a Shop node from sync data."""
        query = """
        MERGE (s:Shop {shop_id: $shop_id})
        SET s.name = $name, s.type = $type, s.sub_type = $sub_type,
            s.area = $area, s.address = $address,
            s.longitude = $longitude, s.latitude = $latitude,
            s.avg_price = $avg_price, s.score = $score
        """
        async with self.driver.session() as session:
            await session.run(query, **shop)

    async def upsert_area(self, name: str) -> None:
        """Upsert an Area node."""
        async with self.driver.session() as session:
            await session.run(
                "MERGE (a:Area {name: $name})", name=name
            )

    async def upsert_category(self, cat: dict) -> None:
        """Upsert a Category node with parent relationship."""
        async with self.driver.session() as session:
            await session.run(
                """
                MERGE (c:Category {category_id: $category_id})
                SET c.name = $name
                """,
                category_id=cat["category_id"],
                name=cat["name"],
            )
            if cat.get("parent_id"):
                await session.run(
                    """
                    MATCH (c:Category {category_id: $category_id})
                    MATCH (p:Category {category_id: $parent_id})
                    MERGE (c)-[:CHILD_OF]->(p)
                    """,
                    category_id=cat["category_id"],
                    parent_id=cat["parent_id"],
                )

    async def link_shop_area(self, shop_id: str, area_name: str) -> None:
        """Link a Shop to its Area."""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (s:Shop {shop_id: $shop_id})
                MERGE (a:Area {name: $area_name})
                MERGE (s)-[:LOCATED_IN]->(a)
                """,
                shop_id=shop_id,
                area_name=area_name,
            )

    async def link_shop_category(self, shop_id: str, category_id: str) -> None:
        """Link a Shop to its primary Category."""
        async with self.driver.session() as session:
            await session.run(
                """
                MATCH (s:Shop {shop_id: $shop_id})
                MATCH (c:Category {category_id: $category_id})
                MERGE (s)-[:HAS_CATEGORY]->(c)
                """,
                shop_id=shop_id,
                category_id=category_id,
            )

    # ── Trace → Profiles ───────────────────────────────────────────

    async def get_profiles_by_trace(self, trace_id: str) -> list["ProfileRef"]:
        """Find all profile atoms linked to the User who performed the given trace.

        Resolves ``trace_id`` → ``EventRef`` → ``User`` → all profile nodes.
        Returns lightweight ``ProfileRef`` objects with ``.id``, ``.confidence``,
        and ``.reinforce_count`` attributes.

        Args:
            trace_id: The event/trace ID (maps to EventRef.event_id).

        Returns:
            List of ProfileRef objects (empty if trace cannot be resolved).
        """
        rel_types = list(RELATIONSHIP_MAP.values())
        query = """
        MATCH (er:EventRef {event_id: $trace_id})<-[:PERFORMED]-(u:User)
        MATCH (u)-[rel]->(p)
        WHERE type(rel) IN $rel_types
        RETURN elementId(p) AS id,
               coalesce(p.confidence, 0.0) AS confidence,
               coalesce(p.reinforce_count, 0) AS reinforce_count
        """
        async with self.driver.session() as session:
            cursor = await session.run(query, trace_id=trace_id, rel_types=rel_types)
            results: list[ProfileRef] = []
            async for record in cursor:
                results.append(ProfileRef(**dict(record)))
            return results


# ── Internal Helpers ──────────────────────────────────────────────────


class ProfileRef:
    """Lightweight reference to a user profile atom in Neo4j.

    Returned by :meth:`Neo4jClient.get_profiles_by_trace` — carries only
    the fields needed by FeedbackConsumer.
    """

    __slots__ = ("id", "confidence", "reinforce_count")

    def __init__(self, id: str, confidence: float = 0.0, reinforce_count: int = 0):
        self.id = id
        self.confidence = confidence
        self.reinforce_count = reinforce_count

    def __repr__(self) -> str:
        return (
            f"ProfileRef(id={self.id!r}, confidence={self.confidence}, "
            f"reinforce_count={self.reinforce_count})"
        )


def _profile_to_neo4j_props(profile: AnyProfile) -> dict:
    """Convert a ProfileAtom dataclass to a Neo4j-safe properties dict.

    Skips None values and Python-internal fields.
    """
    from dataclasses import fields

    skip = {"user_id"}  # user_id is passed separately
    props = {}
    for f in fields(profile):
        if f.name in skip:
            continue
        value = getattr(profile, f.name)
        if value is not None:
            # Convert bool to Neo4j boolean
            if isinstance(value, bool):
                props[f.name] = value
            elif isinstance(value, (int, float, str)):
                props[f.name] = value
            elif isinstance(value, list):
                # Lists aren't used in Profile atoms currently
                pass
    return props


def _neo4j_node_to_profile(node_type: str, props: dict, element_id: str = "") -> AnyProfile | None:
    """Convert a Neo4j node properties dict to a ProfileAtom instance.

    Args:
        node_type: The Neo4j node label.
        props: Dict of node properties.
        element_id: The Neo4j elementId (not a property on the node — passed separately).
    """
    cls = NODE_TYPE_MAP.get(node_type)
    if cls is None:
        return None

    # Filter to only fields that exist on the dataclass
    from dataclasses import fields as dc_fields
    valid_keys = {f.name for f in dc_fields(cls)}
    filtered = {k: v for k, v in props.items() if k in valid_keys}
    # Inject element_id so cleanup/consolidation can delete by elementId
    if "element_id" in valid_keys and element_id:
        filtered["element_id"] = element_id
    return cls(**filtered)
