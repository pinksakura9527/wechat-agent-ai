"""API configuration panel (Base URL / Key / model / sampling)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from config.settings import ApiConfig


class ApiPanel(QWidget):
    """Edits a copy of `ApiConfig` and emits it on save."""

    api_saved = Signal(object)

    def __init__(self, config: ApiConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        group = QGroupBox("OpenAI 兼容接口配置", self)
        form = QFormLayout(group)

        self._base_url = QLineEdit(config.base_url, self)
        self._base_url.setPlaceholderText("https://api.openai.com/v1")
        form.addRow("Base URL", self._base_url)

        key_row = QHBoxLayout()
        self._api_key = QLineEdit(config.api_key, self)
        self._api_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key.setPlaceholderText("sk-...")
        self._show_key = QPushButton("显示", self)
        self._show_key.setCheckable(True)
        self._show_key.toggled.connect(self._toggle_key_visible)
        key_row.addWidget(self._api_key, 1)
        key_row.addWidget(self._show_key)
        form.addRow("API Key", key_row)

        self._model = QLineEdit(config.model, self)
        self._model.setPlaceholderText("gpt-4o-mini / deepseek-chat / qwen2.5 ...")
        form.addRow("模型名", self._model)

        self._max_tokens = QSpinBox(self)
        self._max_tokens.setRange(64, 32768)
        self._max_tokens.setSingleStep(64)
        self._max_tokens.setValue(config.max_tokens)
        form.addRow("最大 Token", self._max_tokens)

        self._temperature = QDoubleSpinBox(self)
        self._temperature.setRange(0.0, 2.0)
        self._temperature.setSingleStep(0.1)
        self._temperature.setValue(config.temperature)
        form.addRow("温度", self._temperature)

        self._timeout = QDoubleSpinBox(self)
        self._timeout.setRange(5.0, 300.0)
        self._timeout.setSingleStep(5.0)
        self._timeout.setValue(config.timeout_seconds)
        form.addRow("请求超时（秒）", self._timeout)

        layout.addWidget(group)

        actions = QHBoxLayout()
        self._save = QPushButton("保存配置", self)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._save_clicked)
        actions.addWidget(self._save)
        actions.addStretch(1)
        layout.addLayout(actions)

        note = QLabel(
            "配置保存在用户目录（%APPDATA%\\WeChatAgentAI\\settings.json），不会写入仓库。"
            "API Key 仅在本机使用，但请求内容会发送给你配置的服务商。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #667085;")
        layout.addWidget(note)
        layout.addStretch(1)

    def _toggle_key_visible(self, visible: bool) -> None:
        self._api_key.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self._show_key.setText("隐藏" if visible else "显示")

    def _save_clicked(self) -> None:
        config = ApiConfig(
            base_url=self._base_url.text().strip(),
            api_key=self._api_key.text().strip(),
            model=self._model.text().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
            timeout_seconds=self._timeout.value(),
        )
        self.api_saved.emit(config)

    def reload(self, config: ApiConfig) -> None:
        self._base_url.setText(config.base_url)
        self._api_key.setText(config.api_key)
        self._model.setText(config.model)
        self._max_tokens.setValue(config.max_tokens)
        self._temperature.setValue(config.temperature)
        self._timeout.setValue(config.timeout_seconds)
