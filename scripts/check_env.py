"""Environment self-check for WeChat Agent AI (phase 1 deliverable).

Verifies, without starting the desktop app:

1. Python version (>= 3.11).
2. adb binary (settings -> PATH -> ANDROID_HOME -> common emulator bundles).
3. llmadb CLI (settings -> PATH -> project virtualenv -> current interpreter).
4. Connected emulator (llmadb devices / adb devices).
5. API key configured (warning only).
6. Data directory writable.

Usage::

    python scripts/check_env.py
    python scripts/check_env.py --json
    python scripts/check_env.py --no-device      # skip the device probe

Exit code 0 means: no hard failure. Warnings (no device, no API key) still
return 0 so CI can run without an emulator.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config.settings import AppSettings, user_data_dir  # noqa: E402

MIN_PYTHON = (3, 11)
TIMEOUT_SECONDS = 25


@dataclass
class Check:
    name: str
    status: str          # "ok" | "warn" | "fail"
    detail: str
    hint: str = ""


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [check for check in self.checks if check.status == "fail"]

    @property
    def warned(self) -> list[Check]:
        return [check for check in self.checks if check.status == "warn"]

    def to_dict(self) -> dict:
        return {
            "ok": not self.failed,
            "checks": [asdict(check) for check in self.checks],
        }


def _run(command: list[str], timeout: int = TIMEOUT_SECONDS) -> tuple[int, str]:
    """Run a command, returning (exit code, merged output)."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as exc:  # pragma: no cover - platform specific
        return 126, str(exc)
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output.strip()


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        try:
            if path and path.is_file():
                return path
        except OSError:
            continue
    return None


def find_adb(settings: AppSettings) -> Path | None:
    """Locate the adb executable, preferring the configured path."""
    runtime = settings.runtime
    candidates: list[Path] = []
    if runtime.adb_path:
        candidates.append(Path(runtime.adb_path).expanduser())
    on_path = shutil.which("adb")
    if on_path:
        candidates.append(Path(on_path))

    for variable in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        base = os.environ.get(variable)
        if base:
            candidates.append(Path(base) / "platform-tools" / "adb.exe")
            candidates.append(Path(base) / "platform-tools" / "adb")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Android" / "platform-tools" / "adb.exe")

    candidates.extend(
        [
            Path.home() / "AppData" / "Local" / "Android" / "platform-tools" / "adb.exe",
            Path("C:/Android/Sdk/platform-tools/adb.exe"),
            # Emulator bundles that ship an adb-compatible binary.
            Path("C:/Program Files/BlueStacks_nxt/HD-Adb.exe"),
            Path("C:/LDPlayer/LDPlayer9/adb.exe"),
            Path("C:/Program Files/Netease/MuMuPlayer-12.0/shell/adb.exe"),
            Path("/usr/local/bin/adb"),
            Path("/usr/bin/adb"),
        ]
    )
    return _first_existing(candidates)


def find_llmadb(settings: AppSettings) -> Path | None:
    """Locate the llmadb console script."""
    candidates: list[Path] = []
    configured = settings.runtime.llmadb_path
    if configured:
        candidates.append(Path(configured).expanduser())
    on_path = shutil.which("llmadb")
    if on_path:
        candidates.append(Path(on_path))

    scripts_dir = Path(sys.executable).parent
    candidates.extend(
        [
            REPO_ROOT / ".venv" / "Scripts" / "llmadb.exe",
            REPO_ROOT / ".venv" / "bin" / "llmadb",
            scripts_dir / "llmadb.exe",
            scripts_dir / "llmadb",
        ]
    )
    return _first_existing(candidates)


def check_python() -> Check:
    version = sys.version_info
    text = f"Python {version.major}.{version.minor}.{version.micro} ({sys.executable})"
    if (version.major, version.minor) >= MIN_PYTHON:
        return Check("python", "ok", text)
    return Check(
        "python",
        "fail",
        text,
        "Install Python {}+ from https://www.python.org/downloads/".format(
            ".".join(str(part) for part in MIN_PYTHON)
        ),
    )


def check_adb(settings: AppSettings) -> tuple[Check, Path | None]:
    adb = find_adb(settings)
    if not adb:
        return (
            Check(
                "adb",
                "fail",
                "adb not found",
                "Install Android platform-tools and/or set runtime.adb_path in settings.json "
                "(Windows: winget install Google.PlatformTools)",
            ),
            None,
        )
    code, output = _run([str(adb), "version"])
    first_line = output.splitlines()[0] if output else "no output"
    if code == 0:
        return Check("adb", "ok", f"{adb} ({first_line})"), adb
    return Check("adb", "fail", f"{adb} exited with {code}: {first_line}"), adb


def check_llmadb(settings: AppSettings) -> tuple[Check, Path | None]:
    llmadb = find_llmadb(settings)
    if not llmadb:
        code, output = _run([sys.executable, "-c", "import llm_adb; print('module ok')"])
        if code == 0:
            return (
                Check(
                    "llmadb",
                    "warn",
                    "python package importable but no console script on PATH",
                    "Activate the project virtualenv, or install with: pip install llm-adb",
                ),
                None,
            )
        return (
            Check(
                "llmadb",
                "fail",
                "llmadb CLI and python package not found",
                "Install it with: pip install llm-adb (PyPI package: llm-adb, CLI: llmadb)",
            ),
            None,
        )
    code, output = _run([str(llmadb), "--version"])
    text = output.splitlines()[0] if output else ""
    if code == 0 and text:
        return Check("llmadb", "ok", f"{llmadb} ({text})"), llmadb
    if code == 0:
        return Check("llmadb", "ok", str(llmadb)), llmadb
    return Check("llmadb", "fail", str(llmadb), "Reinstall: pip install --force-reinstall llm-adb"), llmadb


def _device_environment(adb: Path | None, settings: AppSettings) -> dict[str, str]:
    env = dict(os.environ)
    if adb:
        env["LLMADB_ADB"] = str(adb)
    if settings.runtime.device_serial:
        env["LLMADB_SERIAL"] = settings.runtime.device_serial
    return env


def check_device(settings: AppSettings, adb: Path | None, llmadb: Path | None) -> Check:
    env = _device_environment(adb, settings)
    serials: list[str] = []

    if llmadb:
        code, output = _run_with_env([str(llmadb), "devices"], env)
        if code == 0 and "E_ADB" not in output and "E_NO_DEVICE" not in output:
            for line in output.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2 and parts[1].strip() == "device":
                    serials.append(parts[0].strip())

    if not serials and adb:
        code, output = _run_with_env([str(adb), "devices"], env)
        if code == 0:
            for line in output.splitlines():
                if "\tdevice" in line:
                    serials.append(line.split("\t")[0].strip())

    if serials:
        return Check("device", "ok", "connected: " + ", ".join(sorted(set(serials))))
    hint = (
        "Start the Android emulator, enable USB/ADB debugging, then run: "
        "adb connect 127.0.0.1:5555"
    )
    return Check("device", "warn", "no emulator connected", hint)


def _run_with_env(command: list[str], env: dict[str, str], timeout: int = TIMEOUT_SECONDS) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=env,
        )
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()


def check_api(settings: AppSettings) -> Check:
    api = settings.api
    if api.api_key.strip():
        return Check("api", "ok", f"base_url={api.base_url} model={api.model} (key configured)")
    return Check(
        "api",
        "warn",
        f"base_url={api.base_url} model={api.model} (no API key)",
        "Configure Base URL / API Key / model in the app or in settings.json",
    )


def check_data_dir() -> Check:
    directory = user_data_dir()
    probe = directory / ".write-probe"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        return Check("data_dir", "fail", f"{directory} ({exc})", "Check folder permissions")
    return Check("data_dir", "ok", str(directory))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify the WeChat Agent AI environment")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--no-device", action="store_true", help="skip the emulator probe")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    settings = AppSettings.load()
    report = Report()

    report.checks.append(check_python())

    adb_check, adb = check_adb(settings)
    report.checks.append(adb_check)

    llmadb_check, llmadb = check_llmadb(settings)
    report.checks.append(llmadb_check)

    if not args.no_device:
        report.checks.append(check_device(settings, adb, llmadb))

    report.checks.append(check_api(settings))
    report.checks.append(check_data_dir())

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        symbols = {"ok": "[ OK ]", "warn": "[WARN]", "fail": "[FAIL]"}
        for check in report.checks:
            print("{} {:<9} {}".format(symbols.get(check.status, "[????]"), check.name, check.detail))
            if check.hint and check.status != "ok":
                print(f"       -> {check.hint}")
        print()
        if report.failed:
            print(f"Result: {len(report.failed)} hard failure(s). Fix the [FAIL] items above.")
        elif report.warned:
            print(f"Result: environment usable; {len(report.warned)} warning(s) to review.")
        else:
            print("Result: all checks passed.")

    return 0 if not report.failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
