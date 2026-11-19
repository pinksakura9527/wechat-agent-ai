"""Integration tests that need a real emulator.

They are deselected by default. Run with::

    set WECHAT_AGENT_DEVICE_TEST=1
    pytest -m integration
"""

from __future__ import annotations

import os

import pytest
from agent.llmadb import LLMadbRunner

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("WECHAT_AGENT_DEVICE_TEST") != "1",
        reason="set WECHAT_AGENT_DEVICE_TEST=1 to run against a real emulator",
    ),
]


def test_device_status():
    runner = LLMadbRunner()
    result = runner.call("device_status", {})
    assert result.ok, result.text
    assert "battery" in result.text


def test_agent_loop_end_to_end_on_device():
    """A scripted LLM drives a real device_status call through the real runner."""
    from agent.llm_client import LLMResponse, ToolCall
    from agent.loop import AgentLoop, LoopLimits
    from agent.permissions import PermissionConfig, PermissionGuard

    class ScriptedLLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(id="c1", name="device_status", arguments={}, raw_arguments="{}")
                    ]
                )
            return LLMResponse(text="已确认设备状态。")

    guard = PermissionGuard(PermissionConfig.from_dict({"allowed_tools": ["device_status"]}))
    loop = AgentLoop(
        llm=ScriptedLLM(),
        runner=LLMadbRunner(),
        guard=guard,
        session_id="integration",
        persona="测试人设",
        permissions=guard.config,
        limits=LoopLimits(max_steps=3, step_delay_ms=(0, 0)),
        sleep=lambda _seconds: None,
    )

    events = loop.run_instruction("现在是什么界面？")

    tool_results = [e for e in events if e.kind.value == "tool_result"]
    assert tool_results and tool_results[0].payload["ok"] is True
    assert any(e.kind.value == "assistant_text" for e in events)
    assert isinstance(loop.history[-1]["content"], str)


def test_loop_and_memory_roundtrip_on_device(tmp_path):
    """Run one real instruction, persist it, export it, and import it again."""
    from agent.llm_client import LLMResponse, ToolCall
    from agent.loop import AgentLoop, LoopLimits
    from agent.permissions import PermissionConfig, PermissionGuard
    from memory.db import MemoryStore
    from memory.transfer import export_session, import_session

    class ScriptedLLM:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, messages, tools):
            self.calls += 1
            if self.calls == 1:
                return LLMResponse(
                    tool_calls=[
                        ToolCall(id="c1", name="device_status", arguments={}, raw_arguments="{}")
                    ]
                )
            return LLMResponse(text="界面已确认。")

    store = MemoryStore(tmp_path / "memory.db")
    store.connect()
    session = store.create_session(title="集成会话", persona_snapshot="测试人设")
    guard = PermissionGuard(PermissionConfig.from_dict({"allowed_tools": ["device_status"]}))
    loop = AgentLoop(
        llm=ScriptedLLM(),
        runner=LLMadbRunner(),
        guard=guard,
        session_id=session.session_id,
        persona="测试人设",
        permissions=guard.config,
        limits=LoopLimits(max_steps=3, step_delay_ms=(0, 0)),
        memory=store,
        sleep=lambda _seconds: None,
    )

    loop.run_instruction("现在是什么界面？")

    # user + assistant(tool_calls) + tool + final assistant text
    assert store.count_messages(session.session_id) == 4
    actions = store.list_actions(session.session_id)
    assert len(actions) == 1 and actions[0].tool_name == "device_status"

    export = export_session(
        store,
        session.session_id,
        tmp_path / "export.json",
        persona="测试人设",
        permissions=guard.config.to_dict(),
    )
    summary = import_session(store, export, mode="new_session")
    assert summary["messages"] == 4
    assert summary["actions"] == 1
    assert store.count_messages(summary["session_id"]) == 4
    store.close()


def test_ui_tree_or_screenshot_fallback():
    """WeChat blocks the accessibility tree; the screenshot must still work."""
    runner = LLMadbRunner()
    result = runner.call("get_ui", {})
    if result.ok:
        assert len(result.text.splitlines()) <= 120
        assert "screen" in result.text.splitlines()[0]
        return
    assert result.error_code == "E_SECURE_OR_EMPTY", result.text
    shot = runner.call("screenshot", {})
    assert shot.ok, shot.text
    assert shot.image_path
