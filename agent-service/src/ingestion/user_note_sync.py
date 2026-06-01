import os
from collections.abc import Callable
from typing import Any

import httpx
from pymilvus import MilvusClient

from milvus import USER_NOTE

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


def fetch_blogs_from_java(
    since: int = 0,
    *,
    base_url: str | None = None,
    internal_token: str | None = None,
    http_client: httpx.Client | None = None,
) -> list[dict]:
    base_url = base_url or os.environ.get("JAVA_API_BASE_URL", "http://localhost:8085")
    internal_token = internal_token or os.environ.get("SYNC_INTERNAL_TOKEN", "")
    url = f"{base_url.rstrip('/')}/api/sync/blogs"
    headers = {"X-Internal-Token": internal_token}
    params = {"since": since}

    if http_client is not None:
        response = http_client.get(url, headers=headers, params=params)
    else:
        with httpx.Client(timeout=60.0) as client:
            response = client.get(url, headers=headers, params=params)
    response.raise_for_status()
    body = response.json()
    if not body.get("success"):
        raise RuntimeError(f"Blog sync failed: {body}")
    return body.get("data") or []


def run_full_sync(
    *,
    milvus_client: MilvusClient,
    embedding_dim: int,
    fetch_blogs: Callable[[int], list[dict]] | None = None,
    embed_texts: Callable[[list[str]], list[list[float]]] | None = None,
    java_base_url: str | None = None,
    internal_token: str | None = None,
) -> int:
    from ingestion.embedding import embed_texts as default_embed_texts

    if fetch_blogs is None:
        fetch_blogs = lambda since: fetch_blogs_from_java(
            since, base_url=java_base_url, internal_token=internal_token
        )
    if embed_texts is None:
        embed_texts = default_embed_texts

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
        milvus_client.upsert(collection_name=USER_NOTE, data=rows[i : i + BATCH_SIZE])
    return len(rows)


def run_full_user_note_sync(
    *,
    java_base_url: str | None = None,
    internal_token: str | None = None,
    milvus_host: str | None = None,
    milvus_port: int | None = None,
    embedding_dim: int | None = None,
) -> int:
    java_base_url = java_base_url or os.environ["JAVA_BASE_URL"]
    internal_token = internal_token or os.environ["SYNC_INTERNAL_TOKEN"]
    milvus_host = milvus_host or os.environ.get("MILVUS_HOST", "localhost")
    milvus_port = milvus_port or int(os.environ.get("MILVUS_PORT", "19530"))
    embedding_dim = embedding_dim or int(os.environ.get("EMBEDDING_DIM", "1024"))

    from milvus import init

    milvus_client = init(embedding_dim, host=milvus_host, port=milvus_port)
    return run_full_sync(
        milvus_client=milvus_client,
        embedding_dim=embedding_dim,
        java_base_url=java_base_url,
        internal_token=internal_token,
    )


if __name__ == "__main__":
    synced = run_full_user_note_sync()
    print(f"synced {synced} blogs to {USER_NOTE}")
