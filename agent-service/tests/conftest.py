import sys
from pathlib import Path

import pytest
from pymilvus import MilvusClient

sys.path.insert(0, str(Path(__file__).parent.parent))

COLLECTION_SHOP_DESC = "collection_shop_desc"
COLLECTION_USER_NOTE = "collection_user_note"


@pytest.fixture(scope="session")
def milvus_host():
    return "111.229.253.150"


@pytest.fixture(scope="session")
def milvus_port():
    return 19530


@pytest.fixture(scope="session")
def milvus_uri(milvus_host, milvus_port):
    return f"http://{milvus_host}:{milvus_port}"


@pytest.fixture
def embedding_dim():
    return 128


@pytest.fixture
def clean_milvus(milvus_uri):
    client = MilvusClient(uri=milvus_uri)
    for name in (COLLECTION_SHOP_DESC, COLLECTION_USER_NOTE):
        if client.has_collection(name):
            client.drop_collection(name)
    yield
    for name in (COLLECTION_SHOP_DESC, COLLECTION_USER_NOTE):
        if client.has_collection(name):
            client.drop_collection(name)
