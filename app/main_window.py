"""Main window: wires the panels to the agent loop, memory and settings.

This module contains presentation logic only. Device work, permissions and
persistence live in `agent/` and `memory/`; the window just connects them
and renders `AgentEvent` objects on the UI thread.
"""

from __future__ import annotations

import contextlib
import json
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from agent.llm_client import OpenAICompatClient
from agent.llmadb import LLMadbRunner
from agent.loop import AgentEvent, AgentLoop, EventKind, LoopLimits
from agent.permissions import PermissionConfig, PermissionGuard, load_permission_config
from agent.prompts import load_wechat_guide
from app.widgets.api_panel import ApiPanel
from app.widgets.chat_panel import ChatPanel
from app.widgets.memory_panel import MemoryPanel
from app.widgets.permissions_panel import PermissionsPanel
from app.widgets.persona_panel import PersonaPanel
from app.worker import DeviceCheckWorker, InstructionWorker
from config.settings import (
    AppSettings,
    bundled_file,
    permissions_path,
    persona_path,
    user_data_dir,
)
from memory import MemoryStore, export_session, import_session

RISK_TEXT = (
    "⚠ 风险提示：在模拟器上运行微信自动化存在账号风控风险。"
    "微信用户协议禁止自动化工具，模拟器的虚拟环境特征也可能触发风控。"
    "请使用小号测试、控制操作频率、避免机械式精确点击。"
)

STATE_LABELS = {
    "idle": "AI 运行中 · 空闲",
    "thinking": "AI 思考中…",
    "executing": "正在执行设备操作…",
    "stopped": "已暂停",
    "error": "出错了，请查看日志",
}


class MainWindow(QMainWindow):
    """The single application window."""

    agent_event = Signal(object)

    def __init__(self, settings: AppSettings) -> None:
        super().__init__()
        self._settings = settings
        self._store = MemoryStore()
        self._store.connect()
        self._persona = self._load_persona()
        self._session = self._restore_session()
        self._permissions = load_permission_config()

        self._running = False
        self._busy = False
        self._loop: AgentLoop | None = None
        self._guard: PermissionGuard | None = None
        self._runner: LLMadbRunner | None = None
        self._llm: OpenAICompatClient | None = None
        self._worker: InstructionWorker | None = None
        self._device_worker: DeviceCheckWorker | None = None

        self.setWindowTitle("WeChat Agent AI — LLM 驱动的微信桌面助理")
        self.resize(1280, 860)
        self._build_ui()
        self._connect_signals()
        self.agent_event.connect(self._on_agent_event)
        self._restore_log(announce=True)
        self._refresh_memory_panel()
        self._check_device()

    # ------------------------------------------------------------------ setup
    def _restore_session(self):
        sessions = self._store.list_sessions(limit=1)
        if sessions:
            return sessions[0]
        return self._store.create_session(title="新会话", persona_snapshot=self._persona)

    def _load_persona(self) -> str:
        target = persona_path()
        if target.is_file():
            try:
                return target.read_text(encoding="utf-8")
            except OSError:
                pass
        return bundled_file("default_persona.md").read_text(encoding="utf-8")

    def _build_ui(self) -> None:
        central = QWidget(self)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        banner = QLabel(RISK_TEXT, self)
        banner.setWordWrap(True)
        banner.setStyleSheet(
            "background: #fff4e5; color: #8a4b00; border: 1px solid #ffd8a8;"
            " border-radius: 6px; padding: 8px;"
        )
        outer.addWidget(banner)

        body = QHBoxLayout()
        body.setSpacing(12)

        self._tabs = QTabWidget(self)
        self._chat_panel = ChatPanel(self)
        self._api_panel = ApiPanel(self._settings.api, self)
        self._persona_panel = PersonaPanel(self._persona, self)
        self._permissions_panel = PermissionsPanel(self._permissions, self._settings.runtime, self)
        self._memory_panel = MemoryPanel(self)
        self._tabs.addTab(self._chat_panel, "聊天 / 日志")
        self._tabs.addTab(self._api_panel, "API 配置")
        self._tabs.addTab(self._persona_panel, "人设")
        self._tabs.addTab(self._permissions_panel, "权限")
        self._tabs.addTab(self._memory_panel, "记忆")
        body.addWidget(self._tabs, 1)

        side = QWidget(self)
        side.setFixedWidth(280)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)

        title = QLabel("AI 控制", side)
        title.setStyleSheet("font-size: 15px; font-weight: 700; color: #101828;")
        side_layout.addWidget(title)

        self._master_button = QPushButton("▶ 开启 AI 控制", side)
        self._master_button.setObjectName("primaryButton")
        self._master_button.setFixedHeight(42)
        side_layout.addWidget(self._master_button)

        self._state_label = QLabel("已暂停", side)
        self._state_label.setStyleSheet("color: #667085;")
        side_layout.addWidget(self._state_label)

        divider = QLabel("设备与权限", side)
        divider.setStyleSheet("margin-top: 14px; font-weight: 600; color: #344054;")
        side_layout.addWidget(divider)

        self._device_label = QLabel("模拟器：检测中…", side)
        self._device_label.setWordWrap(True)
        side_layout.addWidget(self._device_label)

        self._device_button = QPushButton("重新检测模拟器", side)
        side_layout.addWidget(self._device_button)

        self._session_label = QLabel("", side)
        self._session_label.setWordWrap(True)
        self._session_label.setStyleSheet("color: #475467; margin-top: 8px;")
        side_layout.addWidget(self._session_label)

        open_dir = QPushButton("打开数据目录", side)
        open_dir.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(user_data_dir())))
        )
        side_layout.addWidget(open_dir)

        side_layout.addStretch(1)
        body.addWidget(side)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage(f"数据目录：{user_data_dir()}")

    def _connect_signals(self) -> None:
        self._chat_panel.instruction_submitted.connect(self._send_instruction)
        self._api_panel.api_saved.connect(self._on_api_saved)
        self._persona_panel.persona_saved.connect(self._on_persona_saved)
        self._permissions_panel.permissions_changed.connect(self._on_permissions_changed)
        self._permissions_panel.runtime_changed.connect(self._on_runtime_changed)
        self._memory_panel.export_requested.connect(self._export_session)
        self._memory_panel.import_requested.connect(self._import_session)
        self._memory_panel.new_session_requested.connect(self._new_session)
        self._master_button.clicked.connect(self._toggle_agent)
        self._device_button.clicked.connect(self._check_device)

    # ------------------------------------------------------------------ agent
    def _toggle_agent(self) -> None:
        if self._running:
            self._stop_agent()
        else:
            self._start_agent()

    def _start_agent(self) -> None:
        problems = self._settings.api.validate()
        if not self._settings.api.api_key.strip():
            problems.append("API Key 为空")
        if problems:
            QMessageBox.warning(self, "配置不完整", "请先完成 API 配置：\n- " + "\n- ".join(problems))
            self._tabs.setCurrentWidget(self._api_panel)
            return

        self._runner = LLMadbRunner(
            llmadb=self._settings.runtime.llmadb_path or None,
            adb=self._settings.runtime.adb_path or None,
            serial=self._settings.runtime.device_serial or None,
            allow_unicode=self._settings.runtime.unicode_input,
        )
        self._guard = PermissionGuard(self._permissions)
        self._llm = OpenAICompatClient(self._settings.api)
        limits = LoopLimits(
            max_steps=self._settings.runtime.max_steps,
            step_delay_ms=self._settings.runtime.step_delay_ms,
        )
        self._loop = AgentLoop(
            llm=self._llm,
            runner=self._runner,
            guard=self._guard,
            session_id=self._session.session_id,
            persona=self._persona,
            permissions=self._permissions,
            limits=limits,
            memory=self._store,
            listener=self.agent_event.emit,
            sleep=time.sleep,
            guide=load_wechat_guide(),
            send_screenshots=self._settings.runtime.send_screenshots,
        )
        self._loop.load_history(self._store.session_history(self._session.session_id, limit=40))
        if self._settings.runtime.unicode_input:
            try:
                self._runner.prepare_unicode()
            except Exception:  # noqa: BLE001 - never block startup on IME issues
                self._chat_panel.append_notice("ADBKeyboard 未就绪：中文输入可能不可用，请运行 scripts/setup_adbkeyboard.py。")
        self._running = True
        self._master_button.setText("■ 停止 AI 控制")
        self._master_button.setProperty("stopping", "true")
        self._master_button.style().unpolish(self._master_button)
        self._master_button.style().polish(self._master_button)
        self._state_label.setText("AI 运行中 · 等待指令")
        self._chat_panel.set_running(True)
        self._chat_panel.append_notice("AI 控制已开启。关闭时点“停止”，会立即取消正在进行的设备操作。")
        self._check_device()

    def _stop_agent(self) -> None:
        if self._loop is not None:
            self._loop.stop()
        if self._runner is not None:
            with contextlib.suppress(Exception):  # never block shutdown on IME restore
                self._runner.restore_unicode()
        self._running = False
        self._master_button.setText("▶ 开启 AI 控制")
        self._master_button.setProperty("stopping", "false")
        self._master_button.style().unpolish(self._master_button)
        self._master_button.style().polish(self._master_button)
        self._state_label.setText("已暂停")
        self._chat_panel.set_running(False)
        self._chat_panel.append_notice("AI 控制已暂停。")

    def _send_instruction(self, text: str) -> None:
        if not self._running or self._loop is None:
            self._chat_panel.append_notice("请先点击“开启 AI 控制”。")
            return
        if self._busy:
            self._chat_panel.append_notice("上一个指令还在执行，请稍候或先停止。")
            return
        self._chat_panel.append_user(text)
        self._busy = True
        self._chat_panel.set_busy(True)
        self._worker = InstructionWorker(self._loop, text)
        self._worker.completed.connect(self._on_worker_completed)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.start()

    def _on_worker_completed(self) -> None:
        self._busy = False
        self._chat_panel.set_busy(False)
        self._refresh_memory_panel()

    def _on_worker_failed(self, message: str) -> None:
        self._busy = False
        self._chat_panel.set_busy(False)
        self._chat_panel.append_error(message)
        self._refresh_memory_panel()

    def _on_agent_event(self, event: AgentEvent) -> None:
        payload = event.payload or {}
        if event.kind is EventKind.ASSISTANT_TEXT:
            self._chat_panel.append_assistant(str(payload.get("text", "")))
        elif event.kind is EventKind.TOOL_CALL:
            arguments = payload.get("arguments") or {}
            compact = json.dumps(arguments, ensure_ascii=False)
            if len(compact) > 140:
                compact = compact[:140] + "…"
            self._chat_panel.append_tool(str(payload.get("name", "?")), "调用 " + compact, True)
        elif event.kind is EventKind.TOOL_RESULT:
            name = str(payload.get("name", "?"))
            if payload.get("ok"):
                self._chat_panel.append_tool(name, str(payload.get("summary", "完成")), True)
            else:
                detail = str(payload.get("message") or payload.get("error") or "失败")
                hint = str(payload.get("hint") or "")
                self._chat_panel.append_tool(name, detail + (f"（{hint}）" if hint else ""), False)
        elif event.kind is EventKind.ERROR:
            self._chat_panel.append_error(str(payload.get("message", "未知错误")))
        elif event.kind is EventKind.STATE_CHANGED:
            self._state_label.setText(STATE_LABELS.get(str(payload.get("state")), "AI 运行中"))

    # ------------------------------------------------------------------ device
    def _check_device(self) -> None:
        if self._device_worker is not None and self._device_worker.isRunning():
            return
        self._device_label.setText("模拟器：检测中…")
        self._device_button.setEnabled(False)
        runner = self._runner or LLMadbRunner(
            llmadb=self._settings.runtime.llmadb_path or None,
            adb=self._settings.runtime.adb_path or None,
            serial=self._settings.runtime.device_serial or None,
        )
        self._device_worker = DeviceCheckWorker(runner)
        self._device_worker.checked.connect(self._on_device_checked)
        self._device_worker.start()

    def _on_device_checked(self, ok: bool, detail: str) -> None:
        self._device_button.setEnabled(True)
        if ok:
            self._device_label.setText("模拟器：已连接 ✅\n" + detail)
            self._device_label.setStyleSheet("color: #027a48;")
        else:
            self._device_label.setText("模拟器：未连接 ❌\n" + detail)
            self._device_label.setStyleSheet("color: #b42318;")

    # ------------------------------------------------------------------ config
    def _on_api_saved(self, config) -> None:
        problems = config.validate()
        if problems:
            QMessageBox.warning(self, "配置有误", "\n".join(problems))
            return
        self._settings.api = config
        try:
            self._settings.save()
        except OSError as exc:
            QMessageBox.warning(self, "保存失败", str(exc))
            return
        if self._llm is not None:
            self._llm.configure(config)
        self._chat_panel.append_notice("API 配置已保存。")

    def _on_persona_saved(self, persona: str) -> None:
        self._persona = persona
        self._store.update_persona_snapshot(self._session.session_id, persona)
        if self._loop is not None:
            self._loop.set_persona(persona)
        self._chat_panel.append_notice("人设已保存，下一轮对话生效。")

    def _on_permissions_changed(self, config: PermissionConfig) -> None:
        self._permissions = config
        try:
            permissions_path().write_text(
                json.dumps(config.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        except OSError as exc:
            QMessageBox.warning(self, "保存权限失败", str(exc))
        if self._guard is not None:
            self._guard.update(config)
        if self._loop is not None:
            self._loop.set_permissions(config)
        self._chat_panel.append_notice("权限已更新。")

    def _on_runtime_changed(self, runtime) -> None:
        self._settings.runtime = runtime
        try:
            self._settings.save()
        except OSError as exc:
            QMessageBox.warning(self, "保存设置失败", str(exc))
        if self._runner is not None:
            self._runner.allow_unicode = runtime.unicode_input
        if self._loop is not None:
            self._loop.set_send_screenshots(runtime.send_screenshots)
        self._chat_panel.append_notice("输入与视觉设置已更新。")

    # ------------------------------------------------------------------ memory
    def _refresh_memory_panel(self) -> None:
        self._memory_panel.refresh(
            session_id=self._session.session_id,
            title=self._session.title,
            messages=self._store.count_messages(self._session.session_id),
            actions=self._store.count_actions(self._session.session_id),
            database=str(self._store.database),
        )
        self._session_label.setText(
            f"当前会话：{self._session.title}\n消息 {self._store.count_messages(self._session.session_id)} · 动作 {self._store.count_actions(self._session.session_id)}"
        )

    def _restore_log(self, *, announce: bool = False) -> None:
        self._chat_panel.clear()
        if announce:
            self._chat_panel.append_notice(
                f"已恢复会话「{self._session.title}」。历史消息会作为上下文继续使用。"
            )
        for record in self._store.list_messages(self._session.session_id):
            if record.role == "user":
                self._chat_panel.append_user(record.content)
            elif record.role == "assistant" and record.content:
                self._chat_panel.append_assistant(record.content)
            elif record.role == "tool":
                text = record.content.replace("\n", " ")
                self._chat_panel.append_tool("结果", text[:160], True)

    def _new_session(self) -> None:
        if self._running:
            self._stop_agent()
        self._session = self._store.create_session(
            title="新会话 " + datetime.now().strftime("%m-%d %H:%M"),
            persona_snapshot=self._persona,
        )
        self._restore_log()
        self._refresh_memory_panel()
        self._chat_panel.append_notice("已新建会话。")

    def _ask_import_mode(self) -> str | None:
        box = QMessageBox(self)
        box.setWindowTitle("导入方式")
        box.setText("选择导入方式：")
        box.setInformativeText("“新建会话”不会影响当前对话；“合并到当前”会把历史追加进来。")
        new_button = box.addButton("新建会话（推荐）", QMessageBox.ButtonRole.AcceptRole)
        merge_button = box.addButton("合并到当前会话", QMessageBox.ButtonRole.ActionRole)
        box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is new_button:
            return "new_session"
        if box.clickedButton() is merge_button:
            return "merge_current"
        return None

    def _export_session(self) -> None:
        default = "wechat-session-{}.json".format(datetime.now().strftime("%Y%m%d-%H%M"))
        path, _ = QFileDialog.getSaveFileName(self, "导出会话", default, "JSON (*.json)")
        if not path:
            return
        try:
            target = export_session(
                self._store,
                self._session.session_id,
                path,
                persona=self._persona,
                permissions=self._permissions.to_dict(),
            )
        except (OSError, KeyError) as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        QMessageBox.information(self, "导出完成", f"已导出到：\n{target}")

    def _import_session(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入会话", "", "JSON (*.json);;所有文件 (*)")
        if not path:
            return
        mode = self._ask_import_mode()
        if mode is None:
            return
        if self._running:
            self._stop_agent()
        try:
            summary = import_session(
                self._store,
                path,
                mode=mode,
                current_session_id=self._session.session_id if mode == "merge_current" else None,
            )
        except Exception as exc:  # noqa: BLE001 - surface format errors to the user
            QMessageBox.warning(self, "导入失败", str(exc))
            return

        if mode == "new_session":
            session = self._store.get_session(summary["session_id"])
            if session is not None:
                self._session = session
        self._restore_log()
        self._refresh_memory_panel()

        answer = QMessageBox.question(
            self,
            "应用导入的配置？",
            "是否同时应用文件里的人设与权限配置？\n（选择否将保留当前配置）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._apply_imported_config(summary)

        self._chat_panel.append_notice(
            "导入完成：{} 条消息、{} 条动作（{}）。".format(
                summary["messages"], summary["actions"], summary["mode"]
            )
        )

    def _apply_imported_config(self, summary: dict[str, Any]) -> None:
        persona = summary.get("persona") or ""
        if persona:
            self._persona = persona
            self._persona_panel.set_text(persona)
            with contextlib.suppress(OSError):
                persona_path().write_text(persona, encoding="utf-8")
            if self._loop is not None:
                self._loop.set_persona(persona)
        raw_permissions = summary.get("permissions") or {}
        try:
            config = PermissionConfig.from_dict(raw_permissions)
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "权限配置无效", str(exc))
            return
        self._permissions = config
        self._permissions_panel.set_config(config)
        self._on_permissions_changed(config)

    # ------------------------------------------------------------------ close
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._loop is not None:
            self._loop.stop()
        for worker in (self._worker, self._device_worker):
            if worker is not None and worker.isRunning():
                worker.wait(3000)
        self._store.close()
        super().closeEvent(event)
