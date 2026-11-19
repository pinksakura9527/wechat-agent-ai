"""Permission guard configuration.

Phase 1 defines the schema and loading rules; phase 2 implements
`PermissionGuard.check()`, which runs before every tool call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.tools import TOOL_CATALOG


class PermissionDenied(RuntimeError):
    """Raised when the model requests a tool the user did not allow."""

    def __init__(self, tool_name: str, reason: str) -> None:
        super().__init__(f"tool '{tool_name}' denied: {reason}")
        self.tool_name = tool_name
        self.reason = reason

    def as_tool_error(self) -> dict[str, Any]:
        """Structured error the agent loop sends back to the model."""
        return {
            "ok": False,
            "error": "permission_denied",
            "tool": self.tool_name,
            "reason": self.reason,
        }


@dataclass
class PermissionConfig:
    """Which tools the model may call.

    `denied_tools` always wins over `allowed_tools`; unknown tool names are
    rejected at load time so a typo cannot silently widen access.
    """

    allowed_tools: set[str] = field(default_factory=set)
    denied_tools: set[str] = field(default_factory=set)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PermissionConfig:
        allowed = set(raw.get("allowed_tools", []))
        denied = set(raw.get("denied_tools", []))
        return cls(allowed_tools=allowed, denied_tools=denied).validated()

    @classmethod
    def load(cls, path: Path) -> PermissionConfig:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def validated(self) -> PermissionConfig:
        unknown = (self.allowed_tools | self.denied_tools) - set(TOOL_CATALOG)
        if unknown:
            raise ValueError(f"unknown tools in permission config: {sorted(unknown)}")
        # A tool may appear in both lists: the deny list wins at check time.
        return self

    @property
    def dangerous_tools(self) -> set[str]:
        """Tools flagged dangerous in the catalogue (derived, never configured)."""
        return {name for name, spec in TOOL_CATALOG.items() if spec.category == "dangerous"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "allowed_tools": sorted(self.allowed_tools),
            "denied_tools": sorted(self.denied_tools),
            "dangerous_tools": sorted(self.dangerous_tools),
        }

    def is_allowed(self, tool_name: str) -> bool:
        return tool_name in self.allowed_tools and tool_name not in self.denied_tools

    def summary_lines(self) -> list[str]:
        """Short permission digest injected into the system prompt."""
        lines = [f"- allowed: {', '.join(sorted(self.allowed_tools)) or '(none)'}"]
        if self.denied_tools:
            lines.append(f"- denied: {', '.join(sorted(self.denied_tools))}")
        return lines


def load_permission_config(path: Path | None = None) -> PermissionConfig:
    """Load the user's permissions, falling back to the bundled defaults."""
    from config.settings import bundled_file, permissions_path

    candidate = Path(path) if path is not None else permissions_path()
    if candidate.is_file():
        try:
            return PermissionConfig.load(candidate)
        except (OSError, ValueError):
            pass
    default = bundled_file("permissions.default.json")
    return PermissionConfig.load(default)


class PermissionGuard:
    """Checks every tool call against the current permission config."""

    def __init__(self, config: PermissionConfig) -> None:
        self._config = config

    @property
    def config(self) -> PermissionConfig:
        return self._config

    def update(self, config: PermissionConfig) -> None:
        """Swap the policy at runtime (used by the permissions panel)."""
        self._config = config

    def check(self, tool_name: str, arguments: dict[str, Any] | None = None) -> None:
        """Raise PermissionDenied when the call is not allowed.

        Order matters: unknown tools, then explicit denials, then the allow
        list. Any exception type other than PermissionDenied would be a bug,
        so the agent loop lets it propagate.
        """
        _ = arguments  # reserved for future argument-level policies
        if tool_name not in TOOL_CATALOG:
            raise PermissionDenied(tool_name, "unknown_tool")
        if tool_name in self._config.denied_tools:
            raise PermissionDenied(tool_name, "explicitly_denied")
        if tool_name not in self._config.allowed_tools:
            raise PermissionDenied(tool_name, "not_allowed")

    def allows(self, tool_name: str) -> bool:
        try:
            self.check(tool_name)
        except PermissionDenied:
            return False
        return True
