"""SQLite-backed session metadata store.

The JSONL + WAV + Markdown files under `LOG_DIR` remain the source of truth
for transcripts and audio. This DB is a thin index that stores the bits of
metadata that don't fit the event log nicely — user-supplied titles,
LLM-generated titles, summary blurbs, etc. Lookup is O(1) by session_id.

Lives at `<user data>/overheard.db` next to `logs/` and `settings.json`.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .config import _user_data_dir

DB_PATH = _user_data_dir() / "overheard.db"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id              TEXT PRIMARY KEY,
    title           TEXT,
    generated_title TEXT,
    summary_blurb   TEXT,
    created_at      REAL,
    ended_at        REAL,
    duration_s      REAL DEFAULT 0,
    updated_at      REAL
);
CREATE TABLE IF NOT EXISTS suggested_actions (
    id           TEXT PRIMARY KEY,
    session_id   TEXT NOT NULL,
    json         TEXT NOT NULL,
    status       TEXT NOT NULL,
    suggested_at TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
"""

# Migrations for DBs created before later columns were added. Run BEFORE the
# index DDL so older DBs (which lack these columns) can be upgraded — each
# ALTER is wrapped in try/except so re-running on a fresh DB is fine.
_MIGRATIONS: tuple[str, ...] = ()

_INDEXES = """
CREATE INDEX IF NOT EXISTS sessions_created_at_idx
    ON sessions(created_at DESC);
CREATE INDEX IF NOT EXISTS suggested_actions_session_idx
    ON suggested_actions(session_id, suggested_at DESC);
"""


class SessionsDB:
    def __init__(self, path: Path = DB_PATH) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            for stmt in _MIGRATIONS:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass
            conn.executescript(_INDEXES)
            conn.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # New connection per call so we don't have to worry about
        # cross-thread sqlite reuse (the default sqlite3 module is not
        # thread-safe per-connection without `check_same_thread=False`).
        conn = sqlite3.connect(self._path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    # ---- session row management ----

    def upsert_created(self, session_id: str, created_at: float) -> None:
        """Idempotent: create a row when a session starts, or no-op if a
        row already exists (e.g. crash recovery, backfill)."""
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions(id, created_at, updated_at) "
                "VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
                (session_id, created_at, created_at),
            )

    def mark_ended(self, session_id: str, ended_at: float, duration_s: float) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET ended_at=?, duration_s=?, updated_at=? "
                "WHERE id=?",
                (ended_at, duration_s, ended_at, session_id),
            )

    def set_generated_title(self, session_id: str, title: str, blurb: str) -> None:
        with self._lock, self._connect() as conn:
            now = _now()
            conn.execute(
                "INSERT INTO sessions(id, generated_title, summary_blurb, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET generated_title=excluded.generated_title, "
                "summary_blurb=excluded.summary_blurb, updated_at=excluded.updated_at",
                (session_id, title.strip(), blurb.strip(), now, now),
            )

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM suggested_actions WHERE session_id=?", (session_id,))
            cur = conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))
            return cur.rowcount > 0

    def set_user_title(self, session_id: str, title: str | None) -> None:
        """User rename. Pass `None` to clear the override and fall back to
        the LLM-generated title."""
        with self._lock, self._connect() as conn:
            now = _now()
            value = title.strip() if isinstance(title, str) else None
            conn.execute(
                "INSERT INTO sessions(id, title, created_at, updated_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, updated_at=excluded.updated_at",
                (session_id, value, now, now),
            )

    # ---- reads ----

    def get(self, session_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            return dict(row) if row else None

    def all(self) -> dict[str, dict[str, Any]]:
        """Map session_id → row, for bulk decoration of `GET /sessions`."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM sessions").fetchall()
            return {r["id"]: dict(r) for r in rows}

    # ---- suggested actions ----

    def upsert_action(self, action: dict[str, Any]) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO suggested_actions(id, session_id, json, status, "
                "suggested_at, updated_at) VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET session_id=excluded.session_id, "
                "json=excluded.json, status=excluded.status, "
                "suggested_at=excluded.suggested_at, updated_at=excluded.updated_at",
                (action["id"], action["sessionId"], json.dumps(action, default=str),
                 action["status"], action["suggestedAt"], action["updatedAt"]),
            )

    def get_action(self, session_id: str, action_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT json FROM suggested_actions WHERE session_id=? AND id=?",
                (session_id, action_id),
            ).fetchone()
        return json.loads(row["json"]) if row else None

    def get_actions(self, session_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT json FROM suggested_actions WHERE session_id=? "
                "ORDER BY suggested_at DESC, updated_at DESC",
                (session_id,),
            ).fetchall()
        return [json.loads(row["json"]) for row in rows]

def resolve_title(row: dict[str, Any] | None, session_id: str) -> str:
    """Pick the best display name for a session.

    Priority: user override > LLM-generated > the bare session id as a
    last-resort fallback.
    """
    if row:
        for k in ("title", "generated_title"):
            v = row.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return session_id


def _now() -> float:
    import time
    return time.time()


_singleton: SessionsDB | None = None


def get_db() -> SessionsDB:
    global _singleton
    if _singleton is None:
        _singleton = SessionsDB()
    return _singleton
