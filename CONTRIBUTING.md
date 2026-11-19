# 贡献指南（Contributing）

感谢你愿意改进 WeChat Agent AI！这是一个 MIT 许可的开源项目，欢迎任何规模的 PR。

## 开发环境

```powershell
git clone https://github.com/<you>/wechat-agent-ai.git
cd wechat-agent-ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

python scripts/check_env.py      # 环境自检
python scripts/setup_adbkeyboard.py   # 可选：中文输入（一次性）
pytest                            # 无模拟器也能跑（mock llmadb）
```

## 代码规范

- Python 3.11+，类型注解优先，注释用英文；
- 提交前运行 `ruff check .` 与 `ruff format .`；
- 文档与 UI 文案先中文、后补英文；
- 一个 PR 只做一件事；涉及行为变化时同步更新文档。

## 目录职责

| 目录 | 职责 | 不要做 |
| --- | --- | --- |
| `app/` | 窗口、控件、事件渲染 | 业务逻辑、subprocess、SQL |
| `agent/` | 循环、LLM、MCP、权限、llmadb 调用 | 导入 `app/`、直接操作 SQLite |
| `memory/` | SQLite 与导入导出 | 调用 llmadb、导入 `agent/` |
| `config/` | 设置、默认人设、权限默认值 | 依赖上层 |

## 如何新增一个 MCP 工具

1. 在 `agent/tools.py` 的 `TOOL_CATALOG` 添加 `ToolSpec`：
   - `name`：snake_case，与 llmadb 子命令语义一致；
   - `summary`：给模型看的一句话（英文，简洁）；
   - `category`：`read` / `interact` / `dangerous`；
   - `parameters`：JSON Schema。
2. 在 `agent/llmadb.py` 增加“参数 → 命令行”构造与输出裁剪。
3. 若为危险工具，加入 `config/permissions.default.json` 的 `denied_tools` 与
   `dangerous_tools`，并在 UI 中显示红色警告。
4. 在 `tests/` 用 mock 的 llmadb 输出覆盖成功与失败路径。
5. 更新 `docs/permissions.md` 的工具表。

## 如何扩展权限 schema

- 只增加工具名不改变语义：直接改 `config/permissions.default.json`；
- 需要按参数细粒度控制（例如只允许 tap 指定 index 范围）：在
  `agent/permissions.py` 增加 `PolicyRule` 并在 `check()` 中评估；
- 任何新字段必须向后兼容：旧配置文件缺失字段时使用默认值，且 `version` 递增。

## 如何更换桌面技术栈

`agent/` 与 `memory/` 不感知 UI。替换步骤：

1. 保留 `agent/loop.py` 的 `AgentEvent` 流（或写一个适配器）；
2. 新前端只调用 `AgentLoop`、`PermissionGuard`、`MemoryStore` 的公开方法；
3. 删除或隔离 `app/`，更新 `pyproject.toml` 的入口点与依赖；
4. 在 PR 描述中说明打包方式与 CI 调整。

## 微信界面与截图

微信大部分界面对 uiautomator 不可见（`llmadb ui` 返回 `E_SECURE_OR_EMPTY`），所以
AgentLoop 会把 `screenshot` 的 PNG 作为图片消息发给模型（默认开启，最多保留最近 2 张）。
改 UI 自动化相关代码时，请同时验证：

1. 纯文本模型下仍能工作（关闭“允许把截图发送给视觉模型”）；
2. 图片消息不会写入 SQLite；
3. 裁剪逻辑不会删掉最新截图。

## 测试

- 单元测试不得依赖真实模拟器：用 `tests/fixtures/` 里的 llmadb 输出样本；
- 需要设备的测试标记 `@pytest.mark.integration`，默认跳过；
- 新增行为应有对应测试；修复 bug 请附最小复现。

## 提交与 PR

- 提交信息：`type(scope): summary`，例如 `feat(tools): add wait_for`；
- PR 描述写清：动机、改动、验证方式（命令与结果）、风险；
- 涉及权限、安全、风控文案的改动请额外说明。
