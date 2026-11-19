"""Permission guard tests."""

from __future__ import annotations

import pytest

from agent.permissions import (
    PermissionConfig,
    PermissionDenied,
    PermissionGuard,
    load_permission_config,
)


def _config(allowed, denied=()):
    return PermissionConfig.from_dict({"allowed_tools": list(allowed), "denied_tools": list(denied)})


def test_allowed_tool_passes():
    PermissionGuard(_config(["get_ui"])).check("get_ui")


def test_explicit_denial_wins_over_allow():
    guard = PermissionGuard(_config(["get_ui", "shell"], ["shell"]))
    with pytest.raises(PermissionDenied) as info:
        guard.check("shell")
    assert info.value.reason == "explicitly_denied"


def test_tool_not_in_allow_list_is_denied():
    guard = PermissionGuard(_config(["get_ui"]))
    with pytest.raises(PermissionDenied) as info:
        guard.check("tap")
    assert info.value.reason == "not_allowed"
    assert guard.allows("get_ui")
    assert not guard.allows("tap")


def test_unknown_tool_is_denied_even_if_allowed_list_mentions_it():
    config = PermissionConfig(allowed_tools={"get_ui"}, denied_tools=set())
    with pytest.raises(ValueError):
        PermissionConfig.from_dict({"allowed_tools": ["get_ui", "make_coffee"]})
    guard = PermissionGuard(config)
    with pytest.raises(PermissionDenied) as info:
        guard.check("make_coffee")
    assert info.value.reason == "unknown_tool"


def test_denied_error_is_structured():
    guard = PermissionGuard(_config(["get_ui"], ["shell"]))
    with pytest.raises(PermissionDenied) as info:
        guard.check("shell")
    payload = info.value.as_tool_error()
    assert payload == {
        "ok": False,
        "error": "permission_denied",
        "tool": "shell",
        "reason": "explicitly_denied",
    }


def test_load_permission_config_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_AGENT_HOME", str(tmp_path))
    config = load_permission_config()
    assert config.is_allowed("get_ui")
    assert not config.is_allowed("shell")


def test_load_permission_config_reads_user_file(tmp_path, monkeypatch):
    monkeypatch.setenv("WECHAT_AGENT_HOME", str(tmp_path))
    (tmp_path / "permissions.json").write_text(
        '{"version": 1, "allowed_tools": ["device_status"], "denied_tools": []}',
        encoding="utf-8",
    )
    config = load_permission_config()
    assert config.allowed_tools == {"device_status"}
