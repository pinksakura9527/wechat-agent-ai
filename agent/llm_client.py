"""Client for OpenAI-compatible chat-completions endpoints.

Works with OpenAI, DeepSeek, Ollama, vLLM, LM Studio and anything else that
speaks the same JSON shape. The client is deliberately thin: it sends
messages + tool schemas, and normalises tool calls into plain dictionaries so
the rest of the app never touches provider objects.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from config.settings import ApiConfig


class LLMError(RuntimeError):
    """Raised when the provider rejects a request or returns an unusable payload."""


@dataclass
class ToolCall:
    """One tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""

    def as_openai_tool_call(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.raw_arguments or json.dumps(self.arguments)},
        }


@dataclass
class LLMResponse:
    """Normalised model reply."""

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def assistant_message(self) -> dict[str, Any]:
        """Message dict suitable for appending to the conversation history."""
        message: dict[str, Any] = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            message["tool_calls"] = [call.as_openai_tool_call() for call in self.tool_calls]
        return message


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


def _describe_error(exc: Exception) -> str:
    """Turn provider errors into actionable Chinese messages."""
    status = getattr(exc, "status_code", None)
    text = str(exc)
    if status == 404:
        return (
            "模型或接入点不存在（404）。豆包/火山方舟请在控制台创建「推理接入点」，"
            "把模型名填成 ep-... 形式的接入点 ID（展示名如 Doubao-Seed-2.1-turbo 不能直接用于 API）；"
            "其他厂商请核对模型 ID。原始错误：" + text
        )
    if status == 401:
        return "API Key 无效或已过期（401），请检查 Key 与 Base URL 是否属于同一厂商。原始错误：" + text
    if status == 429:
        return "请求过于频繁或额度不足（429），请稍后重试或检查账户余额。原始错误：" + text
    if status is None and ("Connection" in text or "connect" in text.lower()):
        return "无法连接到大模型服务，请检查 Base URL、网络/代理。原始错误：" + text
    return "LLM 请求失败：" + text


class OpenAICompatClient:
    """OpenAI-compatible client; also works with DeepSeek, Ollama, vLLM, etc."""

    def __init__(self, config: ApiConfig, *, client: Any | None = None) -> None:
        self.config = config
        self._client = client

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.config.api_key.strip():
            raise LLMError("API key is not configured; open the API panel and save a key")
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency error
            raise LLMError("the 'openai' package is not installed; run pip install -e .") from exc
        self._client = OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=1,
        )
        return self._client

    def configure(self, config: ApiConfig) -> None:
        """Apply new credentials; the underlying SDK client is rebuilt lazily."""
        self.config = config
        self._client = None

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        client = self._ensure_client()
        request: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            request["tools"] = tools
            request["tool_choice"] = "auto"
        try:
            response = client.chat.completions.create(**request)
        except Exception as exc:  # noqa: BLE001 - provider SDK error types vary
            raise LLMError(_describe_error(exc)) from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise LLMError("LLM returned no choices")
        message = choices[0].message
        tool_calls: list[ToolCall] = []
        for call in getattr(message, "tool_calls", None) or []:
            raw_arguments = getattr(call.function, "arguments", "") or "{}"
            try:
                arguments = json.loads(raw_arguments)
                if not isinstance(arguments, dict):
                    arguments = {"_value": arguments}
            except json.JSONDecodeError:
                arguments = {"_raw_arguments": raw_arguments}
            tool_calls.append(
                ToolCall(
                    id=getattr(call, "id", "") or f"call_{len(tool_calls)}",
                    name=getattr(call.function, "name", ""),
                    arguments=arguments,
                    raw_arguments=raw_arguments,
                )
            )

        usage = {}
        raw_usage = getattr(response, "usage", None)
        if raw_usage is not None:
            usage = {
                "prompt_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                "completion_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
                "total_tokens": int(getattr(raw_usage, "total_tokens", 0) or 0),
            }
        return LLMResponse(
            text=getattr(message, "content", "") or "",
            tool_calls=tool_calls,
            usage=usage,
            raw={"model": getattr(response, "model", self.config.model)},
        )
