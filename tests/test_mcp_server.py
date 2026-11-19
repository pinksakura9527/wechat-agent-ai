"""MCP server wiring tests (no device)."""

from __future__ import annotations

import json

import anyio
from agent.llmadb import ToolResult
from agent.mcp_server import _execute, build_server
from agent.permissions import PermissionConfig, PermissionGuard
from agent.tools import TOOL_CATALOG


class FakeRunner:
    def __init__(self) -> None:
        self.calls = []

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return ToolResult(ok=True, tool=tool, text=f"{tool} ok")


def _guard(allowed=("get_ui",)):
    return PermissionGuard(PermissionConfig.from_dict({"allowed_tools": list(allowed)}))


def test_all_catalogue_tools_are_registered():
    server = build_server(FakeRunner(), _guard())
    tools = anyio.run(server.list_tools)
    names = {tool.name for tool in tools}
    assert names == set(TOOL_CATALOG)


def test_required_tools_present_with_schemas():
    server = build_server(FakeRunner(), _guard())
    tools = {tool.name: tool for tool in anyio.run(server.list_tools)}
    for required in ("get_ui", "tap", "type_text", "screenshot", "launch_app", "device_status"):
        assert required in tools
        assert tools[required].input_schema["type"] == "object"


def test_execute_respects_guard():
    runner = FakeRunner()
    payload = _execute(runner, _guard(), "shell", {"command": "ls"})
    assert json.loads(payload)["error"] == "permission_denied"
    assert runner.calls == []


def test_execute_returns_tool_text():
    runner = FakeRunner()
    assert _execute(runner, _guard(), "get_ui", {}) == "get_ui ok"
    assert runner.calls == [("get_ui", {})]
