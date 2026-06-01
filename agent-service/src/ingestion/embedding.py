import os

from openai import OpenAI

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text")


def get_embedding_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("LLM_BASE_URL"),
        api_key=os.environ.get("EMBEDDING_API_KEY") or os.environ.get("LLM_API_KEY", "sk-placeholder"),
    )


def embed_texts(texts: list[str], *, client: OpenAI | None = None) -> list[list[float]]:
    if not texts:
        return []
    client = client or get_embedding_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]
