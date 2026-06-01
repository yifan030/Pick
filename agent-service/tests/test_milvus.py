from pymilvus import MilvusClient

from src.milvus import init


class TestInit:
    def test_init_creates_both_collections(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        assert client.has_collection("collection_shop_desc")
        assert client.has_collection("collection_user_note")
        assert isinstance(client, MilvusClient)

    def test_init_is_idempotent(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        init(embedding_dim, host=milvus_host, port=milvus_port)
        init(embedding_dim, host=milvus_host, port=milvus_port)

    def test_init_returns_connected_client(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        names = client.list_collections()
        assert "collection_shop_desc" in names
        assert "collection_user_note" in names


class TestShopDescSchema:
    EXPECTED_FIELDS = {
        "id", "embedding", "shop_id", "area", "longitude", "latitude",
        "avg_price", "type", "sub_type", "score", "open_hours", "tags", "content_type",
    }

    def test_all_fields_present(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_shop_desc")
        field_names = {f["name"] for f in desc["fields"]}
        assert self.EXPECTED_FIELDS.issubset(field_names)

    def test_primary_key_is_varchar_id(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_shop_desc")
        id_field = next(f for f in desc["fields"] if f["name"] == "id")
        assert id_field["type"] == "VARCHAR"
        assert id_field.get("is_primary") is True

    def test_embedding_field_dimension(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_shop_desc")
        emb_field = next(f for f in desc["fields"] if f["name"] == "embedding")
        assert emb_field["type"] == "FLOAT_VECTOR"
        assert emb_field["params"]["dim"] == str(embedding_dim)


class TestUserNoteSchema:
    EXPECTED_FIELDS = {"id", "embedding", "shop_id", "user_nickname", "content_type"}

    def test_all_fields_present(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_user_note")
        field_names = {f["name"] for f in desc["fields"]}
        assert self.EXPECTED_FIELDS.issubset(field_names)

    def test_primary_key_is_varchar_id(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_user_note")
        id_field = next(f for f in desc["fields"] if f["name"] == "id")
        assert id_field["type"] == "VARCHAR"
        assert id_field.get("is_primary") is True

    def test_embedding_field_dimension(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_user_note")
        emb_field = next(f for f in desc["fields"] if f["name"] == "embedding")
        assert emb_field["type"] == "FLOAT_VECTOR"
        assert emb_field["params"]["dim"] == str(embedding_dim)


class TestHNSWIndex:
    def test_index_exists_on_shop_desc(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        indexes = client.list_indexes("collection_shop_desc")
        assert "embedding" in indexes

    def test_index_exists_on_user_note(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        indexes = client.list_indexes("collection_user_note")
        assert "embedding" in indexes

    def test_index_params_shop_desc(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        idx = client.describe_index("collection_shop_desc", "embedding")
        assert idx["index_type"] == "HNSW"
        assert idx["metric_type"] == "COSINE"

    def test_index_params_user_note(self, clean_milvus, embedding_dim, milvus_host, milvus_port):
        client = init(embedding_dim, host=milvus_host, port=milvus_port)

        idx = client.describe_index("collection_user_note", "embedding")
        assert idx["index_type"] == "HNSW"
        assert idx["metric_type"] == "COSINE"


class TestCustomDimension:
    def test_different_embedding_dimension(self, clean_milvus, milvus_host, milvus_port):
        client = init(embedding_dim=384, host=milvus_host, port=milvus_port)

        desc = client.describe_collection("collection_shop_desc")
        emb_field = next(f for f in desc["fields"] if f["name"] == "embedding")
        assert emb_field["params"]["dim"] == "384"
