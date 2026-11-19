"""Device execution layer: the only place that spawns `llmadb`.

Design rules
------------
* Every device interaction goes through the `llmadb` CLI (PyPI `llm-adb`).
  We never call `adb` directly, never parse uiautomator XML ourselves.
* The runner is synchronous and returns small dataclasses, so the UI can call
  it from a worker thread and tests can fake it without a device.
* Output is trimmed defensively: the model must never receive an unbounded
  dump, even if llmadb changes its formatting.
* Errors are parsed from llmadb's stable `error: <CODE> <message> | hint: <hint>`
  line so the agent loop can show the model *why* an action failed.
"""

from __future__ import annotations

import contextlib
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.tools import TOOL_CATALOG

DEFAULT_TIMEOUT = 30.0
MAX_OUTPUT_LINES = 120
MAX_OUTPUT_CHARS = 12_000
PROBE_TIMEOUT = 20.0

_ERROR_RE = re.compile(
    r"^error:\s+(?P<code>[A-Z][A-Z0-9_]*)\s+(?P<message>.*?)(?:\s+\|\s+hint:\s+(?P<hint>.*))?$"
)
_SCREEN_RE = re.compile(r"path=(?P<path>.+?)\s+size=(?P<size>\S+)")
RETRYABLE_TOOLS = {"get_ui", "screenshot", "device_status", "current_app", "wait_for"}
RETRY_DELAY_SECONDS = 0.6


# --------------------------------------------------------------------------- #
# Executable discovery
# --------------------------------------------------------------------------- #
def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _first_file(candidates: Sequence[Path | str | None]) -> str | None:
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return None


def find_llmadb(explicit: str | None = None) -> str | None:
    """Locate the llmadb console script (explicit path > PATH > venv)."""
    candidates: list[Path | str | None] = [explicit, shutil.which("llmadb")]
    scripts = Path(sys.executable).parent
    candidates += [
        _repo_root() / ".venv" / "Scripts" / "llmadb.exe",
        _repo_root() / ".venv" / "bin" / "llmadb",
        scripts / "llmadb.exe",
        scripts / "llmadb",
    ]
    return _first_file(candidates)


def find_adb(explicit: str | None = None) -> str | None:
    """Locate an adb-compatible binary (explicit > PATH > SDK > emulator bundles)."""
    candidates: list[Path | str | None] = [explicit, shutil.which("adb")]
    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "platform-tools" / "adb.exe")
            candidates.append(Path(base) / "platform-tools" / "adb")
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "Android" / "platform-tools" / "adb.exe")
    candidates += [
        Path.home() / "AppData" / "Local" / "Android" / "platform-tools" / "adb.exe",
        Path("C:/Android/Sdk/platform-tools/adb.exe"),
        Path("C:/Program Files/BlueStacks_nxt/HD-Adb.exe"),
        Path("C:/LDPlayer/LDPlayer9/adb.exe"),
        Path("C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe"),
        Path("/usr/local/bin/adb"),
        Path("/usr/bin/adb"),
    ]
    return _first_file(candidates)


# --------------------------------------------------------------------------- #
# Result types
# --------------------------------------------------------------------------- #
@dataclass
class LLMadbResult:
    """Raw result of one llmadb invocation."""

    ok: bool
    argv: list[str]
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0
    error_code: str | None = None
    hint: str | None = None
    duration_ms: int = 0

    def summary(self, limit: int = 400) -> str:
        text = self.stdout.strip() or self.stderr.strip() or "(no output)"
        return text if len(text) <= limit else text[:limit] + "..."


@dataclass
class ToolResult:
    """Result of one tool call, shaped for the model and the action log."""

    ok: bool
    tool: str
    text: str
    error_code: str | None = None
    hint: str | None = None
    image_path: str | None = None
    duration_ms: int = 0
    argv: list[str] = field(default_factory=list)

    def as_tool_error(self) -> dict[str, Any]:
        return {
            "ok": False,
            "error": self.error_code or "tool_failed",
            "tool": self.tool,
            "message": self.text,
            "hint": self.hint or "",
        }

    def summary(self, limit: int = 300) -> str:
        one_line = " ".join(self.text.split())
        return one_line if len(one_line) <= limit else one_line[:limit] + "..."


# --------------------------------------------------------------------------- #
# Output helpers
# --------------------------------------------------------------------------- #
def trim_output(text: str, max_lines: int = MAX_OUTPUT_LINES, max_chars: int = MAX_OUTPUT_CHARS) -> str:
    """Bound llmadb output so a single call cannot blow the context window."""
    lines = text.splitlines()
    truncated = False
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        truncated = True
    result = "\n".join(lines)
    if len(result) > max_chars:
        result = result[:max_chars]
        truncated = True
    if truncated:
        result += f"\n[truncated by wechat-agent to {max_lines} lines / {max_chars} chars]"
    return result


def parse_error(text: str) -> tuple[str | None, str, str]:
    """Split llmadb's error line into (code, message, hint)."""
    for raw_line in text.splitlines():
        match = _ERROR_RE.match(raw_line.strip())
        if match:
            return (
                match.group("code"),
                match.group("message").strip(),
                (match.group("hint") or "").strip(),
            )
    stripped = text.strip()
    return None, (stripped[:500] if stripped else "llmadb returned no output"), ""


def _android_input_escape(text: str) -> str:
    """Escape text for `adb shell input text` (space -> %s, shell metachars)."""
    escaped = text.replace(" ", "%s")
    for char in "&|;<>()$*?":  # keep the device shell from interpreting these
        escaped = escaped.replace(char, "\\" + char)
    return escaped


def _one_target(arguments: Mapping[str, Any]) -> str:
    index = arguments.get("index")
    text = arguments.get("text")
    element_id = arguments.get("id")
    x, y = arguments.get("x"), arguments.get("y")
    given = [name for name, value in (("index", index), ("text", text), ("id", element_id)) if value not in (None, "")]
    if x is not None or y is not None:
        if x is None or y is None:
            raise ValueError("tap requires both x and y when using coordinates")
        given.append("point")
    if len(given) != 1:
        raise ValueError("tap requires exactly one target: index, text, id, or x+y")
    return given[0]


def build_argv(tool: str, arguments: Mapping[str, Any] | None = None) -> list[str]:
    """Translate a tool call into an llmadb argument vector.

    Raised ValueError means the model sent an unusable argument set; the
    runner turns that into a structured error instead of crashing.
    """
    args: dict[str, Any] = dict(arguments or {})
    if tool not in TOOL_CATALOG:
        raise ValueError(f"unknown tool: {tool}")

    if tool == "get_ui":
        argv = ["ui"]
        if args.get("full"):
            argv.append("--full")
        return argv

    if tool == "device_status":
        return ["status"]

    if tool == "current_app":
        return ["current"]

    if tool == "tap":
        target = _one_target(args)
        if target == "index":
            argv = ["tap", str(int(args["index"]))]
        elif target == "text":
            argv = ["tap", "--text", str(args["text"])]
        elif target == "id":
            argv = ["tap", "--id", str(args["id"])]
        else:
            argv = ["tap", "{},{}".format(int(args["x"]), int(args["y"]))]
        if args.get("hold_ms") is not None:
            argv += ["--hold", str(int(args["hold_ms"]))]
        return argv

    if tool == "type_text":
        text = args.get("text")
        if not isinstance(text, str) or text == "":
            raise ValueError("type_text requires a non-empty text")
        if text.startswith("-"):
            # llmadb's CLI skips leading-dash positionals; use its documented
            # adb passthrough instead of silently typing the wrong thing.
            return ["--", "shell", "input", "text", _android_input_escape(text)]
        argv = ["type", text]
        if args.get("clear"):
            argv.append("--clear")
        if args.get("enter", True):
            argv.append("--enter")
        return argv

    if tool == "screenshot":
        argv = ["screen"]
        if args.get("ocr"):
            argv.append("--ocr")
        return argv

    if tool == "launch_app":
        package = args.get("package")
        if not package:
            raise ValueError("launch_app requires a package name")
        return ["launch", str(package)]

    if tool == "swipe":
        direction = args.get("direction")
        start, end = args.get("start"), args.get("end")
        if direction in {"up", "down", "left", "right"}:
            return ["swipe", str(direction)]
        if start and end:
            return ["swipe", str(start), str(end)]
        raise ValueError("swipe requires a direction or start/end points")

    if tool == "key":
        name = args.get("name")
        if not name:
            raise ValueError("key requires a key name")
        return ["key", str(name)]

    if tool == "wait_for":
        argv = ["wait-for"]
        if args.get("text"):
            argv += ["--text", str(args["text"])]
        elif args.get("id"):
            argv += ["--id", str(args["id"])]
        elif args.get("gone"):
            argv += ["--gone", str(args["gone"])]
        else:
            raise ValueError("wait_for requires text, id, or gone")
        if args.get("timeout_ms"):
            argv += ["--timeout", str(max(1, int(args["timeout_ms"]) // 1000))]
        return argv

    # ------------------------------------------------------------- dangerous
    if tool == "shell":
        command = args.get("command")
        if not command:
            raise ValueError("shell requires a command")
        return ["--", "shell", *shlex.split(str(command))]

    if tool == "install":
        apk = args.get("apk_path")
        if not apk:
            raise ValueError("install requires apk_path")
        return ["--", "install", str(apk)]

    if tool == "uninstall":
        package = args.get("package")
        if not package:
            raise ValueError("uninstall requires package")
        return ["--", "uninstall", str(package)]

    if tool == "pull":
        remote = args.get("remote")
        if not remote:
            raise ValueError("pull requires remote")
        remote_path = Path(str(remote))
        local = args.get("local") or remote_path.name or "pulled_file"
        return ["--", "pull", str(remote), str(local)]

    if tool == "push":
        local, remote = args.get("local"), args.get("remote")
        if not local or not remote:
            raise ValueError("push requires local and remote")
        return ["--", "push", str(local), str(remote)]

    if tool == "clear_data":
        package = args.get("package")
        if not package:
            raise ValueError("clear_data requires package")
        return ["clear", str(package)]

    if tool == "force_stop":
        package = args.get("package")
        if not package:
            raise ValueError("force_stop requires package")
        return ["stop", str(package)]

    raise ValueError(f"tool not implemented: {tool}")


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
class LLMadbRunner:
    """Runs llmadb commands with a hard timeout and kill support."""

    def __init__(
        self,
        *,
        llmadb: str | None = None,
        adb: str | None = None,
        serial: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        max_lines: int = MAX_OUTPUT_LINES,
        screenshot_dir: Path | None = None,
        extra_env: Mapping[str, str] | None = None,
        allow_unicode: bool = True,
    ) -> None:
        self.executable = llmadb or find_llmadb()
        self.adb = adb if adb is not None else find_adb()
        self.serial = serial or ""
        self.timeout = timeout
        self.max_lines = max_lines
        self.screenshot_dir = screenshot_dir
        self.extra_env = dict(extra_env or {})
        self.allow_unicode = allow_unicode
        self._unicode: Any | None = None
        self._process: subprocess.Popen[str] | None = None
        self._stopped = False

    # ---------------------------------------------------------------- state
    @property
    def available(self) -> bool:
        return bool(self.executable)

    def environment(self) -> dict[str, str]:
        env = dict(os.environ)
        if self.adb:
            env["LLMADB_ADB"] = self.adb
        if self.serial:
            env["LLMADB_SERIAL"] = self.serial
        env.update(self.extra_env)
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def stop(self) -> None:
        """Ask any in-flight llmadb process to die (used by the stop button)."""
        self._stopped = True
        self._kill_current()

    def resume(self) -> None:
        self._stopped = False

    def _kill_current(self) -> None:
        process = self._process
        if process is None or process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                    capture_output=True,
                    check=False,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except OSError:
            with contextlib.suppress(OSError):
                process.kill()

    # ---------------------------------------------------------------- run
    def run(self, argv: Sequence[str], timeout: float | None = None) -> LLMadbResult:
        started = time.monotonic()
        argv = list(argv)
        if not self.executable:
            return LLMadbResult(
                ok=False,
                argv=argv,
                stdout="",
                stderr="llmadb executable not found",
                returncode=127,
                error_code="E_TOOL_MISSING",
                hint="pip install llm-adb, or set runtime.llmadb_path in settings",
            )
        if self._stopped:
            return LLMadbResult(
                ok=False,
                argv=argv,
                stderr="agent stopped",
                returncode=130,
                error_code="E_STOPPED",
                hint="AI control is paused; start it again to continue",
            )

        command = [self.executable, *argv]
        popen_kwargs: dict[str, Any] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": self.environment(),
        }
        if os.name != "nt":
            popen_kwargs["start_new_session"] = True
        try:
            process = subprocess.Popen(command, **popen_kwargs)  # noqa: S603 - fixed argv
            self._process = process
            try:
                stdout, stderr = process.communicate(timeout=timeout or self.timeout)
            except subprocess.TimeoutExpired:
                self._kill_current()
                stdout, stderr = process.communicate(timeout=5)
                duration = int((time.monotonic() - started) * 1000)
                return LLMadbResult(
                    ok=False,
                    argv=argv,
                    stdout=trim_output(stdout or "", self.max_lines),
                    stderr=trim_output(stderr or "", self.max_lines),
                    returncode=124,
                    error_code="E_TIMEOUT",
                    hint="the action took too long; retry once, then take a screenshot",
                    duration_ms=duration,
                )
            finally:
                self._process = None
        except FileNotFoundError:
            return LLMadbResult(
                ok=False,
                argv=argv,
                stderr=f"{self.executable} not found",
                returncode=127,
                error_code="E_TOOL_MISSING",
                hint="pip install llm-adb",
            )
        except OSError as exc:  # pragma: no cover - platform specific
            return LLMadbResult(
                ok=False,
                argv=argv,
                stderr=str(exc),
                returncode=126,
                error_code="E_SPAWN_FAILED",
                hint="check the configured llmadb path",
            )

        duration = int((time.monotonic() - started) * 1000)
        stdout = trim_output(stdout or "", self.max_lines)
        stderr = trim_output(stderr or "", self.max_lines)
        code, message, hint = parse_error("\n".join(part for part in (stdout, stderr) if part))
        ok = process.returncode == 0 and code is None
        if ok:
            return LLMadbResult(
                ok=True, argv=argv, stdout=stdout, stderr=stderr,
                returncode=process.returncode, duration_ms=duration,
            )
        return LLMadbResult(
            ok=False,
            argv=argv,
            stdout=stdout,
            stderr=message if code else stderr,
            returncode=process.returncode,
            error_code=code or "E_COMMAND_FAILED",
            hint=hint,
            duration_ms=duration,
        )

    # ---------------------------------------------------------------- call
    def call(self, tool: str, arguments: Mapping[str, Any] | None = None) -> ToolResult:
        """Build and run the llmadb command for one tool call."""
        probe = dict(arguments or {})
        text = probe.get("text")
        if tool == "type_text" and isinstance(text, str) and text and not text.isascii():
            return self._type_unicode(probe)
        try:
            argv = build_argv(tool, probe)
        except (ValueError, TypeError) as exc:
            return ToolResult(
                ok=False,
                tool=tool,
                text=str(exc),
                error_code="E_BAD_ARGS",
                hint="fix the arguments and call the tool again",
            )

        screenshot_path: Path | None = None
        if tool == "screenshot":
            screenshot_path = self._new_screenshot_path()
            argv += ["-o", str(screenshot_path)]

        result = self.run(argv)
        if not result.ok and tool in RETRYABLE_TOOLS and result.error_code == "E_TIMEOUT":
            # Read-only probes are safe to retry once after a timeout; actions never are.
            time.sleep(RETRY_DELAY_SECONDS)
            result = self.run(argv)
        if not result.ok:
            return ToolResult(
                ok=False,
                tool=tool,
                text=result.stderr or result.stdout or "llmadb failed",
                error_code=result.error_code,
                hint=result.hint,
                duration_ms=result.duration_ms,
                argv=result.argv,
            )

        text = result.stdout.strip()
        if tool == "screenshot":
            parsed = _SCREEN_RE.search(text)
            if parsed and screenshot_path is None:
                screenshot_path = Path(parsed.group("path"))
            if screenshot_path is not None and not screenshot_path.is_absolute():
                screenshot_path = (Path.cwd() / screenshot_path).resolve()
            text = text or "screenshot saved"
        return ToolResult(
            ok=True,
            tool=tool,
            text=trim_output(text, self.max_lines),
            image_path=str(screenshot_path) if screenshot_path else None,
            duration_ms=result.duration_ms,
            argv=result.argv,
        )

    def prepare_unicode(self) -> None:
        """Select ADBKeyboard before the user/agent focuses a text field.

        Switching IME *after* a field is focused can drop that field's input
        connection on some Android builds (observed on BlueStacks), so the app
        prepares the IME when AI control starts and restores it on stop.
        """
        if not self.allow_unicode:
            return
        from agent.unicode_input import UnicodeInput

        if self._unicode is None:
            self._unicode = UnicodeInput(self)
        self._unicode.ensure_ready()
        self._unicode.keep_active()

    def restore_unicode(self) -> None:
        """Restore the IME that was active before AI control started."""
        if self._unicode is not None:
            self._unicode.restore_ime()

    def _type_unicode(self, probe: dict[str, Any]) -> ToolResult:
        """Route non-ASCII text through the ADBKeyboard IME."""
        if not self.allow_unicode:
            return ToolResult(
                ok=False,
                tool="type_text",
                text="unicode input is disabled in settings",
                error_code="E_UNICODE_DISABLED",
                hint="在设置中开启 runtime.unicode_input，或安装 ADBKeyboard 后重试",
            )
        from agent.unicode_input import UnicodeInput

        if self._unicode is None:
            self._unicode = UnicodeInput(self)
        result = self._unicode.send(
            str(probe.get("text", "")),
            enter=bool(probe.get("enter", True)),
            clear=bool(probe.get("clear", False)),
        )
        return ToolResult(
            ok=result.ok,
            tool="type_text",
            text=result.message,
            error_code=result.code,
            hint=result.hint,
        )

    def _new_screenshot_path(self) -> Path:
        directory = self.screenshot_dir
        if directory is None:
            from config.settings import user_data_dir

            directory = user_data_dir() / "screenshots"
        directory.mkdir(parents=True, exist_ok=True)
        return directory / "screen-{}.png".format(time.strftime("%Y%m%d-%H%M%S"))
