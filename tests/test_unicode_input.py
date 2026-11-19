"""ADBKeyboard unicode input tests (all device calls faked)."""

from __future__ import annotations

import base64

from agent.llmadb import LLMadbResult
from agent.unicode_input import IME_ID, PACKAGE, UnicodeInput


class FakeRunner:
    def __init__(self, *, available: bool = True, current_ime: str = "com.android.inputmethod.latin/.LatinIME") -> None:
        self.argv: list[list[str]] = []
        self.available = available
        self.current_ime = current_ime

    def run(self, argv, timeout=None):
        argv = list(argv)
        self.argv.append(argv)
        joined = " ".join(argv)
        if "pm list packages" in joined:
            stdout = f"package:{PACKAGE}" if self.available else ""
            return LLMadbResult(ok=self.available, argv=argv, stdout=stdout)
        if "settings get secure default_input_method" in joined:
            return LLMadbResult(ok=True, argv=argv, stdout=self.current_ime)
        if "ime set" in joined:
            self.current_ime = argv[-1]
            return LLMadbResult(ok=True, argv=argv)
        if "ime enable" in joined:
            return LLMadbResult(ok=True, argv=argv)
        return LLMadbResult(ok=True, argv=argv, stdout="Broadcast completed: result=0")


def test_available_detects_package():
    runner = FakeRunner(available=True)
    assert UnicodeInput(runner, pause=0).available() is True
    assert UnicodeInput(FakeRunner(available=False), pause=0).available() is False


def test_send_uses_base64_and_restores_ime():
    runner = FakeRunner()
    result = UnicodeInput(runner, pause=0).send("测试中文", enter=True, clear=False)

    assert result.ok
    joined = [" ".join(argv) for argv in runner.argv]
    payload = base64.b64encode("测试中文".encode()).decode()
    assert any("ADB_INPUT_B64" in line and payload in line for line in joined)
    assert any("input keyevent 66" in line for line in joined)
    # IME restored to the original
    assert runner.current_ime == "com.android.inputmethod.latin/.LatinIME"


def test_send_without_adbkeyboard_reports_setup_hint():
    runner = FakeRunner(available=False)
    result = UnicodeInput(runner, pause=0).send("你好")
    assert not result.ok
    assert result.code == "E_UNICODE_UNAVAILABLE"
    assert "setup_adbkeyboard" in (result.hint or "")
    assert runner.argv  # only the availability probe ran


def test_send_can_clear_and_skip_enter():
    runner = FakeRunner()
    UnicodeInput(runner, pause=0).send("hello", enter=False, clear=True)
    joined = [" ".join(argv) for argv in runner.argv]
    assert any("ADB_CLEAR_TEXT" in line for line in joined)
    assert not any("input keyevent 66" in line for line in joined)


def test_keep_active_skips_restore_between_calls():
    runner = FakeRunner()
    unicode_input = UnicodeInput(runner, pause=0)
    unicode_input.ensure_ready()
    unicode_input.keep_active()

    unicode_input.send("第一段", enter=False)

    assert runner.current_ime == IME_ID
    unicode_input.restore_ime()
    assert runner.current_ime == "com.android.inputmethod.latin/.LatinIME"


def test_no_restore_when_ime_already_active():
    runner = FakeRunner(current_ime=IME_ID)
    UnicodeInput(runner, pause=0).send("你好", enter=False)
    joined = [" ".join(argv) for argv in runner.argv]
    # no switch away from ADBKeyboard
    assert not any("ime set com.android.inputmethod.latin" in line for line in joined)
