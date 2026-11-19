"""System prompt assembly: persona + permissions + device guidance.

The persona is user-editable (`persona.md`); the device guide may be
overridden by `config/wechat_prompt.md` (phase 5). This module never
invents WeChat UI details when the guide file is present.
"""

from __future__ import annotations

from pathlib import Path

from agent.permissions import PermissionConfig

DEFAULT_GUIDE = """## Device workflow

- Before acting, call get_ui to see the current screen; never guess coordinates blindly.
- Tap by element index or visible text when possible; use x,y only when get_ui
  cannot represent the control (custom views, WebView, games).
- After every tap / type / swipe, read the returned UI snapshot and confirm the
  screen changed as expected.
- When the UI tree is useless, take a screenshot: the image already carries a
  100px coordinate grid in device pixels.
- If a dump looks stale or a dialog blocks it, press key "back" once or wait a
  second and retry; do not repeat the same failing call more than twice.
- Input text must be ASCII: Android's input command cannot type Chinese. When a
  task needs non-ASCII text, stop and report it to the user instead of typing
  something wrong.

## Boundaries

- Only touch WeChat. Never open settings, payments, or system apps unless the
  user explicitly asks.
- Never send a message to a contact the user did not name.
- If a permission error is returned, do not retry the same tool; choose a
  different allowed approach or tell the user what permission is missing.
"""


def guide_path() -> Path:
    return Path(__file__).resolve().parents[1] / "config" / "wechat_prompt.md"


def load_wechat_guide(path: Path | None = None) -> str:
    """Load the WeChat-specific guide, falling back to the built-in one."""
    candidate = path or guide_path()
    try:
        text = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        return DEFAULT_GUIDE
    return text or DEFAULT_GUIDE


def build_system_prompt(
    *,
    persona: str,
    permissions: PermissionConfig,
    guide: str | None = None,
) -> str:
    """Compose the system prompt sent with every request."""
    persona_text = persona.strip() or "你是一个运行在本机的微信助理。"
    permission_lines = "\n".join(permissions.summary_lines())
    device_guide = (guide if guide is not None else load_wechat_guide()).strip()
    return (
        "# 角色（Persona）\n"
        f"{persona_text}\n\n"
        "# 当前权限（Permission summary）\n"
        f"{permission_lines}\n"
        "工具调用若被拒绝会返回 permission_denied；不要重试被拒绝的工具。\n\n"
        f"{device_guide}\n"
    )
