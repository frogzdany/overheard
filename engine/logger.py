"""Append-only JSONL session logger.

All workers receive a shared `JSONLLogger` for the current session and emit
events into the same file. Thread-safe (every `.log()` acquires the lock and
writes one line). Drops writes that arrive after `.close()` to tolerate
late-firing background workers.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


class JSONLLogger:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fp = path.open("a", buffering=1)
        self._lock = threading.Lock()
        self.path = path

    def log(self, event: str, **fields) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            **fields,
        }
        with self._lock:
            if self._fp.closed:
                return
            try:
                self._fp.write(json.dumps(rec, default=str) + "\n")
            except ValueError:
                # Closed between .closed check and write — narrow race; drop.
                pass

    def close(self) -> None:
        with self._lock:
            try:
                self._fp.close()
            except Exception:
                pass
