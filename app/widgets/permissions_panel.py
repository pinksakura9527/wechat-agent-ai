"""Permission panel: tool allow-list plus input/vision capability toggles."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from agent.permissions import PermissionConfig
from agent.tools import TOOL_CATALOG
from config.settings import RuntimeConfig

DANGER_COLOR = QColor("#b42318")


class PermissionsPanel(QWidget):
    """Allow/deny tools; dangerous tools are red and need confirmation."""

    permissions_changed = Signal(object)
    runtime_changed = Signal(object)

    def __init__(
        self,
        config: PermissionConfig,
        runtime: RuntimeConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._runtime = runtime or RuntimeConfig()
        layout = QVBoxLayout(self)

        warning = QLabel(
            "危险工具默认关闭。勾选后会向模型开放相应能力，例如 shell 可以执行任意 adb 命令、"
            "pull/push 可以在电脑与模拟器之间搬运文件。请确认你了解风险。",
            self,
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color: #b42318; background: #fef3f2; border: 1px solid #fda29b;"
            " border-radius: 6px; padding: 8px;"
        )
        layout.addWidget(warning)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list, 1)

        self._populate()
        self._list.itemChanged.connect(self._on_item_changed)

        capabilities = QGroupBox("输入与视觉", self)
        capabilities_layout = QVBoxLayout(capabilities)
        self._unicode_checkbox = QCheckBox("允许 AI 使用 ADBKeyboard 输入中文（需已安装）", self)
        self._unicode_checkbox.setChecked(self._runtime.unicode_input)
        self._unicode_checkbox.toggled.connect(self._emit_runtime)
        capabilities_layout.addWidget(self._unicode_checkbox)
        unicode_hint = QLabel(
            "未安装时中文输入会返回结构化错误。安装：python scripts/setup_adbkeyboard.py",
            self,
        )
        unicode_hint.setStyleSheet("color: #667085;")
        unicode_hint.setWordWrap(True)
        capabilities_layout.addWidget(unicode_hint)

        self._vision_checkbox = QCheckBox("允许把截图发送给视觉模型（推荐，微信 UI 树通常为空）", self)
        self._vision_checkbox.setChecked(self._runtime.send_screenshots)
        self._vision_checkbox.toggled.connect(self._emit_runtime)
        capabilities_layout.addWidget(self._vision_checkbox)
        vision_hint = QLabel(
            "截图会以图片形式进入模型上下文，Token 消耗更高；关闭后模型只能看到文字结果。",
            self,
        )
        vision_hint.setStyleSheet("color: #667085;")
        vision_hint.setWordWrap(True)
        capabilities_layout.addWidget(vision_hint)
        layout.addWidget(capabilities)

        row = QHBoxLayout()
        reset = QPushButton("恢复默认权限", self)
        reset.clicked.connect(self._restore_default)
        row.addWidget(reset)
        row.addStretch(1)
        layout.addLayout(row)

    # ------------------------------------------------------------------ data
    def _populate(self) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        ordered = sorted(
            TOOL_CATALOG.values(),
            key=lambda spec: (spec.category != "dangerous", spec.category, spec.name),
        )
        for spec in ordered:
            marker = "⚠ 危险 · " if spec.category == "dangerous" else ""
            item = QListWidgetItem(f"{marker}{spec.name} — {spec.summary}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if self._config.is_allowed(spec.name) else Qt.CheckState.Unchecked
            )
            item.setData(Qt.ItemDataRole.UserRole, spec.name)
            if spec.category == "dangerous":
                item.setForeground(DANGER_COLOR)
                item.setToolTip("危险工具：默认拒绝。勾选前请确认风险。")
            self._list.addItem(item)
        self._list.blockSignals(False)

    def config(self) -> PermissionConfig:
        allowed: set[str] = set()
        denied: set[str] = set()
        for row in range(self._list.count()):
            item = self._list.item(row)
            name = item.data(Qt.ItemDataRole.UserRole)
            spec = TOOL_CATALOG[name]
            checked = item.checkState() == Qt.CheckState.Checked
            if checked:
                allowed.add(name)
            elif spec.category == "dangerous":
                denied.add(name)
        return PermissionConfig(allowed_tools=allowed, denied_tools=denied)

    def runtime(self) -> RuntimeConfig:
        return replace(
            self._runtime,
            unicode_input=self._unicode_checkbox.isChecked(),
            send_screenshots=self._vision_checkbox.isChecked(),
        )

    def set_config(self, config: PermissionConfig) -> None:
        self._config = config
        self._populate()

    def set_runtime(self, runtime: RuntimeConfig) -> None:
        self._runtime = runtime
        self._unicode_checkbox.blockSignals(True)
        self._vision_checkbox.blockSignals(True)
        self._unicode_checkbox.setChecked(runtime.unicode_input)
        self._vision_checkbox.setChecked(runtime.send_screenshots)
        self._unicode_checkbox.blockSignals(False)
        self._vision_checkbox.blockSignals(False)

    # --------------------------------------------------------------- signals
    def _on_item_changed(self, item: QListWidgetItem) -> None:
        name = item.data(Qt.ItemDataRole.UserRole)
        spec = TOOL_CATALOG[name]
        if spec.category != "dangerous" or item.checkState() != Qt.CheckState.Checked:
            self._emit()
            return
        answer = QMessageBox.question(
            self,
            "允许危险工具？",
            f"你正在允许「{name}」：{spec.summary}\n\n这可能让模型读取/修改设备数据。确定继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            self._list.blockSignals(True)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._list.blockSignals(False)
            return
        self._emit()

    def _emit(self) -> None:
        self._config = self.config()
        self.permissions_changed.emit(self._config)

    def _emit_runtime(self) -> None:
        self._runtime = self.runtime()
        self.runtime_changed.emit(self._runtime)

    def _restore_default(self) -> None:
        from agent.permissions import load_permission_config

        self.set_config(load_permission_config())
        self._emit()
