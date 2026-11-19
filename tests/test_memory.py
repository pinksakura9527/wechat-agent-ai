"""Memory layer tests: SQLite store plus JSON export/import."""

from __future__ import annotations

import json

import pytest

from memory.db import MemoryStore
from memory.transfer import (
    FORMAT_NAME,
    MemoryFormatError,
    export_session,
    import_session,
    load_export,
)


@pytest.fixture()
def store(tmp_path):
    database = MemoryStore(tmp_path / "memory.db")
    database.connect()
    yield database
    database.close()


def _session(store, title="测试会话", persona="你是一个助理"):
    return store.create_session(title=title, persona_snapshot=persona)


def _seed(store, session_id):
    store.add_message(session_id=session_id, role="user", content="给张三发消息")
    store.add_message(
        session_id=session_id,
        role="assistant",
        content="",
        tool_calls_json=json.dumps([{"id": "c1", "type": "function", "function": {"name": "get_ui"}}]),
    )
    store.add_message(session_id=session_id, role="tool", content="1 text 发送", tool_call_id="c1")
    store.add_action(
        session_id=session_id,
        tool_name="get_ui",
        arguments={"full": False},
        result_summary="12 lines",
        status="ok",
    )


def test_create_and_list_sessions(store):
    session = _session(store)
    assert session.session_id.startswith("s-")
    assert store.get_session(session.session_id).title == "测试会话"
    assert store.list_sessions()[0].session_id == session.session_id


def test_add_message_updates_counts_and_timestamp(store):
    session = _session(store)
    before = store.get_session(session.session_id)
    store.add_message(session_id=session.session_id, role="user", content="hi")
    assert store.count_messages(session.session_id) == 1
    after = store.get_session(session.session_id)
    assert after.updated_at >= before.updated_at


def test_message_limit_returns_latest_in_order(store):
    session = _session(store)
    for index in range(5):
        store.add_message(session_id=session.session_id, role="user", content=f"m{index}")
    messages = store.list_messages(session.session_id, limit=2)
    assert [m.content for m in messages] == ["m3", "m4"]


def test_history_includes_tool_call_id_and_calls(store):
    session = _session(store)
    _seed(store, session.session_id)
    history = store.session_history(session.session_id)
    assert [item["role"] for item in history] == ["user", "assistant", "tool"]
    assert history[1]["tool_calls"][0]["function"]["name"] == "get_ui"
    assert history[2]["tool_call_id"] == "c1"


def test_invalid_role_and_status_rejected(store):
    session = _session(store)
    with pytest.raises(ValueError):
        store.add_message(session_id=session.session_id, role="robot", content="x")
    with pytest.raises(ValueError):
        store.add_action(
            session_id=session.session_id,
            tool_name="get_ui",
            arguments={},
            result_summary="x",
            status="maybe",
        )


def test_export_writes_versioned_payload(store, tmp_path):
    session = _session(store)
    _seed(store, session.session_id)
    target = export_session(
        store,
        session.session_id,
        tmp_path / "out" / "session.json",
        persona="人设文本",
        permissions={"version": 1, "allowed_tools": ["get_ui"], "denied_tools": []},
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["format"] == FORMAT_NAME
    assert payload["persona"] == "人设文本"
    assert len(payload["messages"]) == 3
    assert payload["actions"][0]["arguments"] == {"full": False}


def test_export_unknown_session_raises(store, tmp_path):
    with pytest.raises(KeyError):
        export_session(store, "nope", tmp_path / "x.json", persona="", permissions={})


def test_import_creates_new_session_with_data(store, tmp_path):
    session = _session(store)
    _seed(store, session.session_id)
    source = export_session(store, session.session_id, tmp_path / "export.json", persona="导入人设", permissions={})

    summary = import_session(store, source, mode="new_session")

    assert summary["session_id"] != session.session_id
    assert summary["messages"] == 3
    assert summary["actions"] == 1
    assert store.count_messages(summary["session_id"]) == 3
    assert store.get_session(summary["session_id"]).persona_snapshot == "导入人设"
    imported = store.list_messages(summary["session_id"])
    assert imported[2].tool_call_id == "c1"
    assert imported[0].created_at == store.list_messages(session.session_id)[0].created_at


def test_import_merge_current_appends(store, tmp_path):
    original = _session(store)
    _seed(store, original.session_id)
    source = export_session(store, original.session_id, tmp_path / "export.json", persona="p", permissions={})

    current = _session(store, title="当前")
    summary = import_session(store, source, mode="merge_current", current_session_id=current.session_id)

    assert summary["session_id"] == current.session_id
    assert store.count_messages(current.session_id) == 3
    assert store.count_messages(original.session_id) == 3


def test_import_merge_requires_existing_session(store, tmp_path):
    session = _session(store)
    source = export_session(store, session.session_id, tmp_path / "e.json", persona="", permissions={})
    with pytest.raises(KeyError):
        import_session(store, source, mode="merge_current", current_session_id="missing")
    with pytest.raises(ValueError):
        import_session(store, source, mode="merge_current")


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(format="other"),
        lambda payload: payload.update(version=99),
        lambda payload: payload["messages"][0].update(role="robot"),
        lambda payload: payload["actions"][0].update(status="maybe"),
    ],
)
def test_invalid_exports_are_rejected(store, tmp_path, mutate):
    session = _session(store)
    _seed(store, session.session_id)
    source = export_session(store, session.session_id, tmp_path / "e.json", persona="", permissions={})
    payload = json.loads(source.read_text(encoding="utf-8"))
    mutate(payload)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(MemoryFormatError):
        load_export(bad)


def test_delete_session_cascades(store):
    session = _session(store)
    _seed(store, session.session_id)
    assert store.delete_session(session.session_id) is True
    assert store.get_session(session.session_id) is None
    assert store.count_messages(session.session_id) == 0
    assert store.count_actions(session.session_id) == 0


def test_ensure_session_is_idempotent(store):
    first = store.ensure_session("fixed-id", persona="p")
    second = store.ensure_session("fixed-id", persona="other")
    assert first.session_id == second.session_id
    assert second.persona_snapshot == "p"
