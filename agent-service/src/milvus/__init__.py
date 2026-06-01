from pymilvus import DataType, MilvusClient

HNSW_PARAMS = {"M": 16, "efConstruction": 200}
SHOP_DESC = "collection_shop_desc"
USER_NOTE = "collection_user_note"


def init(embedding_dim: int, host: str = "localhost", port: int = 19530) -> MilvusClient:
    client = MilvusClient(uri=f"http://{host}:{port}")

    _ensure_collection(client, embedding_dim, SHOP_DESC, _build_shop_desc_schema)
    _ensure_collection(client, embedding_dim, USER_NOTE, _build_user_note_schema)

    return client


def _ensure_collection(client, dim, name, schema_builder):
    if client.has_collection(name):
        return
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


def _build_shop_desc_schema(dim: int):
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


def _build_user_note_schema(dim: int):
    schema = MilvusClient.create_schema()
    schema.add_field("id", DataType.VARCHAR, max_length=128, is_primary=True)
    schema.add_field("embedding", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("shop_id", DataType.INT64)
    schema.add_field("user_nickname", DataType.VARCHAR, max_length=256)
    schema.add_field("content_type", DataType.VARCHAR, max_length=64)
    return schema
