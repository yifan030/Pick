from unittest.mock import MagicMock

import httpx
import pytest

from src.storage.user_note_sync import (
    build_embedding_text,
    fetch_blogs_from_java,
    run_full_sync,
    to_milvus_row,
)
from src.storage.milvus_store import COLLECTION_USER_NOTE


class TestBuildEmbeddingText:
    def test_combines_title_and_content(self):
        blog = {
            "title": "人均30的港式茶餐厅",
            "content": "又吃到一家好吃的茶餐厅",
        }

        text = build_embedding_text(blog)

        assert "人均30的港式茶餐厅" in text
        assert "又吃到一家好吃的茶餐厅" in text


class TestToMilvusRow:
    def test_builds_note_row_with_metadata(self, embedding_dim):
        blog = {
            "blogId": 4,
            "shopId": 10,
            "userNickname": "测试用户",
            "title": "探店标题",
            "content": "探店正文",
        }
        embedding = [0.1] * embedding_dim

        row = to_milvus_row(blog, embedding)

        assert row["id"] == "note_4"
        assert row["shop_id"] == 10
        assert row["user_nickname"] == "测试用户"
        assert row["content_type"] == "user_note"
        assert row["embedding"] == embedding


class TestRunFullSync:
    @pytest.fixture
    def sample_blogs(self):
        return [
            {
                "blogId": 4,
                "shopId": 10,
                "userNickname": "用户A",
                "title": "标题一",
                "content": "正文一",
            },
            {
                "blogId": 5,
                "shopId": 1,
                "userNickname": "用户B",
                "title": "标题二",
                "content": "正文二",
            },
        ]

    def test_upserts_all_blogs_with_embeddings(self, embedding_dim, sample_blogs):
        milvus_client = MagicMock()
        fetch_blogs = MagicMock(return_value=sample_blogs)
        embed_texts = MagicMock(
            side_effect=lambda texts: [[float(i)] * embedding_dim for i, _ in enumerate(texts)]
        )

        count = run_full_sync(
            milvus_client=milvus_client,
            embedding_dim=embedding_dim,
            fetch_blogs=fetch_blogs,
            embed_texts=embed_texts,
        )

        assert count == 2
        fetch_blogs.assert_called_once_with(0)
        embed_texts.assert_called_once()
        milvus_client.upsert.assert_called_once()
        call = milvus_client.upsert.call_args
        assert call.kwargs["collection_name"] == COLLECTION_USER_NOTE
        rows = call.kwargs["data"]
        assert len(rows) == 2
        assert {row["id"] for row in rows} == {"note_4", "note_5"}
        for row in rows:
            assert len(row["embedding"]) == embedding_dim
            assert row["content_type"] == "user_note"


class TestFetchBlogsFromJava:
    def test_parses_sync_api_response(self):
        response = httpx.Response(
            200,
            json={
                "success": True,
                "data": [
                    {
                        "blogId": 4,
                        "shopId": 10,
                        "userNickname": "用户A",
                        "title": "标题",
                        "content": "正文",
                    }
                ],
            },
            request=httpx.Request("GET", "http://localhost:8085/api/sync/blogs"),
        )
        http_client = MagicMock()
        http_client.get.return_value = response

        blogs = fetch_blogs_from_java(
            since=0,
            base_url="http://localhost:8085",
            internal_token="secret",
            http_client=http_client,
        )

        assert len(blogs) == 1
        assert blogs[0]["blogId"] == 4
        http_client.get.assert_called_once_with(
            "http://localhost:8085/api/sync/blogs",
            headers={"X-Internal-Token": "secret"},
            params={"since": 0},
        )
