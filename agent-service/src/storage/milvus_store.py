"""Milvus memory store for Event, Session, and AgentCase collections.

Provides:
- Collection creation (idempotent) with HNSW + SPARSE_INVERTED_INDEX
- Insert/upsert operations
- Dense vector search
- Sparse (BM25) vector search
- Delete by ID or filter

Compatible with pymilvus >= 3.0 (CollectionSchema + FieldSchema API).
"""

import logging
import os
import time as _time_module
from pymilvus import MilvusClient, DataType, FieldSchema, CollectionSchema
from pymilvus.milvus_client.index import IndexParams

logger = logging.getLogger("pick.storage.milvus")

# ── Collection Names ──────────────────────────────────────────────────

COLLECTION_USER_EVENT = "user_event"
COLLECTION_USER_SESSION = "user_session"
COLLECTION_AGENT_CASE = "agent_case"

# Product RAG collections (shop descriptions, user blog notes)
COLLECTION_SHOP_DESC = "collection_shop_desc"
COLLECTION_USER_NOTE = "collection_user_note"

ALL_COLLECTIONS = [COLLECTION_USER_EVENT, COLLECTION_USER_SESSION, COLLECTION_AGENT_CASE]
PRODUCT_COLLECTIONS = [COLLECTION_SHOP_DESC, COLLECTION_USER_NOTE]

# ── Embedding Config ──────────────────────────────────────────────────

EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

# Common HNSW index params
HNSW_PARAMS = {"M": 16, "efConstruction": 200}

# ── Collection Schemas ────────────────────────────────────────────────


def _make_event_schema(dim: int) -> list[FieldSchema]:
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="event_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="payload", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="session_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="compressed", dtype=DataType.BOOL),
        FieldSchema(name="compressed_from", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="ttl_seconds", dtype=DataType.INT64),
        FieldSchema(name="expires_at", dtype=DataType.INT64),
        FieldSchema(name="created_at", dtype=DataType.INT64),
    ]


def _make_session_schema(dim: int) -> list[FieldSchema]:
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="key_shops", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="key_areas", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="intent", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="is_complete", dtype=DataType.BOOL),
        FieldSchema(name="created_at", dtype=DataType.INT64),
        FieldSchema(name="updated_at", dtype=DataType.INT64),
    ]


def _make_agent_case_schema(dim: int) -> list[FieldSchema]:
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="user_id", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="case_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="description", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="context", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="action", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="outcome", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="outcome_reason", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="lesson", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="sparse_embedding", dtype=DataType.SPARSE_FLOAT_VECTOR),
        FieldSchema(name="created_at", dtype=DataType.INT64),
        FieldSchema(name="ttl_seconds", dtype=DataType.INT64),
    ]


# ── Index Definitions ─────────────────────────────────────────────────


def _build_index_params(client: MilvusClient) -> IndexParams:
    """Build a combined IndexParams with both dense HNSW and sparse
    inverted index definitions."""
    index_params = client.prepare_index_params()
    # Dense HNSW index
    index_params.add_index(
        field_name="embedding",
        index_type="HNSW",
        metric_type="COSINE",
        params=HNSW_PARAMS,
    )
    # Sparse inverted index
    index_params.add_index(
        field_name="sparse_embedding",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="IP",  # Inner Product for sparse
        params={"drop_ratio_build": 0.2},
    )
    return index_params


def _build_product_index_params(client: MilvusClient) -> IndexParams:
    """Build IndexParams for product RAG collections (dense HNSW only)."""
    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="embedding",
        index_type="HNSW",
        metric_type="COSINE",
        params=HNSW_PARAMS,
    )
    return index_params


# ── Store Class ───────────────────────────────────────────────────────


class MilvusMemoryStore:
    """Manages three Milvus collections for agent memory: user_event,
    user_session, agent_case. Each has dense (HNSW/COSINE) and sparse
    (INVERTED_INDEX/IP) search capability."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 19530,
        embedding_dim: int = 1024,
    ):
        self._host = host
        self._port = port
        self._dim = embedding_dim
        self.client: MilvusClient | None = None

    def connect(self):
        """Initialize the MilvusClient connection."""
        uri = f"http://{self._host}:{self._port}"
        self.client = MilvusClient(uri=uri)
        logger.info("MilvusMemoryStore connected: %s", uri)

    # ── Collection Management ─────────────────────────────────────

    def create_all_collections(self) -> list[str]:
        """Create all three collections if they don't exist. Idempotent."""
        schemas = {
            COLLECTION_USER_EVENT: _make_event_schema(self._dim),
            COLLECTION_USER_SESSION: _make_session_schema(self._dim),
            COLLECTION_AGENT_CASE: _make_agent_case_schema(self._dim),
        }
        created = []
        for name, fields in schemas.items():
            if self.client.has_collection(name):
                logger.info("Collection %s already exists", name)
                created.append(name)
                continue
            # Build CollectionSchema with pymilvus >= 3.0 API
            collection_schema = CollectionSchema(
                fields=fields,
                enable_dynamic_field=True,
            )
            self.client.create_collection(
                collection_name=name,
                schema=collection_schema,
            )
            # Create both dense HNSW + sparse inverted indexes
            index_params = _build_index_params(self.client)
            self.client.create_index(
                collection_name=name,
                index_params=index_params,
            )
            self.client.load_collection(name)
            logger.info("Created collection %s with HNSW + sparse indexes", name)
            created.append(name)
        return created

    def drop_all_collections(self):
        """Drop all three collections. Use with caution — for testing."""
        for name in ALL_COLLECTIONS:
            if self.client.has_collection(name):
                self.client.drop_collection(name)

    # ── Insert Operations ─────────────────────────────────────────

    def insert_event(self, event) -> str:
        """Insert a MemoryEvent into user_event collection."""
        from src.storage.models import MemoryEvent
        data = event.to_milvus_dict()
        data["id"] = event.id
        data["embedding"] = event.embedding or []
        self.client.insert(
            collection_name=COLLECTION_USER_EVENT,
            data=[data],
        )
        return event.id

    def insert_session(self, session) -> str:
        """Insert or upsert a SessionSummary into user_session."""
        from src.storage.models import SessionSummary
        data = session.to_milvus_dict()
        data["id"] = session.id
        data["embedding"] = session.embedding or []
        self.client.upsert(
            collection_name=COLLECTION_USER_SESSION,
            data=[data],
        )
        return session.id

    def insert_agent_case(self, case) -> str:
        """Insert an AgentCase into agent_case collection."""
        from src.storage.models import AgentCase
        data = case.to_milvus_dict()
        data["id"] = case.id
        data["embedding"] = case.embedding or []
        self.client.insert(
            collection_name=COLLECTION_AGENT_CASE,
            data=[data],
        )
        return case.id

    # ── Search Operations ─────────────────────────────────────────

    def search_dense(
        self,
        collection: str,
        embedding: list[float],
        filter_expr: str,
        top_k: int = 20,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """Dense vector search (HNSW/COSINE)."""
        if output_fields is None:
            output_fields = ["id", "user_id", "description", "created_at"]
        results = self.client.search(
            collection_name=collection,
            data=[embedding],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
        )
        return results[0] if results else []

    def search_sparse(
        self,
        collection: str,
        sparse_vector: dict[int, float],
        filter_expr: str,
        top_k: int = 20,
        output_fields: list[str] | None = None,
    ) -> list[dict]:
        """Sparse vector search (BM25/IP)."""
        if output_fields is None:
            output_fields = ["id", "user_id", "description", "created_at"]
        results = self.client.search(
            collection_name=collection,
            data=[sparse_vector],
            filter=filter_expr,
            limit=top_k,
            output_fields=output_fields,
            search_params={"metric_type": "IP"},
        )
        return results[0] if results else []

    # ── Delete Operations ─────────────────────────────────────────

    def delete_by_id(self, collection: str, entity_id: str) -> None:
        """Delete a single entity by primary key."""
        self.client.delete(
            collection_name=collection,
            filter=f'id == "{entity_id}"',
        )

    def delete_by_filter(self, collection: str, filter_expr: str) -> None:
        """Delete entities matching a filter expression."""
        self.client.delete(
            collection_name=collection,
            filter=filter_expr,
        )

    # ── Product Collection Management ──────────────────────────────

    def create_product_collections(self) -> list[str]:
        """Create product RAG collections (shop_desc, user_note) if absent."""
        schemas = {
            COLLECTION_SHOP_DESC: _make_shop_desc_schema(self._dim),
            COLLECTION_USER_NOTE: _make_user_note_schema(self._dim),
        }
        created = []
        for name, fields in schemas.items():
            if self.client.has_collection(name):
                created.append(name)
                continue
            collection_schema = CollectionSchema(fields=fields)
            self.client.create_collection(
                collection_name=name,
                schema=collection_schema,
            )
            index_params = _build_product_index_params(self.client)
            self.client.create_index(
                collection_name=name,
                index_params=index_params,
            )
            self.client.load_collection(name)
            logger.info("Created product collection %s", name)
            created.append(name)
        return created

    def delete_expired(self, collection: str) -> int:
        """Delete all expired entities. Returns count deleted."""
        now = int(_time_module.time())
        filter_expr = f"expires_at > 0 and expires_at <= {now}"
        # Milvus delete doesn't return count easily; we estimate
        self.client.delete(
            collection_name=collection,
            filter=filter_expr,
        )
        return 0  # Milvus doesn't return delete count


# ── Product Collection Schemas ────────────────────────────────────────


def _make_shop_desc_schema(dim: int) -> list[FieldSchema]:
    """Schema for collection_shop_desc (product RAG)."""
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="shop_id", dtype=DataType.INT64),
        FieldSchema(name="area", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="longitude", dtype=DataType.DOUBLE),
        FieldSchema(name="latitude", dtype=DataType.DOUBLE),
        FieldSchema(name="avg_price", dtype=DataType.INT64),
        FieldSchema(name="type", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="sub_type", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="score", dtype=DataType.DOUBLE),
        FieldSchema(name="open_hours", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=2048),
        FieldSchema(name="content_type", dtype=DataType.VARCHAR, max_length=64),
    ]


def _make_user_note_schema(dim: int) -> list[FieldSchema]:
    """Schema for collection_user_note (user blog notes RAG)."""
    return [
        FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=128),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="shop_id", dtype=DataType.INT64),
        FieldSchema(name="user_nickname", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="content_type", dtype=DataType.VARCHAR, max_length=64),
    ]
