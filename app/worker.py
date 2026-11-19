"""QThread workers that keep the UI responsive."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal


class InstructionWorker(QThread):
    """Runs one agent instruction off the UI thread."""

    failed = Signal(str)
    completed = Signal()

    def __init__(self, loop, text: str) -> None:
        super().__init__()
        self._loop = loop
        self._text = text

    def run(self) -> None:  # noqa: D401 - Qt entry point
        try:
            self._loop.run_instruction(self._text)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
            self.failed.emit(str(exc))
            return
        self.completed.emit()


class DeviceCheckWorker(QThread):
    """Probes the emulator without blocking the window."""

    checked = Signal(bool, str)

    def __init__(self, runner) -> None:
        super().__init__()
        self._runner = runner

    def run(self) -> None:
        try:
            result = self._runner.call("device_status", {})
        except Exception as exc:  # noqa: BLE001
            self.checked.emit(False, str(exc))
            return
        if result.ok:
            summary = " ".join(result.text.split())
            self.checked.emit(True, summary[:120])
        else:
            self.checked.emit(False, result.text or "device check failed")
