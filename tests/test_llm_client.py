"""Tests for the OpenAI-compatible client normalisation (no network)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from agent.llm_client import LLMError, OpenAICompatClient, ToolCall
from config.settings import ApiConfig


class FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        return self.response


class FakeClient:
    def __init__(self, response):
        self.chat = SimpleNamespace(completions=FakeCompletions(response))


def _response(content="", tool_calls=()):
    message = SimpleNamespace(content=content, tool_calls=list(tool_calls))
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage, model="fake-model")


def _tool_call(call_id="call_1", name="get_ui", arguments='{"full": true}'):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))


def test_text_only_response():
    client = OpenAICompatClient(ApiConfig(api_key="k"), client=FakeClient(_response("你好")))
    result = client.complete([{"role": "user", "content": "hi"}], [])

    assert result.text == "你好"
    assert result.tool_calls == []
    assert result.usage["total_tokens"] == 15
    assert result.assistant_message() == {"role": "assistant", "content": "你好"}


def test_tool_call_is_parsed():
    client = OpenAICompatClient(ApiConfig(api_key="k"), client=FakeClient(_response("", [_tool_call()])))
    result = client.complete([{"role": "user", "content": "看看界面"}], [])

    assert result.has_tool_calls
    call = result.tool_calls[0]
    assert call.name == "get_ui"
    assert call.arguments == {"full": True}
    message = result.assistant_message()
    assert message["tool_calls"][0]["function"]["arguments"] == '{"full": true}'


def test_malformed_tool_arguments_are_preserved():
    bad = _tool_call(arguments="{not json")
    client = OpenAICompatClient(ApiConfig(api_key="k"), client=FakeClient(_response("", [bad])))
    result = client.complete([{"role": "user", "content": "x"}], [])

    assert result.tool_calls[0].arguments == {"_raw_arguments": "{not json"}


def test_request_carries_tools_and_sampling_options():
    fake = FakeClient(_response("ok"))
    config = ApiConfig(api_key="k", model="m1", temperature=0.2, max_tokens=99)
    client = OpenAICompatClient(config, client=fake)
    client.complete([{"role": "user", "content": "x"}], [{"type": "function", "function": {"name": "get_ui"}}])

    request = fake.chat.completions.requests[0]
    assert request["model"] == "m1"
    assert request["temperature"] == 0.2
    assert request["max_tokens"] == 99
    assert request["tool_choice"] == "auto"
    assert request["tools"][0]["function"]["name"] == "get_ui"


def test_no_tools_omits_tool_choice():
    fake = FakeClient(_response("ok"))
    client = OpenAICompatClient(ApiConfig(api_key="k"), client=fake)
    client.complete([{"role": "user", "content": "x"}], [])

    assert "tools" not in fake.chat.completions.requests[0]


def test_missing_api_key_raises():
    client = OpenAICompatClient(ApiConfig(api_key=""), client=None)
    with pytest.raises(LLMError, match="API key"):
        client.complete([], [])


def test_tool_call_serialisation_roundtrip():
    call = ToolCall(id="c9", name="tap", arguments={"index": 3}, raw_arguments="")
    payload = call.as_openai_tool_call()
    assert payload["id"] == "c9"
    assert json.loads(payload["function"]["arguments"]) == {"index": 3}
