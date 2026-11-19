"""SQLite access for sessions, messages and action logs.

The rest of the application sees typed records only; raw SQL stays here.
Connections are opened lazily with `check_same_thread=False` because the
agent loop may run in a worker thread while the UI reads on the main thread;
a re-entrant lock serialises writes.

Timestamps are ISO-8601 UTC strings with a trailing "Z", e.g.
`2026-01-31T08:00:00Z`, so exports stay human-readable and sortable.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
DEFAULT_HISTORY_LIMIT = 40


def utc_now() -> str:
    """Current time as a second-precision ISO-8601 UTC string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_session_id() -> str:
    return "s-{}".format(uuid.uuid4().hex[:16])


@dataclass(frozen=True)
class SessionRecord:
    session_id: str
    title: str
    created_at: str
    updated_at: str
    persona_snapshot: str


@dataclass(frozen=True)
class MessageRecord:
    id: int
    session_id: str
    role: str
    content: str
    tool_calls_json: str | None
    tool_call_id: str | None
    created_at: str

    def to_llm_message(self) -> dict[str, Any]:
        """Convert to the message dict expected by chat-completions APIs."""
        message: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls_json:
            try:
                message["tool_calls"] = json.loads(self.tool_calls_json)
            except json.JSONDecodeError:
                pass
        if self.tool_call_id:
            message["tool_call_id"] = self.tool_call_id
        return message


@dataclass(frozen=True)
class ActionRecord:
    id: int
    session_id: str
    tool_name: str
    arguments_json: str
    result_summary: str
    status: str
    created_at: str


class MemoryStore:
    """Repository over the SQLite database.

    Implements the `MemorySink` protocol used by `agent.loop.AgentLoop`:
    `add_message` and `add_action`.
    """

    def __init__(self, database: Path | str | None = None) -> None:
        if database is None:
            from config.settings import database_path

            database = database_path()
        self._database = Path(database)
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    # ------------------------------------------------------------- lifecycle
    @property
    def database(self) -> Path:
        return self._database

    def connect(self) -> sqlite3.Connection:
        with self._lock:
            if self._connection is None:
                self._database.parent.mkdir(parents=True, exist_ok=True)
                connection = sqlite3.connect(str(self._database), check_same_thread=False)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                connection.commit()
                self._connection = connection
            return self._connection

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def __enter__(self) -> MemoryStore:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # --------------------------------------------------------------- sessions
    def create_session(
        self,
        *,
        title: str = "新会话",
        persona_snapshot: str = "",
        session_id: str | None = None,
    ) -> SessionRecord:
        session = SessionRecord(
            session_id=session_id or new_session_id(),
            title=title,
            created_at=utc_now(),
            updated_at=utc_now(),
            persona_snapshot=persona_snapshot,
        )
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO sessions (session_id, title, created_at, updated_at, persona_snapshot)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    session.session_id,
                    session.title,
                    session.created_at,
                    session.updated_at,
                    session.persona_snapshot,
                ),
            )
            connection.commit()
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        row = self.connect().execute(
            "SELECT session_id, title, created_at, updated_at, persona_snapshot"
            " FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return _session_from_row(row) if row else None

    def ensure_session(self, session_id: str, *, persona: str = "") -> SessionRecord:
        existing = self.get_session(session_id)
        if existing is not None:
            return existing
        return self.create_session(session_id=session_id, persona_snapshot=persona)

    def list_sessions(self, limit: int = 50) -> list[SessionRecord]:
        rows = self.connect().execute(
            "SELECT session_id, title, created_at, updated_at, persona_snapshot"
            " FROM sessions ORDER BY updated_at DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [_session_from_row(row) for row in rows]

    def update_persona_snapshot(self, session_id: str, persona: str) -> None:
        with self._lock, self.connect() as connection:
            connection.execute(
                "UPDATE sessions SET persona_snapshot = ?, updated_at = ? WHERE session_id = ?",
                (persona, utc_now(), session_id),
            )
            connection.commit()

    def delete_session(self, session_id: str) -> bool:
        with self._lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            connection.commit()
            return cursor.rowcount > 0

    # --------------------------------------------------------------- messages
    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        tool_calls_json: str | None = None,
        tool_call_id: str | None = None,
        created_at: str | None = None,
    ) -> int:
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"invalid message role: {role}")
        now = created_at or utc_now()
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls_json, tool_call_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, role, content, tool_calls_json, tool_call_id, now),
            )
            connection.execute(
                "UPDATE sessions SET updated_at = ? WHERE session_id = ?", (now, session_id)
            )
            connection.commit()
            return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])

    def list_messages(self, session_id: str, limit: int | None = None) -> list[MessageRecord]:
        base = (
            "SELECT id, session_id, role, content, tool_calls_json, tool_call_id, created_at"
            " FROM messages WHERE session_id = ? ORDER BY id DESC"
        )
        if limit is not None:
            base += " LIMIT {}".format(max(1, int(limit)))
        rows = self.connect().execute(base, (session_id,)).fetchall()
        return [MessageRecord(**dict(row)) for row in reversed(rows)]

    def count_messages(self, session_id: str) -> int:
        row = self.connect().execute(
            "SELECT COUNT(*) AS n FROM messages WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"])

    def session_history(
        self, session_id: str, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> list[dict[str, Any]]:
        """Recent messages as chat-completions dicts (oldest first)."""
        return [record.to_llm_message() for record in self.list_messages(session_id, limit=limit)]

    # ---------------------------------------------------------------- actions
    def add_action(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result_summary: str,
        status: str = "ok",
        created_at: str | None = None,
    ) -> int:
        if status not in {"ok", "error", "denied"}:
            raise ValueError(f"invalid action status: {status}")
        now = created_at or utc_now()
        with self._lock, self.connect() as connection:
            connection.execute(
                "INSERT INTO actions (session_id, tool_name, arguments_json, result_summary, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    tool_name,
                    json.dumps(arguments or {}, ensure_ascii=False),
                    result_summary,
                    status,
                    now,
                ),
            )
            connection.commit()
            return int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])

    def list_actions(self, session_id: str, limit: int | None = None) -> list[ActionRecord]:
        base = (
            "SELECT id, session_id, tool_name, arguments_json, result_summary, status, created_at"
            " FROM actions WHERE session_id = ? ORDER BY id DESC"
        )
        if limit is not None:
            base += " LIMIT {}".format(max(1, int(limit)))
        rows = self.connect().execute(base, (session_id,)).fetchall()
        return [ActionRecord(**dict(row)) for row in reversed(rows)]

    def count_actions(self, session_id: str) -> int:
        row = self.connect().execute(
            "SELECT COUNT(*) AS n FROM actions WHERE session_id = ?", (session_id,)
        ).fetchone()
        return int(row["n"])


def _session_from_row(row: sqlite3.Row) -> SessionRecord:
    return SessionRecord(
        session_id=row["session_id"],
        title=row["title"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        persona_snapshot=row["persona_snapshot"] or "",
    )
