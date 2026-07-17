"""Minimal SQLite conversation persistence."""

from __future__ import annotations

import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from hermes_constants import get_hermes_home, get_session_db_path


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds")


@dataclass(frozen=True, slots=True)
class SessionSummary:
    id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int


class SessionDB:
    """Store user/assistant turns without memory or search side systems."""

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            get_hermes_home(create=True)
            self.path = get_session_db_path()
        else:
            self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path)
        os.chmod(self.path, 0o600)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
                content TEXT NOT NULL,
                UNIQUE (session_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS messages_session_sequence
                ON messages(session_id, sequence);
            """
        )
        self._connection.commit()

    def create_session(self, title: str = "New session", session_id: str | None = None) -> str:
        identifier = session_id or uuid.uuid4().hex
        timestamp = _now()
        self._connection.execute(
            "INSERT INTO sessions(id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (identifier, title.strip()[:120] or "New session", timestamp, timestamp),
        )
        self._connection.commit()
        return identifier

    def has_session(self, session_id: str) -> bool:
        row = self._connection.execute(
            "SELECT 1 FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        return row is not None

    def set_title(self, session_id: str, title: str) -> None:
        with self._connection:
            cursor = self._connection.execute(
                "UPDATE sessions SET title = ?, updated_at = ? WHERE id = ?",
                (title.strip()[:120] or "New session", _now(), session_id),
            )
        if cursor.rowcount == 0:
            raise KeyError(f"unknown session: {session_id}")

    def add_turn(self, session_id: str, user_message: str, assistant_message: str) -> None:
        if not self.has_session(session_id):
            raise KeyError(f"unknown session: {session_id}")
        row = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) AS last_sequence FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        sequence = int(row["last_sequence"]) + 1
        timestamp = _now()
        with self._connection:
            self._connection.executemany(
                "INSERT INTO messages(session_id, sequence, role, content) VALUES (?, ?, ?, ?)",
                [
                    (session_id, sequence, "user", user_message),
                    (session_id, sequence + 1, "assistant", assistant_message),
                ],
            )
            self._connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE id = ?",
                (timestamp, session_id),
            )

    def load_messages(self, session_id: str) -> list[dict[str, str]]:
        rows = self._connection.execute(
            "SELECT role, content FROM messages WHERE session_id = ? ORDER BY sequence",
            (session_id,),
        ).fetchall()
        return [{"role": row["role"], "content": row["content"]} for row in rows]

    def list_sessions(self, limit: int = 20) -> list[SessionSummary]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        rows = self._connection.execute(
            """
            SELECT s.id, s.title, s.created_at, s.updated_at, COUNT(m.id) AS message_count
            FROM sessions AS s
            LEFT JOIN messages AS m ON m.session_id = s.id
            GROUP BY s.id
            ORDER BY s.updated_at DESC, s.rowid DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [SessionSummary(**dict(row)) for row in rows]

    def latest_session_id(self) -> str | None:
        row = self._connection.execute(
            "SELECT id FROM sessions ORDER BY updated_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return str(row["id"]) if row else None

    def delete_session(self, session_id: str) -> bool:
        with self._connection:
            cursor = self._connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cursor.rowcount > 0

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> SessionDB:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
