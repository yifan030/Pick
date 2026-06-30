# src/sync/__init__.py
"""Data sync module: MySQL → Neo4j entity graph seeding."""
from src.sync.entity_sync import sync_all_entities

__all__ = ["sync_all_entities"]
