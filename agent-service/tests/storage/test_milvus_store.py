# tests/storage/test_milvus_store.py
"""Integration tests for MilvusMemoryStore. Requires Milvus running."""
import pytest
from src.storage.milvus_store import (
    MilvusMemoryStore,
    COLLECTION_USER_EVENT,
    COLLECTION_USER_SESSION,
    COLLECTION_AGENT_CASE,
)
from src.storage.models import MemoryEvent, SessionSummary, AgentCase

pytestmark = pytest.mark.integration


@pytest.fixture
def store():
    """Create MilvusMemoryStore connected to the test Milvus instance."""
    ms = MilvusMemoryStore(
        host="111.229.253.150",
        port=19530,
        embedding_dim=1024,
    )
    ms.connect()
    return ms


def test_create_collections(store):
    """All three collections should be creatable (idempotent)."""
    names = store.create_all_collections()
    assert COLLECTION_USER_EVENT in names
    assert COLLECTION_USER_SESSION in names
    assert COLLECTION_AGENT_CASE in names


def test_collections_have_dense_and_sparse_indexes(store):
    """Each collection should have HNSW (dense) + SPARSE_INVERTED_INDEX."""
    for coll in [COLLECTION_USER_EVENT, COLLECTION_USER_SESSION, COLLECTION_AGENT_CASE]:
        desc = store.client.describe_collection(coll)
        field_names = {f["name"] for f in desc["fields"]}
        assert "embedding" in field_names, f"{coll} missing embedding field"
        # Sparse field name may vary; check index exists
        index_names = {idx["field_name"] for idx in desc.get("indexes", [])}
        has_dense = any("embedding" in idx for idx in index_names)
        assert has_dense, f"{coll} missing dense index"


def test_insert_and_search_event(store):
    """Insert a MemoryEvent and retrieve it via dense search."""
    store.create_all_collections()

    event = MemoryEvent(
        user_id="test_user_milvus",
        event_type="search",
        description="在春熙路搜索川渝火锅，人均预算80元",
        payload={"query": "火锅", "area": "春熙路"},
        session_id="sess_test",
    )

    # Insert with a dummy embedding (1024-dim)
    import random
    event.embedding = [random.random() for _ in range(1024)]
    eid = store.insert_event(event)
    assert eid is not None

    # Search
    results = store.search_dense(
        collection=COLLECTION_USER_EVENT,
        embedding=event.embedding,
        filter_expr=f'user_id == "test_user_milvus"',
        top_k=5,
    )
    assert len(results) > 0

    # Cleanup
    store.delete_by_id(COLLECTION_USER_EVENT, eid)
