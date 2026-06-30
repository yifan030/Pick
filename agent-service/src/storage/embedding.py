"""Shared embedding interface — thin shim over ingestion embedding.

All memory modules import embed_texts from here so the implementation
can be swapped without touching every caller.

Lazily loads the actual embedding function to avoid triggering pymilvus
imports during test collection (ingestion.__init__ imports shop_sync
which imports pymilvus).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def embed_texts(
    texts: list[str],
    **kwargs,
) -> list[list[float]]:
    """Embed a list of texts, delegating to src.ingestion.embedding.

    Args:
        texts: List of text strings to embed.
        **kwargs: Additional keyword arguments for the embedding function.

    Returns:
        List of embedding vectors.
    """
    mod_key = "src.ingestion.embedding"
    if mod_key not in sys.modules:
        _lazy_load_embedding(mod_key)
    return sys.modules[mod_key].embed_texts(texts, **kwargs)


def _lazy_load_embedding(mod_key: str) -> None:
    """Load src.ingestion.embedding directly via file path, bypassing __init__.py."""
    spec = importlib.util.spec_from_file_location(
        mod_key,
        Path(__file__).resolve().parent.parent / "ingestion" / "embedding.py",
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot load src.ingestion.embedding")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_key] = mod
    spec.loader.exec_module(mod)


__all__ = ["embed_texts"]
