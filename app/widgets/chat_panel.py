"""Chat / action log panel.

Shows user instructions, assistant text and compact tool summaries. Raw UI
dumps never enter this widget: the agent loop already trims and summarises
them, and the log only keeps the first line.
"""

from __future__ import annotations

import html

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class ChatPanel(QWidget):
    """Instruction input plus a read-only conversation/log view."""

    instruction_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._log = QTextBrowser(self)
        self._log.setOpenExternalLinks(False)
        self._log.setFont(QFont("Microsoft YaHei UI", 10))
        layout.addWidget(self._log, 1)

        input_row = QHBoxLayout()
        self._input = QPlainTextEdit(self)
        self._input.setPlaceholderText("输入指令，例如：给张三发一条消息，说我会晚点到（Enter 发送，Shift+Enter 换行）")
        self._input.setFixedHeight(74)
        self._input.installEventFilter(self)
        input_row.addWidget(self._input, 1)

        self._send = QPushButton("发送", self)
        self._send.setObjectName("primaryButton")
        self._send.setFixedHeight(34)
        self._send.clicked.connect(self._submit)
        input_row.addWidget(self._send, 0, Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(input_row)

        self._hint = QLabel("AI 未启动：点击右侧“开启 AI 控制”后即可发送指令。", self)
        self._hint.setStyleSheet("color: #667085;")
        layout.addWidget(self._hint)

        self._running = False
        self._busy = False
        self._input.setEnabled(False)
        self._send.setEnabled(False)

    # ------------------------------------------------------------------ input
    def eventFilter(self, watched, event):  # noqa: N802 - Qt naming
        if (
            watched is self._input
            and event.type() == QEvent.Type.KeyPress
            and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        ):
            self._submit()
            return True
        return super().eventFilter(watched, event)

    def _submit(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.instruction_submitted.emit(text)

    def set_busy(self, busy: bool) -> None:
        """Disable the input while a worker runs, without changing the hint."""
        self._busy = busy
        enabled = self._running and not busy
        self._input.setEnabled(enabled)
        self._send.setEnabled(enabled)

    def set_running(self, running: bool) -> None:
        self._running = running
        enabled = running and not self._busy
        self._input.setEnabled(enabled)
        self._send.setEnabled(enabled)
        self._hint.setText(
            "AI 运行中：指令会驱动模拟器里的微信。随时可点击“停止”。"
            if running
            else "AI 未启动：点击右侧“开启 AI 控制”后即可发送指令。"
        )

    # ------------------------------------------------------------------- log
    def append_user(self, text: str) -> None:
        self._append("你", html.escape(text), "#101828", "#eef4ff")

    def append_assistant(self, text: str) -> None:
        self._append("AI", html.escape(text), "#101828", "#f9fafb")

    def append_tool(self, name: str, summary: str, ok: bool = True) -> None:
        color = "#027a48" if ok else "#b42318"
        label = "工具" if ok else "工具失败"
        self._append(label, f"{html.escape(name)} · {html.escape(summary)}", color, "#f9fafb")

    def append_error(self, text: str) -> None:
        self._append("错误", html.escape(text), "#b42318", "#fef3f2")

    def append_notice(self, text: str) -> None:
        self._append("提示", html.escape(text), "#475467", "#f2f4f7")

    def _append(self, speaker: str, body: str, color: str, background: str) -> None:
        self._log.append(
            '<div style="margin:6px 0; padding:8px 10px; background:{}; border-radius:6px;">'
            '<span style="color:{}; font-weight:600;">{}</span>'
            '<div style="color:#344054; margin-top:2px;">{}</div></div>'.format(
                background, color, speaker, body.replace("\n", "<br/>")
            )
        )
        self._log.verticalScrollBar().setValue(self._log.verticalScrollBar().maximum())

    def clear(self) -> None:
        self._log.clear()
