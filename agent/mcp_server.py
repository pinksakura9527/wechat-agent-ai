"""MCP server exposing llmadb capabilities as tools.

The server is a thin adapter: validate arguments, ask the permission guard,
delegate to the llmadb runner, and return compact text (never raw uiautomator
XML or full-resolution screenshots). Screenshots are returned as MCP image
content, already downscaled and grid-annotated by llmadb.

Run standalone with::

    python -m agent.mcp_server

It speaks MCP over stdio, so stdout is reserved for protocol frames; all
diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import Image, MCPServer

from agent.llmadb import LLMadbRunner
from agent.permissions import PermissionDenied, PermissionGuard, load_permission_config
from agent.tools import TOOL_CATALOG
from config.settings import AppSettings

SERVER_NAME = "wechat-agent"
SERVER_VERSION = "0.1.0"
INSTRUCTIONS = (
    "Tools for driving WeChat inside an Android emulator through llmadb. "
    "Prefer get_ui + tap by index/text; use screenshot only when the UI tree "
    "cannot describe the screen. Every action returns the updated compact UI."
)


def _execute(runner: LLMadbRunner, guard: PermissionGuard, tool: str, arguments: dict[str, Any]) -> str:
    try:
        guard.check(tool, arguments)
    except PermissionDenied as exc:
        return json.dumps(exc.as_tool_error(), ensure_ascii=False)
    result = runner.call(tool, arguments)
    if result.ok:
        return result.text
    return json.dumps(result.as_tool_error(), ensure_ascii=False)


def build_server(runner: LLMadbRunner, guard: PermissionGuard) -> MCPServer:
    """Create an MCPServer with every catalogue tool registered."""
    server = MCPServer(SERVER_NAME, version=SERVER_VERSION, instructions=INSTRUCTIONS)

    def spec(name: str) -> Any:
        return TOOL_CATALOG[name]

    @server.tool(name="get_ui", description=spec("get_ui").summary)
    def get_ui(full: bool = False) -> str:
        return _execute(runner, guard, "get_ui", {"full": full})

    @server.tool(name="device_status", description=spec("device_status").summary)
    def device_status() -> str:
        return _execute(runner, guard, "device_status", {})

    @server.tool(name="current_app", description=spec("current_app").summary)
    def current_app() -> str:
        return _execute(runner, guard, "current_app", {})

    @server.tool(name="tap", description=spec("tap").summary)
    def tap(
        index: int | None = None,
        text: str | None = None,
        element_id: str | None = None,
        x: int | None = None,
        y: int | None = None,
        hold_ms: int | None = None,
    ) -> str:
        arguments: dict[str, Any] = {}
        if index is not None:
            arguments["index"] = index
        if text:
            arguments["text"] = text
        if element_id:
            arguments["id"] = element_id
        if x is not None and y is not None:
            arguments["x"], arguments["y"] = x, y
        if hold_ms is not None:
            arguments["hold_ms"] = hold_ms
        return _execute(runner, guard, "tap", arguments)

    @server.tool(name="type_text", description=spec("type_text").summary)
    def type_text(text: str, enter: bool = True, clear: bool = False) -> str:
        return _execute(runner, guard, "type_text", {"text": text, "enter": enter, "clear": clear})

    @server.tool(name="screenshot", description=spec("screenshot").summary, structured_output=False)
    def screenshot(ocr: bool = False) -> Any:
        try:
            guard.check("screenshot", {"ocr": ocr})
        except PermissionDenied as exc:
            return json.dumps(exc.as_tool_error(), ensure_ascii=False)
        result = runner.call("screenshot", {"ocr": ocr})
        if not result.ok:
            return json.dumps(result.as_tool_error(), ensure_ascii=False)
        if result.image_path and Path(result.image_path).is_file():
            return Image(path=result.image_path)
        return result.text

    @server.tool(name="launch_app", description=spec("launch_app").summary)
    def launch_app(package: str) -> str:
        return _execute(runner, guard, "launch_app", {"package": package})

    @server.tool(name="swipe", description=spec("swipe").summary)
    def swipe(direction: str | None = None, start: str | None = None, end: str | None = None) -> str:
        arguments: dict[str, Any] = {}
        if direction:
            arguments["direction"] = direction
        if start and end:
            arguments["start"], arguments["end"] = start, end
        return _execute(runner, guard, "swipe", arguments)

    @server.tool(name="key", description=spec("key").summary)
    def key(name: str) -> str:
        return _execute(runner, guard, "key", {"name": name})

    @server.tool(name="wait_for", description=spec("wait_for").summary)
    def wait_for(
        text: str | None = None,
        element_id: str | None = None,
        gone: str | None = None,
        timeout_ms: int = 5000,
    ) -> str:
        arguments: dict[str, Any] = {"timeout_ms": timeout_ms}
        if text:
            arguments["text"] = text
        if element_id:
            arguments["id"] = element_id
        if gone:
            arguments["gone"] = gone
        return _execute(runner, guard, "wait_for", arguments)

    @server.tool(name="shell", description=spec("shell").summary)
    def shell(command: str) -> str:
        return _execute(runner, guard, "shell", {"command": command})

    @server.tool(name="install", description=spec("install").summary)
    def install(apk_path: str) -> str:
        return _execute(runner, guard, "install", {"apk_path": apk_path})

    @server.tool(name="uninstall", description=spec("uninstall").summary)
    def uninstall(package: str) -> str:
        return _execute(runner, guard, "uninstall", {"package": package})

    @server.tool(name="pull", description=spec("pull").summary)
    def pull(remote: str, local: str | None = None) -> str:
        arguments: dict[str, Any] = {"remote": remote}
        if local:
            arguments["local"] = local
        return _execute(runner, guard, "pull", arguments)

    @server.tool(name="push", description=spec("push").summary)
    def push(local: str, remote: str) -> str:
        return _execute(runner, guard, "push", {"local": local, "remote": remote})

    @server.tool(name="clear_data", description=spec("clear_data").summary)
    def clear_data(package: str) -> str:
        return _execute(runner, guard, "clear_data", {"package": package})

    @server.tool(name="force_stop", description=spec("force_stop").summary)
    def force_stop(package: str) -> str:
        return _execute(runner, guard, "force_stop", {"package": package})

    return server


def main(argv: list[str] | None = None) -> int:
    """Start the MCP server over stdio using the saved settings."""
    settings = AppSettings.load()
    permissions = load_permission_config()
    runner = LLMadbRunner(
        llmadb=settings.runtime.llmadb_path or None,
        adb=settings.runtime.adb_path or None,
        serial=settings.runtime.device_serial or None,
        max_lines=max(20, settings.runtime.max_steps * 10),
    )
    server = build_server(runner, PermissionGuard(permissions))
    print(
        f"[{SERVER_NAME}] llmadb={runner.executable or 'not found'} adb={runner.adb or 'not found'}",
        file=sys.stderr,
    )
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
