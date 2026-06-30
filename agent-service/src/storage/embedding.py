"""Text embedding via OpenAI-compatible embedding API.

All memory modules and sync pipelines import ``embed_texts`` / ``embed_single``
from here. Uses the same OpenAI-compatible client as chat, configurable via
standard env vars. The default model is ``text-embedding-3-small``;
product sync uses a separate multimodal embedding path (see ``shop_sync.py``).
"""

from __future__ import annotations

import os
import logging
from openai import OpenAI

logger = logging.getLogger("pick.storage.embedding")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_BASE_URL = os.environ.get("EMBEDDING_BASE_URL", None)
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", None)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy-init the embedding client (synchronous, non-streaming)."""
    global _client
    if _client is None:
        _client = OpenAI(
            base_url=EMBEDDING_BASE_URL or os.environ.get("LLM_BASE_URL"),
            api_key=EMBEDDING_API_KEY or os.environ.get("LLM_API_KEY", "sk-placeholder"),
        )
    return _client


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed a list of text strings via OpenAI-compatible embeddings API.

    Args:
        texts: List of text strings to embed (max 2048 per call recommended).
        model: Override the default embedding model.
        dimensions: Override the output embedding dimensions.

    Returns:
        List of embedding vectors, one per input text, preserving order.
    """
    if not texts:
        return []

    client = _get_client()
    model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM

    try:
        response = client.embeddings.create(
            model=model,
            input=texts,
            dimensions=dims,
        )
    except Exception:
        logger.exception("Embedding API call failed for %d texts", len(texts))
        raise

    sorted_data = sorted(response.data, key=lambda d: d.index)
    return [d.embedding for d in sorted_data]


def embed_single(text: str, **kwargs) -> list[float]:
    """Embed a single text string.

    Args:
        text: A single text string to embed.
        **kwargs: Forwarded to ``embed_texts``.

    Returns:
        A single embedding vector.
    """
    return embed_texts([text], **kwargs)[0]


__all__ = ["embed_texts", "embed_single"]
