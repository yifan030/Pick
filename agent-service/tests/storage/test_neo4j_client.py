# tests/storage/test_neo4j_client.py
"""Integration tests for Neo4jClient. Requires Neo4j running via Docker."""
import pytest
import asyncio
from src.storage.neo4j_client import Neo4jClient
from src.storage.models import (
    TastePreference, CuisinePreference, DietaryPreference,
)

pytestmark = pytest.mark.integration


@pytest.fixture
async def neo4j():
    """Create a Neo4jClient connected to the test instance."""
    client = Neo4jClient(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="pick-neo4j-dev",
    )
    await client.connect()
    yield client
    await client.close()


@pytest.mark.asyncio
async def test_write_and_read_taste_preference(neo4j):
    """Write a TastePreference then read it back."""
    user_id = "test_user_1"
    tp = TastePreference(
        user_id=user_id,
        property="spicy",
        value="avoid",
        confidence=0.9,
        reinforce_count=3,
    )

    # Write
    profile_id = await neo4j.write_profile(user_id, tp)
    assert profile_id is not None

    # Read back
    profiles = await neo4j.read_profiles(user_id, types=["TastePreference"])
    assert len(profiles) >= 1
    found = [p for p in profiles if p.property == "spicy"]
    assert len(found) == 1
    assert found[0].value == "avoid"
    assert found[0].confidence == 0.9
    assert found[0].reinforce_count == 3

    # Cleanup
    await neo4j.delete_profile(profile_id)


@pytest.mark.asyncio
async def test_update_profile_confidence(neo4j):
    """Update a profile's confidence after REINFORCE."""
    user_id = "test_user_2"
    tp = TastePreference(user_id=user_id, property="sweet", value="like", confidence=0.6)

    profile_id = await neo4j.write_profile(user_id, tp)

    # Update
    await neo4j.update_profile(profile_id, {"confidence": 0.7, "reinforce_count": 1})

    profiles = await neo4j.read_profiles(user_id, types=["TastePreference"])
    found = [p for p in profiles if p.property == "sweet"]
    assert found[0].confidence == 0.7
    assert found[0].reinforce_count == 1

    await neo4j.delete_profile(profile_id)


@pytest.mark.asyncio
async def test_hard_constraints_always_returned(neo4j):
    """get_hard_constraints should return DietaryPreferences."""
    user_id = "test_user_3"
    dp = DietaryPreference(user_id=user_id, constraint="清真", type="religious")

    pid = await neo4j.write_profile(user_id, dp)
    hard = await neo4j.get_hard_constraints(user_id)
    assert len(hard) >= 1
    assert any(p.constraint == "清真" for p in hard)

    await neo4j.delete_profile(pid)
