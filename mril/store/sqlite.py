"""SQLite-backed event store — the local-first ledger."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from mril.core.events import Event, event_from_dict

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL UNIQUE,
    event_type  TEXT NOT NULL,
    task_id     TEXT,
    attempt_id  TEXT,
    decision_id TEXT,
    dedupe_key  TEXT,
    occurred_at TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_decision ON events(decision_id);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_EVENT_COLS = ("event_id", "event_type", "task_id", "attempt_id", "decision_id", "occurred_at")


class SQLiteEventStore:
    def __init__(self, path: str | Path = "mril.db"):
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL + busy timeout: the eval runner and a `mril task` inspection can
        # coexist on one ledger without SQLITE_BUSY on the first read.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._lock = threading.Lock()
        with self._conn:
            self._conn.executescript(_SCHEMA)
            self._migrate()

    def _migrate(self) -> None:
        cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(events)")}
        if "dedupe_key" not in cols:
            self._conn.execute("ALTER TABLE events ADD COLUMN dedupe_key TEXT")
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedupe "
            "ON events(dedupe_key)"
        )

    def append(self, event: Event) -> bool:
        payload = json.dumps(event.to_dict(), sort_keys=True)
        row = (
            event.event_id,
            event.event_type,
            event.task_id,
            event.attempt_id,
            event.decision_id,
            event.dedupe_key,
            event.occurred_at,
            payload,
        )
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO events "
                "(event_id, event_type, task_id, attempt_id, decision_id, "
                "dedupe_key, occurred_at, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
            return cur.rowcount == 1

    def get(self, event_id: str) -> Event | None:
        row = self._conn.execute(
            "SELECT payload FROM events WHERE event_id = ?", (event_id,)
        ).fetchone()
        return event_from_dict(json.loads(row["payload"])) if row else None

    def events_for_task(self, task_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT payload FROM events WHERE task_id = ? ORDER BY seq", (task_id,)
        ).fetchall()
        return [event_from_dict(json.loads(r["payload"])) for r in rows]

    def events_for_decision(self, decision_id: str) -> list[Event]:
        rows = self._conn.execute(
            "SELECT payload FROM events WHERE decision_id = ? ORDER BY seq",
            (decision_id,),
        ).fetchall()
        return [event_from_dict(json.loads(r["payload"])) for r in rows]

    def all_events(self) -> list[Event]:
        rows = self._conn.execute("SELECT payload FROM events ORDER BY seq").fetchall()
        return [event_from_dict(json.loads(r["payload"])) for r in rows]

    def task_ids(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT task_id FROM events WHERE task_id IS NOT NULL ORDER BY task_id"
        ).fetchall()
        return [r["task_id"] for r in rows]

    def close(self) -> None:
        self._conn.close()
