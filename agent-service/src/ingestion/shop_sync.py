import base64
import json
import os
from collections.abc import Callable
from pathlib import Path

import httpx
from pymilvus import MilvusClient

from src.milvus import SHOP_DESC

BATCH_SIZE = 50
CONTENT_TYPE = "shop_description"
EMBEDDING_PATH = "/embeddings/multimodal"


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

    images = shop.get("images")
    if images:
        for img in images.split(","):
            img = img.strip()
            if img:
                parts.append(img)

    return "\n".join(parts)


def build_multimodal_input(shop: dict, image_base_path: str | Path = "") -> list[dict]:
    items: list[dict] = [{"type": "text", "text": build_embedding_text(shop)}]
    base = Path(image_base_path) if image_base_path else None

    images = shop.get("images") or ""
    for img in images.split(","):
        img = img.strip()
        if not img or base is None:
            continue
        path = base / img
        if not path.is_file():
            continue
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        suffix = path.suffix.lstrip(".").lower() or "jpeg"
        if suffix == "jpg":
            suffix = "jpeg"
        items.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/{suffix};base64,{encoded}"},
            }
        )

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


def fetch_shops(
    base_url: str,
    internal_token: str,
    since: int = 0,
    client: httpx.Client | None = None,
) -> list[dict]:
    url = f"{base_url.rstrip('/')}/api/sync/shops"
    headers = {"X-Internal-Token": internal_token}
    params = {"since": since}

    if client is None:
        with httpx.Client(timeout=60.0) as http:
            response = http.get(url, headers=headers, params=params)
            response.raise_for_status()
            payload = response.json()
    else:
        response = client.get(url, headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()

    if not payload.get("success", True):
        raise RuntimeError(f"shop sync failed: {payload}")

    return payload.get("data") or []


def embed_shop_multimodal(
    shop: dict,
    *,
    api_key: str,
    base_url: str,
    model: str,
    image_base_path: str | Path = "",
    client: httpx.Client | None = None,
) -> list[float]:
    payload = {
        "model": model,
        "input": build_multimodal_input(shop, image_base_path),
    }
    url = f"{base_url.rstrip('/')}{EMBEDDING_PATH}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "x-ark-vlm1": "true",
    }

    if client is None:
        with httpx.Client(timeout=60.0) as http:
            response = http.post(url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
    else:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        body = response.json()

    data = body.get("data")
    if isinstance(data, dict):
        embedding = data.get("embedding")
    elif isinstance(data, list) and data:
        embedding = data[0].get("embedding")
    else:
        embedding = None

    if not embedding:
        raise RuntimeError(f"embedding response missing vector: {body}")

    return embedding


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
        milvus_client.upsert(collection_name=SHOP_DESC, data=records[i : i + batch_size])

    return len(shops)


def run_full_shop_desc_sync(
    *,
    java_base_url: str | None = None,
    internal_token: str | None = None,
    milvus_host: str | None = None,
    milvus_port: int | None = None,
    embedding_dim: int | None = None,
    embedding_api_key: str | None = None,
    embedding_base_url: str | None = None,
    embedding_model: str | None = None,
    image_base_path: str | Path | None = None,
) -> int:
    java_base_url = java_base_url or os.environ["JAVA_BASE_URL"]
    internal_token = internal_token or os.environ["SYNC_INTERNAL_TOKEN"]
    milvus_host = milvus_host or os.environ.get("MILVUS_HOST", "localhost")
    milvus_port = milvus_port or int(os.environ.get("MILVUS_PORT", "19530"))
    embedding_dim = embedding_dim or int(os.environ.get("EMBEDDING_DIM", "1024"))
    embedding_api_key = embedding_api_key or os.environ["EMBEDDING_API_KEY"]
    embedding_base_url = embedding_base_url or os.environ["EMBEDDING_BASE_URL"]
    embedding_model = embedding_model or os.environ.get(
        "EMBEDDING_MODEL", "doubao-embedding-vision-250615"
    )
    image_base_path = image_base_path or os.environ.get("IMAGE_BASE_PATH", "")

    from milvus import init

    milvus_client = init(embedding_dim, host=milvus_host, port=milvus_port)

    def embed(shop: dict) -> list[float]:
        return embed_shop_multimodal(
            shop,
            api_key=embedding_api_key,
            base_url=embedding_base_url,
            model=embedding_model,
            image_base_path=image_base_path,
        )

    return sync_shop_desc(
        milvus_client=milvus_client,
        fetch_shops_fn=lambda: fetch_shops(java_base_url, internal_token, since=0),
        embed_shop=embed,
    )


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
    print(f"synced {synced} shops to {SHOP_DESC}")

