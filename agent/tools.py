"""Declarative catalogue of the tools exposed to the LLM.

A single catalogue feeds three consumers:

* the MCP server (tool schemas),
* the permission guard (which tool is allowed),
* the agent loop (how to turn a call into an `llmadb` invocation).

Phase 1 only defines the data model and the catalogue; execution is wired in
phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ToolCategory = Literal["read", "interact", "dangerous"]


@dataclass(frozen=True)
class ToolSpec:
    """A tool callable by the model."""

    name: str
    summary: str
    category: ToolCategory
    parameters: dict[str, Any] = field(default_factory=dict)
    requires_device: bool = True

    def mcp_schema(self) -> dict[str, Any]:
        """JSON schema in the shape expected by MCP / OpenAI tool calling."""
        return {
            "name": self.name,
            "description": self.summary,
            "inputSchema": self.parameters or {"type": "object", "properties": {}},
        }


TOOL_CATALOG: dict[str, ToolSpec] = {
    "get_ui": ToolSpec(
        name="get_ui",
        summary="Dump the current screen as a reduced, indexed UI tree (llmadb ui).",
        category="read",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "tap": ToolSpec(
        name="tap",
        summary=(
            "Tap an element by index from get_ui, by visible text, or by x,y coordinates. "
            "Returns the updated UI tree."
        ),
        category="interact",
        parameters={
            "type": "object",
            "properties": {
                "index": {"type": "integer", "description": "Element index from the last get_ui."},
                "text": {"type": "string", "description": "Visible text to tap."},
                "x": {"type": "integer", "description": "X coordinate (pair with y)."},
                "y": {"type": "integer", "description": "Y coordinate (pair with x)."},
                "hold_ms": {"type": "integer", "description": "Optional long-press duration."},
            },
            "additionalProperties": False,
        },
    ),
    "type_text": ToolSpec(
        name="type_text",
        summary="Type text into the focused input field; optionally press Enter to send.",
        category="interact",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type."},
                "enter": {"type": "boolean", "default": True, "description": "Press Enter after typing."},
                "clear": {"type": "boolean", "default": False, "description": "Clear the field first."},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    ),
    "screenshot": ToolSpec(
        name="screenshot",
        summary="Capture a downscaled screenshot with a 100px coordinate grid (llmadb screen).",
        category="read",
        parameters={
            "type": "object",
            "properties": {
                "ocr": {"type": "boolean", "default": False, "description": "Ask llmadb to OCR the frame."},
            },
            "additionalProperties": False,
        },
    ),
    "launch_app": ToolSpec(
        name="launch_app",
        summary="Launch an app by package name, e.g. com.tencent.mm for WeChat.",
        category="interact",
        parameters={
            "type": "object",
            "properties": {"package": {"type": "string", "description": "Android package name."}},
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    "device_status": ToolSpec(
        name="device_status",
        summary="Report emulator connectivity and battery status (llmadb status).",
        category="read",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "swipe": ToolSpec(
        name="swipe",
        summary="Scroll or swipe in a direction, or between two points.",
        category="interact",
        parameters={
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down", "left", "right"]},
                "start": {"type": "string", "description": "x1,y1"},
                "end": {"type": "string", "description": "x2,y2"},
            },
            "additionalProperties": False,
        },
    ),
    "key": ToolSpec(
        name="key",
        summary="Press a hardware/navigation key such as back, home or enter.",
        category="interact",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Key name."}},
            "required": ["name"],
            "additionalProperties": False,
        },
    ),
    "wait_for": ToolSpec(
        name="wait_for",
        summary="Poll the UI until given text or an element id appears (or disappears).",
        category="read",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "id": {"type": "string"},
                "gone": {"type": "boolean", "default": False},
                "timeout_ms": {"type": "integer", "default": 5000},
            },
            "additionalProperties": False,
        },
    ),
    "current_app": ToolSpec(
        name="current_app",
        summary="Report the foreground package/activity and keyboard state.",
        category="read",
        parameters={"type": "object", "properties": {}, "additionalProperties": False},
    ),
    "shell": ToolSpec(
        name="shell",
        summary=(
            "DANGEROUS: pass an arbitrary command through llmadb to adb. "
            "Denied by default; may exfiltrate data."
        ),
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
            "additionalProperties": False,
        },
    ),
    "install": ToolSpec(
        name="install",
        summary="DANGEROUS: install an APK on the device. Denied by default.",
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"apk_path": {"type": "string"}},
            "required": ["apk_path"],
            "additionalProperties": False,
        },
    ),
    "uninstall": ToolSpec(
        name="uninstall",
        summary="DANGEROUS: uninstall an app. Denied by default.",
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    "pull": ToolSpec(
        name="pull",
        summary="DANGEROUS: copy a file from the device to the host. Denied by default.",
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"remote": {"type": "string"}, "local": {"type": "string"}},
            "required": ["remote"],
            "additionalProperties": False,
        },
    ),
    "push": ToolSpec(
        name="push",
        summary="DANGEROUS: copy a file from the host to the device. Denied by default.",
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"local": {"type": "string"}, "remote": {"type": "string"}},
            "required": ["local", "remote"],
            "additionalProperties": False,
        },
    ),
    "clear_data": ToolSpec(
        name="clear_data",
        summary="DANGEROUS: wipe an app's data (llmadb clear). Denied by default.",
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
    "force_stop": ToolSpec(
        name="force_stop",
        summary="DANGEROUS: force-stop an app (llmadb stop). Denied by default.",
        category="dangerous",
        parameters={
            "type": "object",
            "properties": {"package": {"type": "string"}},
            "required": ["package"],
            "additionalProperties": False,
        },
    ),
}


def openai_tools() -> list[dict[str, Any]]:
    """Tool schemas in the shape expected by chat-completions APIs."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.summary,
                "parameters": spec.parameters or {"type": "object", "properties": {}},
            },
        }
        for spec in TOOL_CATALOG.values()
    ]


def get_spec(name: str) -> ToolSpec:
    try:
        return TOOL_CATALOG[name]
    except KeyError as exc:
        raise KeyError(f"unknown tool: {name}") from exc


def spec_names() -> list[str]:
    return list(TOOL_CATALOG)


def specs_for(categories: set[str]) -> list[ToolSpec]:
    return [spec for spec in TOOL_CATALOG.values() if spec.category in categories]
