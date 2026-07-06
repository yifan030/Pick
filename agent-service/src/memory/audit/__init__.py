# src/memory/audit/__init__.py
"""Audit logging — all profile changes recorded to memory_diff.jsonl."""

from src.memory.audit.logger import AuditLogger

__all__ = ["AuditLogger"]
