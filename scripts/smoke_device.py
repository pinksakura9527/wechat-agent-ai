"""Device smoke test: connectivity, UI tree or screenshot, IME readiness.

It never sends a message. Use it before a demo or after changing device code.

Usage::

    python scripts/smoke_device.py
    python scripts/smoke_device.py --type    # type+clear in a focused field
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llmadb import LLMadbRunner  # noqa: E402
from agent.unicode_input import UnicodeInput  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="WeChat Agent AI device smoke test")
    parser.add_argument("--type", action="store_true", help="type and clear Chinese text in the focused field")
    args = parser.parse_args(argv)

    runner = LLMadbRunner()
    print(f"llmadb: {runner.executable or 'NOT FOUND'}")
    print(f"adb:    {runner.adb or 'NOT FOUND'}")
    failures = 0

    status = runner.call("device_status", {})
    print(f"[{'OK' if status.ok else 'FAIL'}] device_status: {status.summary(160)}")
    failures += 0 if status.ok else 1

    ui = runner.call("get_ui", {})
    if ui.ok:
        print(f"[OK] ui: {len(ui.text.splitlines())} lines")
    elif ui.error_code == "E_SECURE_OR_EMPTY":
        shot = runner.call("screenshot", {})
        if shot.ok and shot.image_path:
            print(f"[OK] ui blocked by app, screenshot fallback: {shot.image_path}")
        else:
            print(f"[FAIL] screenshot fallback: {shot.text}")
            failures += 1
    else:
        print(f"[FAIL] get_ui: {ui.error_code} {ui.text}")
        failures += 1

    unicode_input = UnicodeInput(runner)
    if unicode_input.available():
        print("[OK] ADBKeyboard installed")
        ready = unicode_input.ensure_ready()
        if ready.ok:
            print("[OK] IME switched to ADBKeyboard")
            if args.type:
                typed = unicode_input.send("测试中文输入", enter=False, clear=True)
                print(f"[{'OK' if typed.ok else 'FAIL'}] type+clear: {typed.message}")
                failures += 0 if typed.ok else 1
                unicode_input.clear()
        else:
            print(f"[FAIL] IME switch: {ready.message}")
            failures += 1
        unicode_input.restore_ime()
    else:
        print("[WARN] ADBKeyboard not installed; Chinese input unavailable")
        print("       run: python scripts/setup_adbkeyboard.py")

    print("RESULT:", "ok" if failures == 0 else f"{failures} failure(s)")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
