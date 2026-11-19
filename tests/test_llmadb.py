"""Unit tests for the llmadb execution layer (no device required)."""

from __future__ import annotations

import pytest

from agent.llmadb import (
    LLMadbResult,
    LLMadbRunner,
    ToolResult,
    build_argv,
    parse_error,
    trim_output,
)


def test_get_ui_argv():
    assert build_argv("get_ui", {}) == ["ui"]
    assert build_argv("get_ui", {"full": True}) == ["ui", "--full"]


def test_tap_by_index_and_text():
    assert build_argv("tap", {"index": 6}) == ["tap", "6"]
    assert build_argv("tap", {"text": "发送"}) == ["tap", "--text", "发送"]
    assert build_argv("tap", {"id": "sendBtn"}) == ["tap", "--id", "sendBtn"]


def test_tap_by_coordinates_and_hold():
    assert build_argv("tap", {"x": 540, "y": 960}) == ["tap", "540,960"]
    assert build_argv("tap", {"index": 1, "hold_ms": 800}) == ["tap", "1", "--hold", "800"]


@pytest.mark.parametrize(
    "arguments",
    [{}, {"index": 1, "text": "x"}, {"x": 1}, {"index": 1, "x": 2, "y": 3}],
)
def test_tap_rejects_ambiguous_targets(arguments):
    with pytest.raises(ValueError):
        build_argv("tap", arguments)


def test_type_text_escapes_and_flags():
    assert build_argv("type_text", {"text": "hello"}) == ["type", "hello", "--enter"]
    assert build_argv("type_text", {"text": "hello", "enter": False}) == ["type", "hello"]
    assert build_argv("type_text", {"text": "hello", "clear": True}) == ["type", "hello", "--clear", "--enter"]


def test_type_text_leading_dash_uses_passthrough():
    argv = build_argv("type_text", {"text": "-5", "enter": False})
    assert argv == ["--", "shell", "input", "text", "-5"]


def test_type_text_escapes_spaces_in_passthrough():
    argv = build_argv("type_text", {"text": "-a b", "enter": False})
    assert argv[-1] == "-a%sb"


def test_screenshot_and_status_argv():
    assert build_argv("screenshot", {}) == ["screen"]
    assert build_argv("screenshot", {"ocr": True}) == ["screen", "--ocr"]
    assert build_argv("device_status", {}) == ["status"]
    assert build_argv("current_app", {}) == ["current"]


def test_wait_for_argv_converts_ms_to_seconds():
    argv = build_argv("wait_for", {"text": "发送", "timeout_ms": 7000})
    assert argv == ["wait-for", "--text", "发送", "--timeout", "7"]


def test_dangerous_tools_use_passthrough():
    assert build_argv("shell", {"command": "input keyevent 3"}) == ["--", "shell", "input", "keyevent", "3"]
    assert build_argv("uninstall", {"package": "com.tencent.mm"}) == ["--", "uninstall", "com.tencent.mm"]
    assert build_argv("clear_data", {"package": "com.tencent.mm"}) == ["clear", "com.tencent.mm"]


def test_unknown_tool_rejected():
    with pytest.raises(ValueError):
        build_argv("rm_rf", {})


def test_parse_error_line():
    code, message, hint = parse_error(
        "screen 1080x1920\nerror: E_NO_DEVICE no devices connected | hint: check USB, enable USB debugging"
    )
    assert code == "E_NO_DEVICE"
    assert message == "no devices connected"
    assert "enable USB debugging" in hint


def test_trim_output_limits_lines_and_chars():
    text = "\n".join(str(i) for i in range(200))
    trimmed = trim_output(text, max_lines=10, max_chars=10_000)
    assert trimmed.count("\n") == 10  # 10 lines + truncation marker
    assert "truncated by wechat-agent" in trimmed


def test_runner_call_success(monkeypatch):
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe")
    monkeypatch.setattr(
        runner,
        "run",
        lambda argv, timeout=None: LLMadbResult(ok=True, argv=list(argv), stdout="ok", returncode=0),
    )
    result = runner.call("get_ui", {})
    assert result.ok
    assert result.text == "ok"


def test_runner_call_parses_failure(monkeypatch):
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe")
    monkeypatch.setattr(
        runner,
        "run",
        lambda argv, timeout=None: LLMadbResult(
            ok=False,
            argv=list(argv),
            stderr="no devices",
            returncode=3,
            error_code="E_NO_DEVICE",
            hint="start an emulator",
        ),
    )
    result = runner.call("get_ui", {})
    assert not result.ok
    assert result.error_code == "E_NO_DEVICE"
    assert result.as_tool_error()["error"] == "E_NO_DEVICE"
    assert result.as_tool_error()["hint"] == "start an emulator"


def test_runner_call_rejects_bad_arguments_without_spawning(monkeypatch):
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe")

    def boom(*_args, **_kwargs):
        raise AssertionError("must not spawn llmadb for invalid arguments")

    monkeypatch.setattr(runner, "run", boom)
    result = runner.call("tap", {})
    assert not result.ok
    assert result.error_code == "E_BAD_ARGS"


def test_non_ascii_text_routes_to_unicode_input(monkeypatch):
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe")
    seen: list[dict] = []

    def fake_type_unicode(probe):
        seen.append(probe)
        return ToolResult(ok=True, tool="type_text", text="typed via ADBKeyboard")

    monkeypatch.setattr(runner, "_type_unicode", fake_type_unicode)
    result = runner.call("type_text", {"text": "你好", "enter": False})

    assert result.ok
    assert seen == [{"text": "你好", "enter": False}]


def test_ascii_text_does_not_use_unicode_path(monkeypatch):
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe")
    monkeypatch.setattr(
        runner,
        "_type_unicode",
        lambda probe: (_ for _ in ()).throw(AssertionError("must not use unicode path")),
    )
    monkeypatch.setattr(
        runner,
        "run",
        lambda argv, timeout=None: LLMadbResult(ok=True, argv=list(argv), stdout="ok"),
    )
    assert runner.call("type_text", {"text": "hello"}).ok


def test_unicode_disabled_returns_structured_error(monkeypatch):
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe", allow_unicode=False)
    result = runner.call("type_text", {"text": "中文"})
    assert not result.ok
    assert result.error_code == "E_UNICODE_DISABLED"


def test_runner_without_executable_reports_missing():
    runner = LLMadbRunner(llmadb="llmadb.exe", adb="adb.exe")
    runner.executable = None  # simulate llm-adb not installed
    result = runner.run(["ui"])
    assert not result.ok
    assert result.error_code == "E_TOOL_MISSING"
