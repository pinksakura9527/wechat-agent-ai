-- Schema for the local chat memory database.
-- Timestamps are ISO-8601 UTC strings ("2026-01-31T08:00:00Z").
-- Applied by memory/db.py on startup; every statement is idempotent.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sessions (
    session_id        TEXT PRIMARY KEY,
    title             TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    persona_snapshot  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
    content         TEXT NOT NULL DEFAULT '',
    tool_calls_json TEXT,
    tool_call_id    TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session
    ON messages (session_id, id);

CREATE TABLE IF NOT EXISTS actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
    tool_name       TEXT NOT NULL,
    arguments_json  TEXT NOT NULL DEFAULT '{}',
    result_summary  TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'error', 'denied')),
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_actions_session
    ON actions (session_id, id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
