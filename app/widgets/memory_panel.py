"""Memory panel: session info plus export/import entry points."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MemoryPanel(QWidget):
    """Shows the active session and exposes export/import/new-session actions."""

    export_requested = Signal()
    import_requested = Signal()
    new_session_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        group = QGroupBox("当前会话", self)
        group_layout = QVBoxLayout(group)
        self._session_label = QLabel("会话：—", self)
        self._counts_label = QLabel("消息 0 条 · 动作 0 条", self)
        self._path_label = QLabel("", self)
        self._path_label.setStyleSheet("color: #667085;")
        self._path_label.setWordWrap(True)
        group_layout.addWidget(self._session_label)
        group_layout.addWidget(self._counts_label)
        group_layout.addWidget(self._path_label)
        layout.addWidget(group)

        row = QHBoxLayout()
        export = QPushButton("导出 JSON…", self)
        export.setObjectName("primaryButton")
        export.clicked.connect(self.export_requested)
        import_button = QPushButton("导入 JSON…", self)
        import_button.clicked.connect(self.import_requested)
        new_button = QPushButton("新建会话", self)
        new_button.clicked.connect(self.new_session_requested)
        row.addWidget(export)
        row.addWidget(import_button)
        row.addWidget(new_button)
        row.addStretch(1)
        layout.addLayout(row)

        hint = QLabel(
            "导入支持两种模式：新建会话（推荐，绝不覆盖当前对话）或合并到当前会话。"
            "导入文件会先校验格式与版本，坏文件会被拒绝。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #667085;")
        layout.addWidget(hint)
        layout.addStretch(1)

    def refresh(self, *, session_id: str, title: str, messages: int, actions: int, database: str) -> None:
        self._session_label.setText(f"会话：{title}（{session_id}）")
        self._counts_label.setText(f"消息 {messages} 条 · 动作 {actions} 条")
        self._path_label.setText(f"数据库：{database}")
