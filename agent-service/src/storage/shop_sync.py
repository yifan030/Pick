"""Shop description sync: fetch from Java → embed → upsert to Milvus.

Pulls shop data via Java sync API, generates multimodal embeddings (text + images)
via DashScope MultiModalEmbedding API, and upserts into the ``collection_shop_desc``
Milvus collection.
"""

import json
import os
from collections.abc import Callable
from pathlib import Path

import dashscope
from dashscope import (
    MultiModalEmbedding,
    MultiModalEmbeddingItemImage,
    MultiModalEmbeddingItemText,
)
from pymilvus import MilvusClient

from src.agent.services.java_client import get_java_client, retry_on_server_error
from src.storage.milvus_store import COLLECTION_SHOP_DESC, EMBEDDING_DIM, HNSW_PARAMS
from src.storage.sync_cursor import SyncCursor

BATCH_SIZE = 50
CONTENT_TYPE = "shop_description"


def _get_image_urls(shop: dict) -> list[str]:
    """Extract image URLs from shop dict, supporting both old and new formats."""
    images_list = shop.get("imagesList")
    if images_list and isinstance(images_list, list):
        return [img.get("url", "") for img in images_list if img.get("url")]
    images = shop.get("images") or ""
    return [img.strip() for img in images.split(",") if img.strip()]


def build_embedding_text(shop: dict) -> str:
    parts: list[str] = []

    name = shop.get("name")
    if name:
        parts.append(name)

    description = shop.get("description")
    if description:
        parts.append(description)

    tags = _parse_json_list(shop.get("tags"))
    if tags:
        parts.append(", ".join(tags))

    scenes = _parse_json_list(shop.get("recommendedScenes") or shop.get("recommended_scenes"))
    if scenes:
        parts.append(", ".join(scenes))

    return "\n".join(parts)


def build_multimodal_input(
    shop: dict, image_base_path: str | Path = ""
) -> list[MultiModalEmbeddingItemText | MultiModalEmbeddingItemImage]:
    """Build multimodal input items for DashScope MultiModalEmbedding API.

    Returns a list of text and image items. Image items use local file paths
    directly — DashScope SDK handles file upload internally.
    """
    items: list[MultiModalEmbeddingItemText | MultiModalEmbeddingItemImage] = [
        MultiModalEmbeddingItemText(build_embedding_text(shop), factor=1.0)
    ]
    base = Path(image_base_path) if image_base_path else None

    for img_url in _get_image_urls(shop):
        if base is None:
            continue
        path = base / img_url
        if path.is_file():
            items.append(MultiModalEmbeddingItemImage(str(path), factor=1.0))

    return items


def to_milvus_record(shop: dict, embedding: list[float]) -> dict:
    shop_id = shop.get("shopId") or shop.get("shop_id")
    tags = shop.get("tags")
    if isinstance(tags, list):
        tags = json.dumps(tags, ensure_ascii=False)

    return {
        "id": f"shop_desc_{shop_id}",
        "embedding": embedding,
        "shop_id": shop_id,
        "area": shop.get("area") or "",
        "longitude": shop.get("longitude") or 0.0,
        "latitude": shop.get("latitude") or 0.0,
        "avg_price": shop.get("avgPrice") or shop.get("avg_price") or 0,
        "type": shop.get("type") or "",
        "sub_type": shop.get("subType") or shop.get("sub_type") or "",
        "score": float(shop.get("score") or 0),
        "open_hours": shop.get("openHours") or shop.get("open_hours") or "",
        "tags": tags or "",
        "content_type": CONTENT_TYPE,
    }


@retry_on_server_error()
def fetch_shops(since: int = 0) -> list[dict]:
    """Fetch shops from Java sync API. Uses shared connection pool."""
    client = get_java_client(timeout=60.0)
    response = client.get("/api/sync/shops", params={"since": since})
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success", True):
        raise RuntimeError(f"shop sync failed: {payload}")
    return payload.get("data") or []


def embed_shop_multimodal(
    shop: dict,
    *,
    api_key: str,
    model: str,
    image_base_path: str | Path = "",
) -> list[float]:
    """Generate multimodal embedding for a shop via DashScope MultiModalEmbedding."""
    items = build_multimodal_input(shop, image_base_path)
    if not items:
        raise ValueError(f"no multimodal input for shop {shop.get('shopId', shop.get('shop_id', 'unknown'))}")

    dashscope.api_key = api_key
    response = MultiModalEmbedding.call(model=model, input=items)

    if response.status_code != 200:
        raise RuntimeError(
            f"MultiModalEmbedding API error: code={response.code}, message={response.message}"
        )

    output = response.output
    if isinstance(output, dict):
        embeddings = output.get("embeddings", [])
        return embeddings[0].get("embedding", []) if embeddings else []
    return output.embeddings[0].embedding


def sync_shop_desc(
    milvus_client: MilvusClient,
    fetch_shops_fn: Callable[[], list[dict]],
    embed_shop: Callable[[dict], list[float]],
    batch_size: int = BATCH_SIZE,
) -> int:
    shops = fetch_shops_fn()
    if not shops:
        return 0

    records = [to_milvus_record(shop, embed_shop(shop)) for shop in shops]

    for i in range(0, len(records), batch_size):
        milvus_client.upsert(collection_name=COLLECTION_SHOP_DESC, data=records[i : i + batch_size])

    return len(shops)


def _init_product_milvus(host: str, port: int, dim: int) -> MilvusClient:
    """Create a MilvusClient and ensure product collections exist."""
    from src.storage.milvus_store import COLLECTION_SHOP_DESC, COLLECTION_USER_NOTE

    client = MilvusClient(uri=f"http://{host}:{port}")

    for name, schema_builder in [
        (COLLECTION_SHOP_DESC, _make_shop_desc_schema),
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


def _make_shop_desc_schema(dim: int):
    from pymilvus import DataType
    schema = MilvusClient.create_schema()
    schema.add_field("id", DataType.VARCHAR, max_length=128, is_primary=True)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("shop_id", DataType.INT64)
    schema.add_field("area", DataType.VARCHAR, max_length=256)
    schema.add_field("longitude", DataType.DOUBLE)
    schema.add_field("latitude", DataType.DOUBLE)
    schema.add_field("avg_price", DataType.INT64)
    schema.add_field("type", DataType.VARCHAR, max_length=128)
    schema.add_field("sub_type", DataType.VARCHAR, max_length=128)
    schema.add_field("score", DataType.DOUBLE)
    schema.add_field("open_hours", DataType.VARCHAR, max_length=512)
    schema.add_field("tags", DataType.VARCHAR, max_length=2048)
    schema.add_field("content_type", DataType.VARCHAR, max_length=64)
    return schema


def _make_user_note_schema(dim: int):
    from pymilvus import DataType
    schema = MilvusClient.create_schema()
    schema.add_field("id", DataType.VARCHAR, max_length=128, is_primary=True)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("shop_id", DataType.INT64)
    schema.add_field("user_nickname", DataType.VARCHAR, max_length=256)
    schema.add_field("content_type", DataType.VARCHAR, max_length=64)
    return schema


def run_full_shop_desc_sync(
    *,
    milvus_host: str | None = None,
    milvus_port: int | None = None,
    embedding_dim: int | None = None,
    embedding_api_key: str | None = None,
    embedding_model: str | None = None,
    multimodal_embedding_model: str | None = None,
    image_base_path: str | Path | None = None,
    full_resync: bool = False,
) -> int:
    """Run shop description sync (incremental by default).

    Uses SyncCursor to track the last successful sync timestamp.  Only shops
    modified since the last run are fetched.  Pass ``full_resync=True`` to
    re-sync everything.

    Returns the number of shops synced.
    """
    milvus_host = milvus_host or os.environ.get("MILVUS_HOST", "localhost")
    milvus_port = milvus_port or int(os.environ.get("MILVUS_PORT", "19530"))
    embedding_dim = embedding_dim or int(os.environ.get("EMBEDDING_DIM", "1024"))
    embedding_api_key = embedding_api_key or os.environ["EMBEDDING_API_KEY"]
    embedding_model = embedding_model or os.environ.get(
        "MULTIMODAL_EMBEDDING_MODEL", "tongyi-embedding-vision-plus"
    )
    image_base_path = (
        image_base_path
        if image_base_path is not None
        else os.environ.get("IMAGE_BASE_PATH", "")
    )

    cursor = SyncCursor("shop_desc")
    since = 0 if full_resync else cursor.last_synced_at

    milvus_client = _init_product_milvus(host=milvus_host, port=milvus_port, dim=embedding_dim)

    def embed(shop: dict) -> list[float]:
        return embed_shop_multimodal(
            shop,
            api_key=embedding_api_key,
            model=embedding_model,
            image_base_path=image_base_path,
        )

    count = sync_shop_desc(
        milvus_client=milvus_client,
        fetch_shops_fn=lambda: fetch_shops(since=since),
        embed_shop=embed,
    )

    if count > 0:
        cursor.update()

    return count


def _parse_json_list(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(v) for v in parsed]
    except (json.JSONDecodeError, TypeError):
        pass
    return [str(value)]


if __name__ == "__main__":
    synced = run_full_shop_desc_sync()
    print(f"synced {synced} shops to {COLLECTION_SHOP_DESC}")
