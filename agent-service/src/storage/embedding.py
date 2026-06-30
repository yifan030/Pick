"""Shared embedding interface — thin shim over ingestion embedding.

All memory modules import embed_texts from here so the implementation
can be swapped without touching every caller.
"""

from src.ingestion.embedding import embed_texts

__all__ = ["embed_texts"]
