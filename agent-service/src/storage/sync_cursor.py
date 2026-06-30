"""Sync cursor: tracks last-sync timestamps for incremental data ingestion.

Stores per-collection millisecond timestamps in a local JSON file so that
subsequent sync runs only fetch records modified after the last run.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("pick.storage.sync_cursor")

DEFAULT_CURSOR_DIR = os.environ.get(
    "SYNC_CURSOR_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "data" / "sync_cursor"),
)


class SyncCursor:
    """Read/write per-collection sync timestamps from a JSON file.

    Usage::

        cursor = SyncCursor("shop_desc")
        since = cursor.last_synced_at  # 0 on first run
        new_data = fetch(since=since)
        cursor.update()  # sets to now
    """

    def __init__(self, collection: str, cursor_dir: str | None = None):
        self._collection = collection
        self._dir = Path(cursor_dir or DEFAULT_CURSOR_DIR)
        self._path = self._dir / f"{collection}_cursor.json"

    @property
    def last_synced_at(self) -> int:
        """Millisecond timestamp of the last successful sync, or 0."""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return int(data.get("last_synced_at", 0))
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return 0

    def update(self, timestamp_ms: int | None = None) -> None:
        """Persist the current timestamp (defaults to now in ms)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        ts = timestamp_ms or int(time.time() * 1000)
        self._path.write_text(
            json.dumps({
                "collection": self._collection,
                "last_synced_at": ts,
                "updated_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000)),
            }, indent=2),
            encoding="utf-8",
        )
        logger.info("Sync cursor updated: %s → %s", self._collection, ts)
