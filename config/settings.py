"""Application settings and on-disk locations.

All user-specific data (API key, persona, chat database) lives in a single
per-user directory so that the repository never contains secrets:

    Windows: %APPDATA%/WeChatAgentAI
    macOS:   ~/Library/Application Support/WeChatAgentAI
    Linux:   ~/.local/share/WeChatAgentAI

Environment overrides (useful for tests and portable installs):

    WECHAT_AGENT_HOME    overrides the whole data directory
    WECHAT_AGENT_CONFIG  overrides the settings file path
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

APP_NAME = "WeChatAgentAI"
SETTINGS_FILE = "settings.json"
PERSONA_FILE = "persona.md"
PERMISSIONS_FILE = "permissions.json"
DATABASE_FILE = "memory.db"

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def user_data_dir() -> Path:
    """Return the per-user data directory, creating it if needed."""
    override = os.environ.get("WECHAT_AGENT_HOME")
    if override:
        path = Path(override).expanduser()
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    override = os.environ.get("WECHAT_AGENT_CONFIG")
    return Path(override).expanduser() if override else user_data_dir() / SETTINGS_FILE


def persona_path() -> Path:
    return user_data_dir() / PERSONA_FILE


def permissions_path() -> Path:
    return user_data_dir() / PERMISSIONS_FILE


def database_path() -> Path:
    return user_data_dir() / DATABASE_FILE


def bundled_file(name: str) -> Path:
    """Path to a read-only default file shipped inside the `config/` package."""
    return Path(__file__).resolve().parent / name


@dataclass
class ApiConfig:
    """OpenAI-compatible chat-completions endpoint configuration."""

    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    max_tokens: int = 2048
    temperature: float = 0.7
    timeout_seconds: float = 60.0

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not self.base_url.startswith(("http://", "https://")):
            problems.append("base_url must start with http:// or https://")
        if not self.model.strip():
            problems.append("model must not be empty")
        if self.max_tokens <= 0:
            problems.append("max_tokens must be positive")
        if not 0.0 <= self.temperature <= 2.0:
            problems.append("temperature must be within [0, 2]")
        return problems


@dataclass
class RuntimeConfig:
    """Device and agent-loop runtime knobs."""

    adb_path: str = ""            # empty = resolve from PATH / ANDROID_HOME
    llmadb_path: str = ""         # empty = resolve from PATH / installed console script
    device_serial: str = ""       # empty = let llmadb pick the only device
    max_steps: int = 12           # tool-call loop budget per user instruction
    step_delay_ms: tuple[int, int] = (300, 900)  # human-like pacing (min, max)
    screenshot_max_width: int = 720
    send_screenshots: bool = True  # feed screenshots to vision models
    unicode_input: bool = True     # use ADBKeyboard for non-ASCII text when installed

    def validate(self) -> list[str]:
        problems: list[str] = []
        if self.max_steps <= 0:
            problems.append("max_steps must be positive")
        low, high = self.step_delay_ms
        if low < 0 or high < low:
            problems.append("step_delay_ms must satisfy 0 <= min <= max")
        return problems


@dataclass
class AppSettings:
    """Root settings object persisted as JSON."""

    api: ApiConfig = field(default_factory=ApiConfig)
    runtime: RuntimeConfig = field(default_factory=RuntimeConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> AppSettings:
        """Load settings, falling back to defaults on missing/corrupt files."""
        target = path or settings_path()
        if not target.exists():
            return cls()
        try:
            raw: dict[str, Any] = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        try:
            api = ApiConfig(**{**asdict(ApiConfig()), **raw.get("api", {})})
            runtime = RuntimeConfig(**{**asdict(RuntimeConfig()), **raw.get("runtime", {})})
            low, high = runtime.step_delay_ms
            runtime.step_delay_ms = (int(low), int(high))
        except (TypeError, ValueError):
            # Unknown fields or wrong types: fall back to safe defaults.
            return cls()
        return cls(api=api, runtime=runtime)

    def save(self, path: Path | None = None) -> Path:
        """Persist settings atomically and return the written path."""
        target = path or settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(dir=str(target.parent), suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(payload + "\n")
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        return target

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["runtime"]["step_delay_ms"] = list(self.runtime.step_delay_ms)
        return data

    def validate(self) -> list[str]:
        return self.api.validate() + self.runtime.validate()
