"""Persona editor panel."""

from __future__ import annotations

from pathlib import Path

from config.settings import bundled_file, persona_path
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PersonaPanel(QWidget):
    """Multi-line persona editor with load/save helpers."""

    persona_saved = Signal(str)

    def __init__(self, persona: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        self._editor = QPlainTextEdit(self)
        self._editor.setPlainText(persona)
        layout.addWidget(self._editor, 1)

        row = QHBoxLayout()
        save = QPushButton("保存人设", self)
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        load_file = QPushButton("从文件加载…", self)
        load_file.clicked.connect(self._load_from_file)
        save_file = QPushButton("另存为…", self)
        save_file.clicked.connect(self._save_to_file)
        restore = QPushButton("恢复默认", self)
        restore.clicked.connect(self._restore_default)
        for button in (save, load_file, save_file, restore):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)

        hint = QLabel(
            "人设会作为系统提示词的一部分注入每轮对话。保存后立即生效；"
            "文件保存在用户目录的 persona.md。",
            self,
        )
        hint.setStyleSheet("color: #667085;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def text(self) -> str:
        return self._editor.toPlainText()

    def set_text(self, persona: str) -> None:
        self._editor.setPlainText(persona)

    def _save(self) -> None:
        target = persona_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.text(), encoding="utf-8")
        self.persona_saved.emit(self.text())

    def _load_from_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "加载人设", "", "Markdown (*.md *.txt);;所有文件 (*)")
        if not path:
            return
        try:
            self._editor.setPlainText(Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            QMessageBox.warning(self, "加载失败", str(exc))

    def _save_to_file(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "保存人设", "persona.md", "Markdown (*.md);;所有文件 (*)")
        if not path:
            return
        try:
            Path(path).write_text(self.text(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))

    def _restore_default(self) -> None:
        answer = QMessageBox.question(
            self,
            "恢复默认人设",
            "将用内置人设覆盖当前编辑内容，确定吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._editor.setPlainText(bundled_file("default_persona.md").read_text(encoding="utf-8"))

