"""Agent loop tests with a scripted LLM and a fake device."""

from __future__ import annotations

from typing import Any

from agent.llm_client import LLMResponse, ToolCall
from agent.llmadb import ToolResult
from agent.loop import AgentEvent, AgentLoop, EventKind, LoopLimits, LoopState
from agent.permissions import PermissionConfig, PermissionGuard


class FakeLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[list[dict[str, Any]]] = []

    def complete(self, messages, tools):
        self.requests.append(messages)
        if not self.responses:
            raise AssertionError("LLM called more times than scripted")
        return self.responses.pop(0)


class FakeRunner:
    def __init__(self, ok: bool = True) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.ok = ok
        self.stopped = False

    def call(self, tool: str, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append((tool, arguments))
        if self.ok:
            return ToolResult(ok=True, tool=tool, text=f"{tool}: done")
        return ToolResult(ok=False, tool=tool, text="boom", error_code="E_FAILED")

    def stop(self) -> None:
        self.stopped = True

    def resume(self) -> None:
        self.stopped = False


class RecordingMemory:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.actions: list[dict[str, Any]] = []

    def add_message(self, *, session_id, role, content, tool_calls_json=None, tool_call_id=None):
        self.messages.append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "tool_calls_json": tool_calls_json,
                "tool_call_id": tool_call_id,
            }
        )

    def add_action(self, *, session_id, tool_name, arguments, result_summary, status):
        self.actions.append({"tool_name": tool_name, "status": status, "arguments": arguments})


def _guard(allowed=("get_ui", "tap")):
    return PermissionGuard(PermissionConfig.from_dict({"allowed_tools": list(allowed)}))


def _loop(llm, runner, guard, memory=None, limits=None, listener=None, persona="测试人设"):
    return AgentLoop(
        llm=llm,
        runner=runner,
        guard=guard,
        session_id="s1",
        persona=persona,
        permissions=guard.config,
        limits=limits or LoopLimits(max_steps=4, step_delay_ms=(0, 0)),
        memory=memory,
        listener=listener,
        sleep=lambda _seconds: None,
    )


def test_single_text_reply_ends_loop():
    llm = FakeLLM([LLMResponse(text="好的，已查看界面")])
    runner = FakeRunner()
    memory = RecordingMemory()
    loop = _loop(llm, runner, _guard(), memory=memory)

    events = loop.run_instruction("看看现在是什么界面")

    assert loop.state == LoopState.IDLE
    kinds = [event.kind for event in events]
    assert EventKind.USER_MESSAGE in kinds
    assert EventKind.ASSISTANT_TEXT in kinds
    assert runner.calls == []
    assert [m["role"] for m in memory.messages] == ["user", "assistant"]
    assert memory.messages[-1]["content"] == "好的，已查看界面"


def test_tool_call_then_answer():
    llm = FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_ui", arguments={}, raw_arguments="{}")]),
            LLMResponse(text="界面是微信首页"),
        ]
    )
    runner = FakeRunner()
    memory = RecordingMemory()
    loop = _loop(llm, runner, _guard(), memory=memory)

    events = loop.run_instruction("现在在哪个页面？")

    assert runner.calls == [("get_ui", {})]
    assert memory.actions == [{"tool_name": "get_ui", "status": "ok", "arguments": {}}]
    result_events = [event for event in events if event.kind is EventKind.TOOL_RESULT]
    assert result_events and result_events[0].payload["ok"] is True
    assert any(event.kind is EventKind.ASSISTANT_TEXT for event in events)
    # the tool result must be fed back to the model
    assert llm.requests[-1][-1]["role"] == "tool"


def test_denied_tool_is_reported_and_stops_after_limit():
    llm = FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="shell", arguments={"command": "ls"}, raw_arguments="{}")]),
            LLMResponse(tool_calls=[ToolCall(id="c2", name="shell", arguments={"command": "ls"}, raw_arguments="{}")]),
        ]
    )
    runner = FakeRunner()
    loop = _loop(llm, runner, _guard(), limits=LoopLimits(max_steps=4, step_delay_ms=(0, 0), max_consecutive_denials=2))

    events = loop.run_instruction("随便执行点命令")

    assert runner.calls == []
    assert loop.state == LoopState.ERROR
    denied = [e for e in events if e.kind is EventKind.TOOL_RESULT and e.payload.get("ok") is False]
    assert len(denied) == 2
    assert denied[0].payload["error"] == "permission_denied"


def test_tool_failure_is_returned_to_model():
    class FailingRunner(FakeRunner):
        def call(self, tool, arguments):
            self.calls.append((tool, arguments))
            return ToolResult(ok=False, tool=tool, text="no device", error_code="E_NO_DEVICE", hint="start emulator")

    llm = FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_ui", arguments={}, raw_arguments="{}")]),
            LLMResponse(text="设备未连接"),
        ]
    )
    loop = _loop(llm, FailingRunner(), _guard())

    loop.run_instruction("看看界面")

    assert loop.state == LoopState.IDLE
    tool_messages = [m for m in loop.history if m["role"] == "tool"]
    assert "E_NO_DEVICE" in tool_messages[0]["content"]


def test_max_steps_guard_stops_runaway_loop():
    endless = [
        LLMResponse(tool_calls=[ToolCall(id=f"c{i}", name="get_ui", arguments={}, raw_arguments="{}")])
        for i in range(5)
    ]
    llm = FakeLLM(endless)
    runner = FakeRunner()
    loop = _loop(llm, runner, _guard(), limits=LoopLimits(max_steps=2, step_delay_ms=(0, 0)))

    events = loop.run_instruction("一直看界面")

    assert len(runner.calls) == 2
    assert loop.state == LoopState.ERROR
    assert any("最大步数" in str(e.payload.get("message", "")) for e in events)


def test_stop_from_listener_halts_before_executing():
    stopper: dict[str, Any] = {}

    def listener(event: AgentEvent) -> None:
        if event.kind is EventKind.TOOL_CALL:
            stopper["loop"].stop()

    llm = FakeLLM([LLMResponse(tool_calls=[ToolCall(id="c1", name="tap", arguments={"index": 1}, raw_arguments="{}")])])
    runner = FakeRunner()
    loop = _loop(llm, runner, _guard(), listener=listener)
    stopper["loop"] = loop

    loop.run_instruction("点一下")

    assert loop.state == LoopState.STOPPED
    assert runner.calls == []
    assert runner.stopped is True


def _png(tmp_path):
    target = tmp_path / "shot.png"
    target.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    return target


class ScreenshotRunner(FakeRunner):
    def __init__(self, image_path) -> None:
        super().__init__()
        self.image_path = str(image_path)

    def call(self, tool, arguments):
        self.calls.append((tool, arguments))
        return ToolResult(ok=True, tool=tool, text="path=shot.png", image_path=self.image_path)


def test_screenshot_is_attached_as_image_message(tmp_path):
    llm = FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_ui", arguments={}, raw_arguments="{}")]),
            LLMResponse(text="看到了"),
        ]
    )
    loop = _loop(llm, ScreenshotRunner(_png(tmp_path)), _guard())
    loop.set_send_screenshots(True)

    loop.run_instruction("看看屏幕")

    last_request = llm.requests[-1]
    image_messages = [m for m in last_request if isinstance(m.get("content"), list)]
    assert len(image_messages) == 1
    parts = image_messages[0]["content"]
    assert any(part.get("type") == "image_url" and part["image_url"]["url"].startswith("data:image/png;base64,") for part in parts)


def test_old_screenshots_are_pruned_to_budget(tmp_path):
    image = _png(tmp_path)
    llm = FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_ui", arguments={}, raw_arguments="{}")]),
            LLMResponse(tool_calls=[ToolCall(id="c2", name="get_ui", arguments={}, raw_arguments="{}")]),
            LLMResponse(text="好了"),
        ]
    )
    loop = _loop(llm, ScreenshotRunner(image), _guard())
    loop._max_images = 1
    loop.run_instruction("连续截图")

    last_request = llm.requests[-1]
    image_messages = [m for m in last_request if isinstance(m.get("content"), list)]
    assert len(image_messages) == 1
    assert any(m.get("content") == "[较早的截图已省略以节省 Token]" for m in last_request)


def test_screenshots_disabled_keeps_text_only(tmp_path):
    llm = FakeLLM(
        [
            LLMResponse(tool_calls=[ToolCall(id="c1", name="get_ui", arguments={}, raw_arguments="{}")]),
            LLMResponse(text="好"),
        ]
    )
    loop = _loop(llm, ScreenshotRunner(_png(tmp_path)), _guard())
    loop.set_send_screenshots(False)
    loop.run_instruction("看看")

    assert not any(isinstance(m.get("content"), list) for m in llm.requests[-1])


def test_system_prompt_includes_persona_and_permissions():
    llm = FakeLLM([LLMResponse(text="ok")])
    loop = _loop(llm, FakeRunner(), _guard(["get_ui"]), persona="你是一个测试人设")

    loop.run_instruction("你好")

    system = llm.requests[0][0]
    assert system["role"] == "system"
    assert "你是一个测试人设" in system["content"]
    assert "allowed: get_ui" in system["content"]
