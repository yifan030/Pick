"""User note (blog) sync: fetch from Java → embed → upsert to Milvus.

Pulls blog/exploration-note data via Java sync API, generates text embeddings,
and upserts into the ``collection_user_note`` Milvus collection.
"""

import os
from collections.abc import Callable
from typing import Any

import httpx
from pymilvus import MilvusClient

from src.agent.services.java_client import get_java_client, retry_on_server_error
from src.storage.milvus_store import COLLECTION_USER_NOTE, EMBEDDING_DIM, HNSW_PARAMS
from src.storage.embedding import embed_texts as _default_embed_texts
from src.storage.sync_cursor import SyncCursor

BATCH_SIZE = 50
CONTENT_TYPE = "user_note"


def build_embedding_text(blog: dict) -> str:
    title = blog.get("title") or ""
    content = blog.get("content") or ""
    return f"{title}\n{content}".strip()


def to_milvus_row(blog: dict, embedding: list[float]) -> dict[str, Any]:
    return {
        "id": f"note_{blog['blogId']}",
        "embedding": embedding,
        "shop_id": blog["shopId"],
        "user_nickname": blog.get("userNickname") or "",
        "content_type": CONTENT_TYPE,
    }


@retry_on_server_error()
def fetch_blogs_from_java(since: int = 0) -> list[dict]:
    """Fetch blogs from Java sync API. Uses shared connection pool."""
    client = get_java_client(timeout=60.0)
    response = client.get("/api/sync/blogs", params={"since": since})
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"Blog sync failed: {body}")
    return body.get("data") or []


def run_full_sync(
    *,
    milvus_client: MilvusClient,
    embedding_dim: int,
    fetch_blogs: Callable[[int], list[dict]],
    embed_texts: Callable[[list[str]], list[list[float]]] | None = None,
) -> int:
    if embed_texts is None:
        embed_texts = _default_embed_texts

    blogs = fetch_blogs(0)
    if not blogs:
        return 0

    texts = [build_embedding_text(blog) for blog in blogs]
    embeddings = embed_texts(texts)
    if len(embeddings) != len(blogs):
        raise RuntimeError("Embedding count does not match blog count")
    for vector in embeddings:
        if len(vector) != embedding_dim:
            raise ValueError(
                f"Expected embedding dim {embedding_dim}, got {len(vector)}"
            )

    rows = [to_milvus_row(blog, vector) for blog, vector in zip(blogs, embeddings)]
    for i in range(0, len(rows), BATCH_SIZE):
        milvus_client.upsert(collection_name=COLLECTION_USER_NOTE, data=rows[i : i + BATCH_SIZE])
    return len(rows)


def _init_product_milvus(host: str, port: int, dim: int) -> MilvusClient:
    """Create a MilvusClient and ensure product collections exist."""
    client = MilvusClient(uri=f"http://{host}:{port}")

    for name, schema_builder in [
        (COLLECTION_USER_NOTE, _make_user_note_schema),
    ]:
        if client.has_collection(name):
            continue
        schema = schema_builder(dim)
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="HNSW",
            metric_type="COSINE",
            params=HNSW_PARAMS,
        )
        client.create_collection(
            collection_name=name,
            schema=schema,
            index_params=index_params,
        )

    return client


def _make_user_note_schema(dim: int):
    from pymilvus import DataType
    schema = MilvusClient.create_schema()
    schema.add_field("id", DataType.VARCHAR, max_length=128, is_primary=True)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("shop_id", DataType.INT64)
    schema.add_field("user_nickname", DataType.VARCHAR, max_length=256)
    schema.add_field("content_type", DataType.VARCHAR, max_length=64)
    return schema


def run_full_user_note_sync(
    *,
    milvus_host: str | None = None,
    milvus_port: int | None = None,
    embedding_dim: int | None = None,
    full_resync: bool = False,
) -> int:
    """Run user note sync (incremental by default).

    Uses SyncCursor to track the last successful sync timestamp.  Only blogs
    modified since the last run are fetched.  Pass ``full_resync=True`` to
    re-sync everything.

    Returns the number of blogs synced.
    """
    milvus_host = milvus_host or os.environ.get("MILVUS_HOST", "localhost")
    milvus_port = milvus_port or int(os.environ.get("MILVUS_PORT", "19530"))
    embedding_dim = embedding_dim or int(os.environ.get("EMBEDDING_DIM", "1024"))

    cursor = SyncCursor("user_note")
    since = 0 if full_resync else cursor.last_synced_at

    milvus_client = _init_product_milvus(host=milvus_host, port=milvus_port, dim=embedding_dim)
    count = run_full_sync(
        milvus_client=milvus_client,
        embedding_dim=embedding_dim,
        fetch_blogs=lambda s: fetch_blogs_from_java(since=s),
        embed_texts=_default_embed_texts,
    )

    if count > 0:
        cursor.update()

    return count


if __name__ == "__main__":
    synced = run_full_user_note_sync()
    print(f"synced {synced} blogs to {COLLECTION_USER_NOTE}")
