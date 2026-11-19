"""Chinese/unicode text input through the ADBKeyboard IME.

Android's built-in `input text` command cannot type non-ASCII characters.
The standard workaround is the open-source ADBKeyboard IME: it listens for
base64-encoded broadcasts and commits the decoded text into the focused field.

This module is deliberately tiny and testable: every device call goes through
the llmadb runner's passthrough (`llmadb -- shell ...`), and no state is cached
beyond the original IME so it can be restored.

Setup (one time, per emulator)::

    python scripts/setup_adbkeyboard.py
"""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

PACKAGE = "com.android.adbkeyboard"
IME_ID = "com.android.adbkeyboard/.AdbIME"
ACTION_B64 = "ADB_INPUT_B64"
ACTION_CLEAR = "ADB_CLEAR_TEXT"
KEYCODE_ENTER = 66

SETUP_HINT = (
    "安装并启用 ADBKeyboard 后即可输入中文：python scripts/setup_adbkeyboard.py"
)


@dataclass
class UnicodeResult:
    ok: bool
    message: str
    code: str | None = None
    hint: str | None = None


class UnicodeInput:
    """Drives the ADBKeyboard IME via llmadb adb passthrough."""

    def __init__(self, runner: Any, *, pause: float = 0.35) -> None:
        self._runner = runner
        self._pause = pause
        self._available: bool | None = None
        self._original_ime: str | None = None
        self._original_soft_keyboard: str | None = None
        self._keep_ready = False

    # ------------------------------------------------------------- device io
    def _shell(self, *args: str, timeout: float = 20.0):
        return self._runner.run(["--", "shell", *args], timeout=timeout)

    def available(self, *, refresh: bool = False) -> bool:
        if self._available and not refresh:
            return True
        result = self._shell("pm", "list", "packages", PACKAGE)
        self._available = result.ok and PACKAGE in result.stdout
        return bool(self._available)

    def current_ime(self) -> str:
        result = self._shell("settings", "get", "secure", "default_input_method")
        return result.stdout.strip() if result.ok else ""

    def select_ime(self) -> UnicodeResult:
        if self.current_ime() == IME_ID:
            # Keep any previously remembered IME so restore_ime() still works.
            return UnicodeResult(True, "ADBKeyboard already active")
        original = self.current_ime()
        self._shell("ime", "enable", IME_ID)
        result = self._shell("ime", "set", IME_ID)
        if not result.ok:
            return UnicodeResult(False, result.stderr or "ime set failed", "E_IME_SET", SETUP_HINT)
        self._original_ime = original or None
        time.sleep(self._pause)
        return UnicodeResult(True, f"switched IME from {original or 'unknown'} to ADBKeyboard")

    def keep_active(self) -> None:
        """Keep ADBKeyboard selected until restore_ime() (agent session mode)."""
        self._keep_ready = True

    def ensure_ready(self) -> UnicodeResult:
        """Make ADBKeyboard the active IME and keep its view visible.

        ADBKeyboard only registers its broadcast receiver while its input view
        is shown. Emulators with a hardware keyboard (BlueStacks default) hide
        the soft keyboard, so the receiver never exists and broadcasts are
        silently dropped. Setting `show_ime_with_hard_keyboard` fixes that.
        """
        if not self.available():
            return UnicodeResult(
                False,
                "ADBKeyboard is not installed on the device",
                "E_UNICODE_UNAVAILABLE",
                SETUP_HINT,
            )
        if self._original_soft_keyboard is None:
            current = self._shell("settings", "get", "secure", "show_ime_with_hard_keyboard")
            self._original_soft_keyboard = (current.stdout or "").strip() or "null"
        if self._original_soft_keyboard != "1":
            self._shell("settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
        return self.select_ime()

    def restore_ime(self) -> None:
        self._keep_ready = False
        if self._original_ime:
            self._shell("ime", "set", self._original_ime)
            self._original_ime = None
        if self._original_soft_keyboard is not None and self._original_soft_keyboard != "1":
            if self._original_soft_keyboard in {"null", ""}:
                self._shell("settings", "delete", "secure", "show_ime_with_hard_keyboard")
            else:
                self._shell("settings", "put", "secure", "show_ime_with_hard_keyboard", "0")
            self._original_soft_keyboard = None

    def clear(self) -> UnicodeResult:
        result = self._shell("am", "broadcast", "-a", ACTION_CLEAR, "-p", PACKAGE)
        if not result.ok:
            return UnicodeResult(False, result.stderr or "clear failed", "E_UNICODE_CLEAR")
        return UnicodeResult(True, "field cleared")

    def send(self, text: str, *, enter: bool = True, clear: bool = False) -> UnicodeResult:
        """Type text with the ADBKeyboard IME and optionally press Enter."""
        if not text:
            return UnicodeResult(False, "empty text", "E_BAD_ARGS")
        if not self.available():
            return UnicodeResult(
                False,
                "ADBKeyboard is not installed on the device",
                "E_UNICODE_UNAVAILABLE",
                SETUP_HINT,
            )
        selected = self.select_ime()
        if not selected.ok:
            return selected

        if clear:
            cleared = self.clear()
            if not cleared.ok:
                return cleared

        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        result = self._shell(
            "am", "broadcast", "-a", ACTION_B64, "-p", PACKAGE, "--es", "msg", payload
        )
        if not result.ok:
            self.restore_ime()
            return UnicodeResult(False, result.stderr or "broadcast failed", "E_UNICODE_SEND")
        time.sleep(self._pause)
        if enter:
            self._shell("input", "keyevent", str(KEYCODE_ENTER))
            time.sleep(self._pause)
        if not self._keep_ready:
            self.restore_ime()
        return UnicodeResult(True, f"typed {len(text)} character(s) via ADBKeyboard")
