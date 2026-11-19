"""Export and import of a chat session as portable JSON.

Export format (version 1)::

    {
      "format": "wechat-agent-memory",
      "version": 1,
      "exported_at": "2026-01-31T08:00:00Z",
      "persona": "...markdown...",
      "permissions": { "version": 1, "allowed_tools": [...], "denied_tools": [...] },
      "session": { "session_id": "...", "title": "...", "created_at": "...", "updated_at": "..." },
      "messages": [ { "role": "user", "content": "...", "created_at": "..." }, ... ],
      "actions":  [ { "tool_name": "get_ui", "arguments": {...}, "result_summary": "...",
                      "status": "ok", "created_at": "..." }, ... ]
    }

Imports never overwrite the live conversation: `new_session` creates a new
session id, `merge_current` appends into an existing one. The caller
decides what to do with the imported persona/permissions.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from memory.db import MemoryStore, utc_now

ImportMode = Literal["new_session", "merge_current"]

FORMAT_NAME = "wechat-agent-memory"
FORMAT_VERSION = 1
VALID_ROLES = {"system", "user", "assistant", "tool"}
VALID_STATUSES = {"ok", "error", "denied"}


class MemoryFormatError(ValueError):
    """The file is not a valid WeChat Agent memory export."""


# --------------------------------------------------------------------------- #
# Export
# --------------------------------------------------------------------------- #
def export_session(
    store: MemoryStore,
    session_id: str,
    target: Path | str,
    *,
    persona: str,
    permissions: dict[str, Any],
) -> Path:
    """Write one session to a JSON file and return the written path."""
    session = store.get_session(session_id)
    if session is None:
        raise KeyError(f"unknown session: {session_id}")
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "exported_at": utc_now(),
        "persona": persona or session.persona_snapshot,
        "permissions": permissions,
        "session": {
            "session_id": session.session_id,
            "title": session.title,
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        },
        "messages": [
            {
                "role": record.role,
                "content": record.content,
                "tool_calls_json": record.tool_calls_json,
                "tool_call_id": record.tool_call_id,
                "created_at": record.created_at,
            }
            for record in store.list_messages(session_id)
        ],
        "actions": [
            {
                "tool_name": record.tool_name,
                "arguments": _load_json(record.arguments_json, {}),
                "result_summary": record.result_summary,
                "status": record.status,
                "created_at": record.created_at,
            }
            for record in store.list_actions(session_id)
        ],
    }

    destination = Path(target)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    fd, tmp = tempfile.mkstemp(dir=str(destination.parent), suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text + "\n")
        os.replace(tmp, destination)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return destination


# --------------------------------------------------------------------------- #
# Import
# --------------------------------------------------------------------------- #
def load_export(source: Path | str) -> dict[str, Any]:
    """Read and validate an export file."""
    path = Path(source)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise MemoryFormatError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise MemoryFormatError(f"{path} is not valid JSON: {exc}") from exc
    _validate(payload)
    return payload


def import_session(
    store: MemoryStore,
    source: Path | str,
    *,
    mode: ImportMode = "new_session",
    current_session_id: str | None = None,
) -> dict[str, Any]:
    """Load an export into the database.

    Returns a summary dict with the target session id and imported counts.
    """
    if mode not in ("new_session", "merge_current"):
        raise ValueError(f"unknown import mode: {mode}")
    payload = load_export(source)

    if mode == "merge_current":
        if not current_session_id:
            raise ValueError("merge_current requires current_session_id")
        session = store.get_session(current_session_id)
        if session is None:
            raise KeyError(f"unknown session: {current_session_id}")
        target_session_id = current_session_id
    else:
        title = payload.get("session", {}).get("title") or "导入的会话"
        session = store.create_session(title=f"导入：{title}", persona_snapshot=payload["persona"])
        target_session_id = session.session_id

    message_count = 0
    for message in payload["messages"]:
        store.add_message(
            session_id=target_session_id,
            role=message["role"],
            content=message.get("content") or "",
            tool_calls_json=message.get("tool_calls_json"),
            tool_call_id=message.get("tool_call_id"),
            created_at=message.get("created_at"),
        )
        message_count += 1

    action_count = 0
    for action in payload["actions"]:
        store.add_action(
            session_id=target_session_id,
            tool_name=action["tool_name"],
            arguments=action.get("arguments") or {},
            result_summary=action.get("result_summary") or "",
            status=action.get("status") or "ok",
            created_at=action.get("created_at"),
        )
        action_count += 1

    return {
        "session_id": target_session_id,
        "mode": mode,
        "title": session.title,
        "messages": message_count,
        "actions": action_count,
        "persona": payload["persona"],
        "permissions": payload["permissions"],
        "exported_at": payload.get("exported_at"),
    }


# --------------------------------------------------------------------------- #
# Validation helpers
# --------------------------------------------------------------------------- #
def _validate(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise MemoryFormatError("export must be a JSON object")
    if payload.get("format") != FORMAT_NAME:
        raise MemoryFormatError(f"unexpected format: {payload.get('format')!r}")
    if payload.get("version") != FORMAT_VERSION:
        raise MemoryFormatError(f"unsupported version: {payload.get('version')!r}")
    if not isinstance(payload.get("persona"), str):
        raise MemoryFormatError("'persona' must be a string")
    if not isinstance(payload.get("permissions"), dict):
        raise MemoryFormatError("'permissions' must be an object")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise MemoryFormatError("'messages' must be a list")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise MemoryFormatError(f"messages[{index}] must be an object")
        if message.get("role") not in VALID_ROLES:
            raise MemoryFormatError(f"messages[{index}] has invalid role")
        if not isinstance(message.get("content"), str):
            raise MemoryFormatError(f"messages[{index}] content must be a string")
    actions = payload.get("actions")
    if not isinstance(actions, list):
        raise MemoryFormatError("'actions' must be a list")
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise MemoryFormatError(f"actions[{index}] must be an object")
        if not isinstance(action.get("tool_name"), str) or not action["tool_name"]:
            raise MemoryFormatError(f"actions[{index}] has no tool_name")
        if action.get("status") not in VALID_STATUSES:
            raise MemoryFormatError(f"actions[{index}] has invalid status")


def _load_json(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback
