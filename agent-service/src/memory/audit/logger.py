# src/memory/audit.py
"""Audit logging for memory operations (memory_diff.jsonl).

Every profile update generates an audit entry recording:
- What changed (old → new)
- Why (trigger conversation context)
- When (timestamp)

Storage: agent-service/data/memory_diff/{user_id}/{YYYY-MM}.jsonl
Retention: 180 days, then archived/compressed.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("pick.memory.audit")

# ── Config ────────────────────────────────────────────────────────────

AUDIT_BASE_DIR = os.environ.get(
    "MEMORY_AUDIT_DIR",
    os.path.join(os.path.dirname(__file__), "..", "..", "data", "memory_diff"),
)
AUDIT_RETENTION_DAYS = 180


class AuditLogger:
    """Appends memory_diff entries to per-user, per-month JSONL files."""

    def __init__(self, base_dir: Optional[str] = None):
        self._base_dir = base_dir or AUDIT_BASE_DIR

    def log(
        self,
        user_id: str,
        session_id: str,
        trigger_message: str,
        round_index: int,
        operations: List[Dict],
    ) -> str:
        """Write an audit entry."""
        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "user_id": user_id,
            "session_id": session_id,
            "trigger_conversation": {
                "user_message": trigger_message,
                "round_index": round_index,
            },
            "operations": operations,
        }

        month_str = now.strftime("%Y-%m")
        dir_path = os.path.join(self._base_dir, user_id)
        os.makedirs(dir_path, exist_ok=True)

        file_path = os.path.join(dir_path, f"{month_str}.jsonl")

        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("Failed to write audit log for user=%s", user_id)

        return file_path

    def read_recent(
        self, user_id: str, months: int = 3
    ) -> List[Dict]:
        """Read recent audit entries for a user."""
        entries = []
        dir_path = os.path.join(self._base_dir, user_id)
        if not os.path.isdir(dir_path):
            return entries

        for filename in sorted(os.listdir(dir_path), reverse=True):
            if not filename.endswith(".jsonl"):
                continue
            file_path = os.path.join(dir_path, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
            except Exception:
                logger.exception("Failed to read audit file %s", file_path)
            if len(entries) >= 1000:
                break
        return entries

    def cleanup_old(self) -> int:
        """Remove audit files older than AUDIT_RETENTION_DAYS. Returns count deleted."""
        import time
        now = time.time()
        cutoff = now - AUDIT_RETENTION_DAYS * 86400
        deleted = 0
        if not os.path.isdir(self._base_dir):
            return 0
        for user_dir in os.listdir(self._base_dir):
            user_path = os.path.join(self._base_dir, user_dir)
            if not os.path.isdir(user_path):
                continue
            for filename in os.listdir(user_path):
                file_path = os.path.join(user_path, filename)
                if os.path.getmtime(file_path) < cutoff:
                    try:
                        os.remove(file_path)
                        deleted += 1
                    except Exception:
                        logger.exception("Failed to delete old audit file %s", file_path)
        return deleted
