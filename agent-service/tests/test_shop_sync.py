import json

import pytest

from src.storage.milvus_store import COLLECTION_SHOP_DESC
from src.storage.shop_sync import (
    build_embedding_text,
    build_multimodal_input,
    embed_shop_multimodal,
    fetch_shops,
    run_full_shop_desc_sync,
    sync_shop_desc,
    to_milvus_record,
)


class FakeMilvusClient:
    def __init__(self):
        self.upserted: list[dict] = []

    def upsert(self, collection_name: str, data: list[dict]):
        assert collection_name == COLLECTION_SHOP_DESC
        self.upserted.extend(data)


def sample_shop(shop_id: int) -> dict:
    return {
        "shopId": shop_id,
        "name": f"店铺{shop_id}",
        "type": "美食",
        "subType": "火锅",
        "area": "陆家嘴",
        "longitude": 121.5,
        "latitude": 31.2,
        "avgPrice": 150,
        "score": 45,
        "openHours": "10:00-22:00",
        "description": "正宗川味火锅",
        "tags": '["停车方便"]',
        "recommendedScenes": '["约会"]',
        "images": "img1.jpg",
    }


class TestBuildEmbeddingText:
    def test_combines_name_description_tags_and_scenes(self):
        shop = {
            "name": "蜀大侠火锅",
            "description": "正宗川味火锅",
            "tags": '["停车方便","有包厢"]',
            "recommended_scenes": '["约会","家庭聚餐"]',
            "images": "img1.jpg,img2.jpg",
        }

        text = build_embedding_text(shop)

        assert "蜀大侠火锅" in text
        assert "正宗川味火锅" in text
        assert "停车方便" in text
        assert "家庭聚餐" in text
        assert "img1.jpg" in text
        assert "img2.jpg" in text

    def test_build_multimodal_input_includes_local_image(self, tmp_path):
        image = tmp_path / "photo.jpg"
        image.write_bytes(b"fake-image-bytes")
        shop = sample_shop(1)
        shop["images"] = "photo.jpg"

        items = build_multimodal_input(shop, tmp_path)

        assert items[0]["type"] == "text"
        assert len(items) == 2
        assert items[1]["type"] == "image_url"
        assert items[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


class TestToMilvusRecord:
    def test_record_has_required_fields_and_content_type(self):
        shop = {
            "shopId": 42,
            "name": "测试店铺",
            "type": "美食",
            "subType": "火锅",
            "area": "陆家嘴",
            "longitude": 121.5,
            "latitude": 31.2,
            "avgPrice": 150,
            "score": 45,
            "openHours": "10:00-22:00",
            "tags": '["停车方便"]',
        }
        embedding = [0.1, 0.2, 0.3]

        record = to_milvus_record(shop, embedding)

        assert record["id"] == "shop_desc_42"
        assert record["shop_id"] == 42
        assert record["embedding"] == embedding
        assert record["area"] == "陆家嘴"
        assert record["type"] == "美食"
        assert record["sub_type"] == "火锅"
        assert record["content_type"] == "shop_description"
        assert record["tags"] == '["停车方便"]'


class TestSyncShopDesc:
    def test_sync_writes_all_shops_with_non_empty_embeddings(self, embedding_dim):
        shops = [sample_shop(1), sample_shop(2)]
        client = FakeMilvusClient()

        count = sync_shop_desc(
            milvus_client=client,
            fetch_shops_fn=lambda: shops,
            embed_shop=lambda shop: [0.01 * shop["shopId"]] * embedding_dim,
        )

        assert count == 2
        assert len(client.upserted) == 2
        for row in client.upserted:
            assert row["content_type"] == "shop_description"
            assert len(row["embedding"]) == embedding_dim
            assert any(v != 0 for v in row["embedding"])


class TestFetchShops:
    def test_fetch_shops_calls_sync_endpoint_and_returns_data(self):
        from unittest.mock import MagicMock, patch

        fake_client = MagicMock()
        fake_client.get.return_value = httpx.Response(
            200,
            json={
                "success": True,
                "data": [sample_shop(1)],
            },
            request=httpx.Request("GET", "http://localhost:8085/api/sync/shops"),
        )

        with patch("src.storage.shop_sync.get_java_client", return_value=fake_client):
            shops = fetch_shops(since=0)

        assert len(shops) == 1
        assert shops[0]["shopId"] == 1
        fake_client.get.assert_called_once_with("/api/sync/shops", params={"since": 0})


class TestEmbedShopMultimodal:
    def test_embed_shop_posts_multimodal_payload_and_returns_vector(self):
        import httpx

        shop = sample_shop(1)

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["model"] == "doubao-embedding-vision-250615"
            assert body["input"][0]["type"] == "text"
            assert "店铺1" in body["input"][0]["text"]
            return httpx.Response(
                200,
                json={"data": {"embedding": [0.5, 0.6, 0.7]}},
            )

        transport = httpx.MockTransport(handler)
        with httpx.Client(transport=transport, base_url="https://ark.example.com/api/v3") as client:
            vector = embed_shop_multimodal(
                shop,
                api_key="key",
                base_url="https://ark.example.com/api/v3",
                model="doubao-embedding-vision-250615",
                client=client,
            )

        assert vector == [0.5, 0.6, 0.7]
