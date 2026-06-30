# src/ingestion/embedding.py
"""Re-export from src.storage.embedding for backward compatibility."""
from src.storage.embedding import embed_texts, embed_single

__all__ = ["embed_texts", "embed_single"]
