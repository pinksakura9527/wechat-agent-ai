"""Presets for OpenAI-compatible providers.

Every vendor below exposes an OpenAI-compatible /chat/completions endpoint, so
the app only needs a Base URL, an API key and a model name. Entries are hints,
not hard bindings: all three fields stay editable.

WeChat automation needs image input, so presets whose model cannot see images
are marked and the UI warns about them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str
    model: str
    vision: bool
    note: str = ""


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset(
        "OpenAI 官方",
        "https://api.openai.com/v1",
        "gpt-4o-mini",
        True,
        "支持图片输入，适合操作微信。",
    ),
    ProviderPreset(
        "DeepSeek 深度求索",
        "https://api.deepseek.com/v1",
        "deepseek-chat",
        False,
        "文本模型，看不到微信截图；聊天界面会不可见，不建议用于实际操作。",
    ),
    ProviderPreset(
        "通义千问（阿里云百炼）",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "qwen-vl-max",
        True,
        "视觉模型，支持图片输入。",
    ),
    ProviderPreset(
        "豆包（火山方舟）",
        "https://ark.cn-beijing.volces.com/api/v3",
        "doubao-1.5-vision-pro-32k-250115",
        True,
        "视觉模型。模型名也可填方舟「推理接入点 ID」（ep-...），以控制台为准。",
    ),
    ProviderPreset(
        "智谱 GLM",
        "https://open.bigmodel.cn/api/paas/v4",
        "glm-4v-plus",
        True,
        "视觉模型，支持图片输入。",
    ),
    ProviderPreset(
        "Kimi（月之暗面）",
        "https://api.moonshot.cn/v1",
        "moonshot-v1-8k",
        False,
        "文本模型，看不到截图。",
    ),
    ProviderPreset(
        "Ollama 本地",
        "http://127.0.0.1:11434/v1",
        "qwen2.5vl:7b",
        True,
        "需要本地已安装 Ollama 并拉取视觉模型。",
    ),
    ProviderPreset("自定义", "", "", True, "手动填写 Base URL 与模型名。"),
)


def match_preset(base_url: str, model: str) -> int:
    """Return the preset index matching the saved config, or the custom entry."""
    clean = (base_url or "").rstrip("/")
    for index, preset in enumerate(PROVIDER_PRESETS):
        if preset.base_url.rstrip("/") == clean and preset.model == model:
            return index
    return len(PROVIDER_PRESETS) - 1
