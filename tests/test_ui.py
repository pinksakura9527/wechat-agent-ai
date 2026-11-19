"""UI tests: panels, permission toggles and window wiring (offscreen Qt)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QTabWidget

from agent.llmadb import ToolResult
from agent.permissions import PermissionConfig
from app.widgets.api_panel import ApiPanel
from app.widgets.permissions_panel import PermissionsPanel
from config.settings import ApiConfig, AppSettings


def _item_for(panel: PermissionsPanel, name: str):
    for row in range(panel._list.count()):
        item = panel._list.item(row)
        if item.data(Qt.ItemDataRole.UserRole) == name:
            return item
    raise AssertionError(f"tool not listed: {name}")


def test_api_panel_emits_edited_config(qtbot):
    panel = ApiPanel(ApiConfig(api_key="", model="m"))
    qtbot.addWidget(panel)
    captured: list[ApiConfig] = []
    panel.api_saved.connect(captured.append)

    panel._base_url.setText("https://example.com/v1")
    panel._api_key.setText("sk-secret")
    panel._model.setText("deepseek-chat")
    panel._max_tokens.setValue(512)
    panel._temperature.setValue(0.3)
    qtbot.mouseClick(panel._save, Qt.MouseButton.LeftButton)

    assert captured
    saved = captured[0]
    assert saved.api_key == "sk-secret"
    assert saved.model == "deepseek-chat"
    assert saved.max_tokens == 512
    assert saved.validate() == []


def test_permissions_panel_enables_safe_tool(qtbot):
    panel = PermissionsPanel(PermissionConfig.from_dict({"allowed_tools": ["get_ui"]}))
    qtbot.addWidget(panel)
    changes: list[PermissionConfig] = []
    panel.permissions_changed.connect(changes.append)

    _item_for(panel, "tap").setCheckState(Qt.CheckState.Checked)

    assert changes
    assert "tap" in changes[-1].allowed_tools
    assert changes[-1].is_allowed("tap")


def test_permissions_panel_dangerous_tool_requires_confirmation(qtbot, monkeypatch):
    panel = PermissionsPanel(PermissionConfig.from_dict({"allowed_tools": ["get_ui"]}))
    qtbot.addWidget(panel)
    changes: list[PermissionConfig] = []
    panel.permissions_changed.connect(changes.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.No,
    )

    shell = _item_for(panel, "shell")
    shell.setCheckState(Qt.CheckState.Checked)

    assert shell.checkState() == Qt.CheckState.Unchecked
    assert changes == []  # no change was accepted


def test_permissions_panel_emits_runtime_toggles(qtbot):
    from config.settings import RuntimeConfig

    runtime = RuntimeConfig(unicode_input=False, send_screenshots=True)
    panel = PermissionsPanel(PermissionConfig.from_dict({"allowed_tools": ["get_ui"]}), runtime)
    qtbot.addWidget(panel)
    changes = []
    panel.runtime_changed.connect(changes.append)

    panel._unicode_checkbox.setChecked(True)
    assert changes
    assert changes[-1].unicode_input is True
    assert changes[-1].send_screenshots is True

    panel._vision_checkbox.setChecked(False)
    assert changes[-1].send_screenshots is False


def test_permissions_panel_dangerous_tool_accepted(qtbot, monkeypatch):
    panel = PermissionsPanel(PermissionConfig.from_dict({"allowed_tools": ["get_ui"]}))
    qtbot.addWidget(panel)
    changes: list[PermissionConfig] = []
    panel.permissions_changed.connect(changes.append)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    _item_for(panel, "shell").setCheckState(Qt.CheckState.Checked)

    assert changes and changes[-1].is_allowed("shell")


class FakeRunner:
    def __init__(self, **_kwargs) -> None:
        pass

    def call(self, tool, arguments):
        return ToolResult(ok=True, tool=tool, text="battery: 100% (not charging)")

    def stop(self) -> None:
        pass

    def resume(self) -> None:
        pass


def _make_window(qtbot, monkeypatch, tmp_path, *, with_key: bool):
    from app import main_window as module

    monkeypatch.setenv("WECHAT_AGENT_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(module, "LLMadbRunner", FakeRunner)
    settings = AppSettings()
    if with_key:
        settings.api.api_key = "sk-test"
    window = module.MainWindow(settings)
    qtbot.addWidget(window)
    return window


def test_window_has_all_tabs(qtbot, monkeypatch, tmp_path):
    window = _make_window(qtbot, monkeypatch, tmp_path, with_key=False)
    try:
        tabs = window.findChild(QTabWidget)
        assert tabs.count() == 5
        assert [tabs.tabText(i) for i in range(tabs.count())] == ["聊天 / 日志", "API 配置", "人设", "权限", "记忆"]
        assert window._master_button.text() == "▶ 开启 AI 控制"
    finally:
        window.close()


def test_start_requires_api_key(qtbot, monkeypatch, tmp_path):
    window = _make_window(qtbot, monkeypatch, tmp_path, with_key=False)
    warnings: list[str] = []
    monkeypatch.setattr(module_warning(), "warning", lambda *args, **kwargs: warnings.append(args[2]))
    try:
        window._master_button.click()
        assert warnings and "API" in warnings[0]
        assert window._running is False
    finally:
        window.close()


def module_warning():
    from app import main_window as module

    return module.QMessageBox


def test_start_and_stop_agent(qtbot, monkeypatch, tmp_path):
    window = _make_window(qtbot, monkeypatch, tmp_path, with_key=True)
    try:
        window._master_button.click()
        assert window._running is True
        assert window._loop is not None
        assert window._master_button.text() == "■ 停止 AI 控制"

        window._master_button.click()
        assert window._running is False
        assert window._master_button.text() == "▶ 开启 AI 控制"
    finally:
        window.close()


def test_instruction_requires_running_agent(qtbot, monkeypatch, tmp_path):
    window = _make_window(qtbot, monkeypatch, tmp_path, with_key=False)
    try:
        window._send_instruction("你好")
        text = window._chat_panel._log.toPlainText()
        assert "请先点击" in text
    finally:
        window.close()
