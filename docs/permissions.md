# 权限模型（Permissions）

## 1. 原则

- **默认最小化**：危险工具不出现在 `allowed_tools` 中，即视为拒绝；
- **显式放行**：用户必须在 UI 中勾选并看到红色警告，才会写入配置；
- **拒绝优先**：`denied_tools` 永远优先于 `allowed_tools`；
- **失败关闭**：未知工具名、配置损坏时，加载失败并按最小权限处理。

## 2. Schema

`permissions.json`（默认值见 `config/permissions.default.json`）：

```json
{
  "version": 1,
  "allowed_tools": ["get_ui", "tap", "type_text", "..."],
  "denied_tools": ["shell", "install", "uninstall", "pull", "push"]
}
```

| 字段 | 含义 |
| --- | --- |
| `allowed_tools` | 允许调用的工具名，必须在 `agent/tools.py` 的目录中存在 |
| `denied_tools` | 明确拒绝的工具名；与 allowed 冲突时启动即报错 |
| `dangerous_tools` | **派生字段，不写入配置**：由 `agent/tools.py` 的 `category` 计算，UI 用它标红；判定只看 allowed/denied |

## 3. 工具分类

| 工具 | 类别 | 默认 | 风险 |
| --- | --- | --- | --- |
| `device_status` | read | 允许 | 低 |
| `get_ui` | read | 允许 | 低（可能含聊天内容） |
| `current_app` | read | 允许 | 低 |
| `screenshot` | read | 允许 | 中（画面可能含隐私） |
| `tap` | interact | 允许 | 中（可能误点） |
| `type_text` | interact | 允许 | 高（可能误发消息） |
| `swipe` / `key` | interact | 允许 | 低 |
| `wait_for` | read | 允许 | 低 |
| `launch_app` | interact | 允许 | 低 |
| `shell` | dangerous | **拒绝** | 极高：任意 adb 命令、数据外泄 |
| `install` / `uninstall` | dangerous | **拒绝** | 高：装/卸应用 |
| `pull` / `push` | dangerous | **拒绝** | 高：文件进出设备 |
| `clear_data` / `force_stop` | dangerous | **拒绝** | 高：破坏会话状态 |

## 4. 检查算法（已实现于 `agent/permissions.py`）

```text
on tool_call(name, args):
    if name not in TOOL_CATALOG:          -> deny("unknown_tool")
    if name in denied_tools:              -> deny("explicitly_denied")
    if name not in allowed_tools:         -> deny("not_allowed")
    allow() -> MCP server -> LLMadbRunner
```

拒绝时返回给模型的结构：

```json
{ "ok": false, "error": "permission_denied", "tool": "shell", "reason": "explicitly_denied" }
```

模型应据此换策略（例如改用 `get_ui`），而不是反复重试同一工具；同一工具连续被拒 2 次时，
AgentLoop 终止本轮并提示用户。

## 5. 扩展步骤

1. 在 `agent/tools.py` 增加 `ToolSpec`（含 category）；
2. 危险工具加入 `dangerous_tools` 与 `denied_tools` 默认值；
3. 在 `agent/llmadb.py` 增加参数构造与输出裁剪；
4. 在 `agent/mcp_server.py` 注册（若使用自动注册则无需改动）；
5. 用 mock 测试守卫拒绝路径与放行路径。
