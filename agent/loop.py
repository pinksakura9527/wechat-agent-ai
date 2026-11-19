"""Agent loop: instruction -> LLM -> tool calls -> llmadb -> LLM.

The loop is UI-agnostic: it emits `AgentEvent` objects through a listener and
persists through an injected memory sink, so tests can run it with fakes and
the desktop app can run it in a worker thread.
"""

from __future__ import annotations

import base64
import contextlib
import json
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from agent.llm_client import LLMClient, LLMError
from agent.permissions import PermissionConfig, PermissionDenied
from agent.prompts import build_system_prompt
from agent.tools import openai_tools


class LoopState(StrEnum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    STOPPED = "stopped"
    ERROR = "error"


class EventKind(StrEnum):
    USER_MESSAGE = "user_message"
    ASSISTANT_TEXT = "assistant_text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STATE_CHANGED = "state_changed"
    ERROR = "error"


@dataclass
class AgentEvent:
    """One observable step of the agent loop."""

    kind: EventKind
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class LoopLimits:
    max_steps: int = 12
    step_delay_ms: tuple[int, int] = (300, 900)
    max_consecutive_denials: int = 2
    max_repeated_failures: int = 3
    history_limit: int = 60


class MemorySink(Protocol):
    """Persistence contract implemented by `memory.db.MemoryStore`."""

    def add_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str,
        tool_calls_json: str | None = None,
        tool_call_id: str | None = None,
    ) -> None: ...

    def add_action(
        self,
        *,
        session_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result_summary: str,
        status: str,
    ) -> None: ...


class AgentLoop:
    """Drives the model/tool cycle until the instruction is done or stopped."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        runner: Any,
        guard: Any,
        session_id: str,
        persona: str,
        permissions: PermissionConfig,
        limits: LoopLimits | None = None,
        memory: MemorySink | None = None,
        listener: Callable[[AgentEvent], None] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        rng: random.Random | None = None,
        guide: str | None = None,
        send_screenshots: bool = True,
        max_images: int = 2,
    ) -> None:
        self._llm = llm
        self._runner = runner
        self._guard = guard
        self._session_id = session_id
        self._persona = persona
        self._permissions = permissions
        self._limits = limits or LoopLimits()
        self._memory = memory
        self._listener = listener
        self._sleep = sleep
        self._rng = rng or random.Random()
        self._guide = guide
        self._send_screenshots = send_screenshots
        self._max_images = max_images
        self._failures: dict[tuple[str, str], int] = {}
        self._state = LoopState.IDLE
        self._stopped = False
        self._history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> LoopState:
        return self._state

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)

    def stop(self) -> None:
        """Request cancellation; the loop finishes the current call and exits."""
        self._stopped = True
        with contextlib.suppress(Exception):  # the loop must survive a broken runner
            self._runner.stop()

    def set_persona(self, persona: str) -> None:
        """Apply an edited persona to the next request."""
        self._persona = persona

    def set_send_screenshots(self, enabled: bool) -> None:
        """Toggle image messages for vision models."""
        self._send_screenshots = enabled

    def set_permissions(self, permissions: PermissionConfig) -> None:
        """Apply an edited permission summary to the next request."""
        self._permissions = permissions

    def load_history(self, messages: list[dict[str, Any]]) -> None:
        """Seed the conversation from stored history (import / app restart)."""
        self._history = [
            {
                "role": message.get("role", "user"),
                "content": message.get("content") or "",
                "tool_calls": message.get("tool_calls"),
                "tool_call_id": message.get("tool_call_id"),
            }
            for message in messages
        ]

    def resume(self) -> None:
        self._stopped = False
        with contextlib.suppress(Exception):
            self._runner.resume()

    # ------------------------------------------------------------------ helpers
    def _set_state(self, state: LoopState, events: list[AgentEvent]) -> None:
        self._state = state
        self._emit(AgentEvent(EventKind.STATE_CHANGED, {"state": state.value}), events)

    def _emit(self, event: AgentEvent, events: list[AgentEvent]) -> None:
        events.append(event)
        if self._listener is not None:
            with contextlib.suppress(Exception):  # the UI must never crash the loop
                self._listener(event)

    def _remember_message(
        self,
        role: str,
        content: str,
        tool_calls: list[dict[str, Any]] | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        self._history.append(
            {"role": role, "content": content, "tool_calls": tool_calls, "tool_call_id": tool_call_id}
        )
        if self._memory is not None:
            with contextlib.suppress(Exception):  # storage must never crash the loop
                self._memory.add_message(
                    session_id=self._session_id,
                    role=role,
                    content=content,
                    tool_calls_json=json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None,
                    tool_call_id=tool_call_id,
                )

    def _remember_action(self, tool: str, arguments: dict[str, Any], summary: str, status: str) -> None:
        if self._memory is None:
            return
        with contextlib.suppress(Exception):
            self._memory.add_action(
                session_id=self._session_id,
                tool_name=tool,
                arguments=arguments,
                result_summary=summary,
                status=status,
            )

    def _request_messages(self) -> list[dict[str, Any]]:
        system = build_system_prompt(
            persona=self._persona,
            permissions=self._permissions,
            guide=self._guide,
        )
        history = [dict(item) for item in self._history[-self._limits.history_limit :]]
        image_indexes = [
            index for index, item in enumerate(history) if isinstance(item.get("content"), list)
        ]
        stale = image_indexes if self._max_images <= 0 else image_indexes[: -self._max_images]
        for index in stale:
            history[index]["content"] = "[较早的截图已省略以节省 Token]"
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for item in history:
            message: dict[str, Any] = {"role": item["role"], "content": item.get("content") or ""}
            if item.get("tool_calls"):
                message["tool_calls"] = item["tool_calls"]
            if item.get("tool_call_id"):
                message["tool_call_id"] = item["tool_call_id"]
            messages.append(message)
        return messages

    def _append_screenshot(self, image_path: str) -> None:
        """Attach a screenshot as a user image message for vision models."""
        if not self._send_screenshots:
            return
        try:
            data = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
        except OSError:
            return
        self._history.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "[系统截图] 当前屏幕，叠加 100px 网格；网格标签即设备像素坐标。",
                    },
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64," + data}},
                ],
                "tool_calls": None,
                "tool_call_id": None,
            }
        )

    def _pace(self) -> None:
        low, high = self._limits.step_delay_ms
        if high <= 0:
            return
        self._sleep(self._rng.randint(low, max(low, high)) / 1000.0)

    # ------------------------------------------------------------------ run
    def run_instruction(self, text: str) -> list[AgentEvent]:
        """Run one user instruction and return the emitted events."""
        events: list[AgentEvent] = []
        self._stopped = False
        self._set_state(LoopState.THINKING, events)
        self._emit(AgentEvent(EventKind.USER_MESSAGE, {"text": text}), events)
        self._remember_message("user", text)

        denials = 0
        for _step in range(self._limits.max_steps):
            if self._stopped:
                self._set_state(LoopState.STOPPED, events)
                return events
            self._pace()
            messages = self._request_messages()
            try:
                response = self._llm.complete(messages, openai_tools())
            except LLMError as exc:
                self._emit(AgentEvent(EventKind.ERROR, {"message": str(exc)}), events)
                self._set_state(LoopState.ERROR, events)
                return events

            if response.text:
                self._emit(AgentEvent(EventKind.ASSISTANT_TEXT, {"text": response.text}), events)
            if not response.has_tool_calls:
                self._remember_message("assistant", response.text)
                self._set_state(LoopState.IDLE, events)
                return events

            self._remember_message("assistant", response.text, [call.as_openai_tool_call() for call in response.tool_calls])
            self._set_state(LoopState.EXECUTING, events)

            for call in response.tool_calls:
                if self._stopped:
                    self._set_state(LoopState.STOPPED, events)
                    return events
                self._emit(AgentEvent(EventKind.TOOL_CALL, {"name": call.name, "arguments": call.arguments}), events)
                if self._stopped:
                    self._set_state(LoopState.STOPPED, events)
                    return events
                try:
                    self._guard.check(call.name, call.arguments)
                except PermissionDenied as exc:
                    denials += 1
                    payload = exc.as_tool_error()
                    self._emit(AgentEvent(EventKind.TOOL_RESULT, {"name": call.name, "ok": False, **payload}), events)
                    self._remember_action(call.name, call.arguments, exc.reason, "denied")
                    self._remember_message(
                        "tool", json.dumps(payload, ensure_ascii=False), tool_call_id=call.id
                    )
                    if denials >= self._limits.max_consecutive_denials:
                        self._emit(
                            AgentEvent(
                                EventKind.ERROR,
                                {"message": f"模型连续请求被禁止的工具（{call.name}），已停止本轮任务。"},
                            ),
                            events,
                        )
                        self._set_state(LoopState.ERROR, events)
                        return events
                    continue

                denials = 0
                result = self._runner.call(call.name, call.arguments)
                failure_key = (
                    call.name,
                    json.dumps(call.arguments, sort_keys=True, ensure_ascii=False, default=str),
                )
                if result.ok:
                    self._failures.pop(failure_key, None)
                    payload = {"ok": True, "tool": call.name, "summary": result.summary()}
                    content = result.text
                    self._remember_action(call.name, call.arguments, result.summary(), "ok")
                else:
                    payload = result.as_tool_error()
                    content = json.dumps(payload, ensure_ascii=False)
                    self._remember_action(call.name, call.arguments, result.summary(), "error")
                    self._failures[failure_key] = self._failures.get(failure_key, 0) + 1
                    if self._failures[failure_key] >= self._limits.max_repeated_failures:
                        self._emit(
                            AgentEvent(
                                EventKind.ERROR,
                                {
                                    "message": "同一工具以相同参数连续失败 {} 次（{}），已停止本轮任务。".format(
                                        self._failures[failure_key], call.name
                                    )
                                },
                            ),
                            events,
                        )
                        self._set_state(LoopState.ERROR, events)
                        return events
                self._emit(AgentEvent(EventKind.TOOL_RESULT, {**payload, "image_path": result.image_path}), events)
                self._remember_message("tool", content, tool_call_id=call.id)
                if result.ok and result.image_path:
                    self._append_screenshot(result.image_path)

            self._set_state(LoopState.THINKING, events)

        self._emit(AgentEvent(EventKind.ERROR, {"message": f"达到最大步数 {self._limits.max_steps}，已停止。"}), events)
        self._set_state(LoopState.ERROR, events)
        return events
