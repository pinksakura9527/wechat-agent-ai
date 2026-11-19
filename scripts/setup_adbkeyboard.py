"""One-time ADBKeyboard setup for Chinese text input.

Installs the open-source ADBKeyboard IME, enables it, and prints the current
input method. Safe to re-run.

Usage::

    python scripts/setup_adbkeyboard.py            # install + enable
    python scripts/setup_adbkeyboard.py --check    # only report status
    python scripts/setup_adbkeyboard.py --apk path/to/ADBKeyboard.apk
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llmadb import find_adb  # noqa: E402

PACKAGE = "com.android.adbkeyboard"
IME_ID = "com.android.adbkeyboard/.AdbIME"
APK_URLS = (
    "https://cdn.jsdelivr.net/gh/senzhk/ADBKeyBoard@master/ADBKeyboard.apk",
    "https://raw.githubusercontent.com/senzhk/ADBKeyBoard/master/ADBKeyboard.apk",
    "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk",
)


def run(adb: str, *args: str, timeout: int = 120) -> tuple[int, str]:
    completed = subprocess.run(
        [adb, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return completed.returncode, ((completed.stdout or "") + (completed.stderr or "")).strip()


def download(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file() and target.stat().st_size > 10_000:
        return target
    errors = []
    for url in APK_URLS:
        try:
            with urllib.request.urlopen(url, timeout=60) as response:  # noqa: S310 - fixed URLs
                data = response.read()
            if len(data) < 10_000:
                errors.append(f"{url}: too small")
                continue
            target.write_bytes(data)
            return target
        except Exception as exc:  # noqa: BLE001 - try the next mirror
            errors.append(f"{url}: {exc}")
    raise SystemExit("could not download ADBKeyboard.apk:\n" + "\n".join(errors))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install and enable ADBKeyboard")
    parser.add_argument("--adb", default="", help="path to adb.exe (auto-detected by default)")
    parser.add_argument("--apk", default="", help="use a local ADBKeyboard.apk")
    parser.add_argument("--check", action="store_true", help="only report status")
    args = parser.parse_args(argv)

    adb = args.adb or find_adb()
    if not adb:
        print("adb not found; install Android platform-tools first.", file=sys.stderr)
        return 1

    code, packages = run(adb, "shell", "pm", "list", "packages", PACKAGE, timeout=30)
    installed = code == 0 and PACKAGE in packages
    code, current = run(adb, "shell", "settings", "get", "secure", "default_input_method", timeout=30)

    print(f"adb:        {adb}")
    print(f"installed:  {'yes' if installed else 'no'}")
    print(f"current IME:{current}")
    if args.check:
        return 0 if installed else 2

    if not installed:
        apk = Path(args.apk) if args.apk else download(REPO_ROOT / ".cache" / "apk" / "ADBKeyboard.apk")
        print(f"installing {apk} ...")
        code, output = run(adb, "install", "-r", str(apk))
        if "Success" not in output:
            print(output, file=sys.stderr)
            return 1

    print("enabling ADBKeyboard ...")
    run(adb, "shell", "ime", "enable", IME_ID, timeout=30)
    run(adb, "shell", "ime", "set", IME_ID, timeout=30)
    code, current = run(adb, "shell", "settings", "get", "secure", "default_input_method", timeout=30)
    print(f"current IME:{current}")
    print("done. The app switches to ADBKeyboard only while typing Chinese, then restores your IME.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
