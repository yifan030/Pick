"""Text embedding via DashScope native TextEmbedding API.

All memory modules and sync pipelines import ``embed_texts`` / ``embed_single``
from here. Uses DashScope TextEmbedding (text-embedding-v4 by default).
Product sync uses a separate multimodal embedding path (see ``shop_sync.py``).
"""

from __future__ import annotations

import os
import logging

import dashscope
from dashscope import TextEmbedding

logger = logging.getLogger("pick.storage.embedding")

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-v4")
EMBEDDING_API_KEY = os.environ.get("EMBEDDING_API_KEY", None)
EMBEDDING_DIM = int(os.environ.get("EMBEDDING_DIM", "1024"))

_initialized = False


def _ensure_api_key() -> None:
    global _initialized
    if not _initialized:
        key = EMBEDDING_API_KEY or os.environ.get("DASHSCOPE_API_KEY")
        if key:
            dashscope.api_key = key
        _initialized = True


def embed_texts(
    texts: list[str],
    *,
    model: str | None = None,
    dimensions: int | None = None,
) -> list[list[float]]:
    """Embed a list of text strings via DashScope TextEmbedding API.

    Args:
        texts: List of text strings to embed.
        model: Override the default embedding model.
        dimensions: Override the output embedding dimensions.

    Returns:
        List of embedding vectors, one per input text, preserving order.
    """
    if not texts:
        return []

    _ensure_api_key()
    model = model or EMBEDDING_MODEL
    dims = dimensions or EMBEDDING_DIM

    try:
        response = TextEmbedding.call(
            model=model,
            input=texts,
            dimension=dims,
        )
    except Exception:
        logger.exception("Embedding API call failed for %d texts", len(texts))
        raise

    if response.status_code != 200:
        raise RuntimeError(
            f"TextEmbedding API error: code={response.code}, message={response.message}"
        )

    output = response.output
    if isinstance(output, dict):
        return [item.get("embedding", []) for item in output.get("embeddings", [])]
    return [item.embedding for item in output.embeddings]


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
