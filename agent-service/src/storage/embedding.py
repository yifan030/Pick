"""Embedding interface stub — to be fully implemented by Plan A.

Currently delegates to src.ingestion.embedding for the embed function.
"""

from __future__ import annotations

import os
from openai import OpenAI


EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "doubao-embedding-text")
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))


def get_embedding_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ.get("EMBEDDING_BASE_URL") or os.environ.get("LLM_BASE_URL"),
        api_key=os.environ.get("EMBEDDING_API_KEY") or os.environ.get("LLM_API_KEY", "sk-placeholder"),
    )


def embed_texts(texts: list[str], *, client: OpenAI | None = None) -> list[list[float]]:
    """Embed multiple texts, returning a list of embedding vectors."""
    if not texts:
        return []
    client = client or get_embedding_client()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def embed_single(text: str, *, client: OpenAI | None = None) -> list[float]:
    """Embed a single text, returning one embedding vector."""
    return embed_texts([text], client=client)[0]
