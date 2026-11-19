"""Phase 1 smoke tests: settings round-trip, tool catalogue, permission schema."""

from __future__ import annotations

import json

import pytest
from agent.tools import TOOL_CATALOG, get_spec, spec_names
from config.settings import AppSettings, bundled_file


def test_settings_roundtrip(tmp_path):
    target = tmp_path / "settings.json"
    settings = AppSettings()
    settings.api.api_key = "sk-test"
    settings.api.model = "test-model"
    settings.runtime.max_steps = 5
    settings.runtime.step_delay_ms = (100, 200)

    settings.save(target)
    loaded = AppSettings.load(target)

    assert loaded.api.api_key == "sk-test"
    assert loaded.api.model == "test-model"
    assert loaded.runtime.max_steps == 5
    assert loaded.runtime.step_delay_ms == (100, 200)


def test_settings_ignore_corrupt_file(tmp_path):
    target = tmp_path / "settings.json"
    target.write_text("{not json", encoding="utf-8")
    loaded = AppSettings.load(target)
    assert loaded.api.model  # falls back to defaults


def test_default_settings_validate():
    assert AppSettings().validate() == []


def test_tool_catalog_contains_required_tools():
    required = {"get_ui", "tap", "type_text", "screenshot", "launch_app", "device_status"}
    assert required <= set(spec_names())
    assert get_spec("shell").category == "dangerous"


def test_tool_schemas_are_well_formed():
    for spec in TOOL_CATALOG.values():
        schema = spec.mcp_schema()
        assert schema["name"] == spec.name
        assert schema["inputSchema"]["type"] == "object"


def test_default_permissions_are_valid_and_minimal():
    raw = json.loads(bundled_file("permissions.default.json").read_text(encoding="utf-8"))
    from agent.permissions import PermissionConfig

    config = PermissionConfig.from_dict(raw)
    assert config.is_allowed("get_ui")
    assert config.is_allowed("type_text")
    assert not config.is_allowed("shell")
    assert "shell" in config.denied_tools


def test_permission_config_rejects_unknown_tool():
    from agent.permissions import PermissionConfig

    with pytest.raises(ValueError):
        PermissionConfig.from_dict({"allowed_tools": ["not_a_tool"]})
