"""API configuration panel (provider preset / Base URL / Key / model)."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
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

from app.worker import ConnectionTestWorker
from config.providers import PROVIDER_PRESETS, match_preset
from config.settings import ApiConfig


class ApiPanel(QWidget):
    """Edits a copy of `ApiConfig` and emits it on save."""

    api_saved = Signal(object)

    def __init__(self, config: ApiConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)

        group = QGroupBox("OpenAI 兼容接口配置", self)
        form = QFormLayout(group)

        self._provider = QComboBox(self)
        self._provider.addItems([preset.name for preset in PROVIDER_PRESETS])
        self._provider.setCurrentIndex(match_preset(config.base_url, config.model))
        self._provider.currentIndexChanged.connect(self._apply_provider)
        form.addRow("服务商预设", self._provider)

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
        self._model.setPlaceholderText("gpt-4o-mini / deepseek-chat / qwen-vl-max ...")
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

        self._provider_hint = QLabel(self)
        self._provider_hint.setWordWrap(True)
        layout.addWidget(self._provider_hint)
        self._update_hint(PROVIDER_PRESETS[self._provider.currentIndex()])

        actions = QHBoxLayout()
        self._save = QPushButton("保存配置", self)
        self._save.setObjectName("primaryButton")
        self._save.clicked.connect(self._save_clicked)
        actions.addWidget(self._save)
        self._test_button = QPushButton("测试连接", self)
        self._test_button.clicked.connect(self._test_clicked)
        actions.addWidget(self._test_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self._test_worker: ConnectionTestWorker | None = None
        self._test_result = QLabel("", self)
        self._test_result.setWordWrap(True)
        layout.addWidget(self._test_result)

        note = QLabel(
            "任何 OpenAI 兼容接口都可以用：DeepSeek、通义千问、豆包、智谱、Kimi、Ollama 等，"
            "只要填对 Base URL 和模型名。微信操作依赖截图，请选择支持图片输入的模型。"
            "配置保存在用户目录（%APPDATA%\\WeChatAgentAI\\settings.json），不会写入仓库。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #667085;")
        layout.addWidget(note)
        layout.addStretch(1)

    # ------------------------------------------------------------------ slots
    def _apply_provider(self, index: int) -> None:
        preset = PROVIDER_PRESETS[index]
        if preset.base_url:
            self._base_url.setText(preset.base_url)
        if preset.model:
            self._model.setText(preset.model)
        self._update_hint(preset)

    def _update_hint(self, preset) -> None:
        if preset.vision:
            self._provider_hint.setText("✅ " + preset.note)
            self._provider_hint.setStyleSheet("color: #027a48;")
        else:
            self._provider_hint.setText("⚠ " + preset.note)
            self._provider_hint.setStyleSheet("color: #b42318;")

    def _toggle_key_visible(self, visible: bool) -> None:
        self._api_key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        )
        self._show_key.setText("隐藏" if visible else "显示")

    def _current_config(self) -> ApiConfig:
        return ApiConfig(
            base_url=self._base_url.text().strip(),
            api_key=self._api_key.text().strip(),
            model=self._model.text().strip(),
            max_tokens=self._max_tokens.value(),
            temperature=self._temperature.value(),
            timeout_seconds=self._timeout.value(),
        )

    def _save_clicked(self) -> None:
        self.api_saved.emit(self._current_config())

    def _test_clicked(self) -> None:
        config = self._current_config()
        if not config.api_key.strip():
            self._test_result.setText("❌ 请先填写 API Key")
            self._test_result.setStyleSheet("color: #b42318;")
            return
        self._test_button.setEnabled(False)
        self._test_result.setText("正在请求模型…")
        self._test_result.setStyleSheet("color: #667085;")
        self._test_worker = ConnectionTestWorker(config)
        self._test_worker.result.connect(self._on_test_result)
        self._test_worker.start()

    def _on_test_result(self, ok: bool, message: str) -> None:
        self._test_button.setEnabled(True)
        self._test_result.setText(("✅ " if ok else "❌ ") + message)
        self._test_result.setStyleSheet("color: #027a48;" if ok else "color: #b42318;")

    def reload(self, config: ApiConfig) -> None:
        self._base_url.setText(config.base_url)
        self._api_key.setText(config.api_key)
        self._model.setText(config.model)
        self._max_tokens.setValue(config.max_tokens)
        self._temperature.setValue(config.temperature)
        self._timeout.setValue(config.timeout_seconds)
        self._provider.setCurrentIndex(match_preset(config.base_url, config.model))
