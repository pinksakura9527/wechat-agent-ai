"""Application entry point: `wechat-agent` / `python -m app.main`."""

from __future__ import annotations

import sys


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow
    from app.style import STYLESHEET
    from config.settings import AppSettings

    application = QApplication(sys.argv)
    application.setApplicationName("WeChat Agent AI")
    application.setOrganizationName("WeChatAgentAI")
    application.setStyleSheet(STYLESHEET)

    window = MainWindow(AppSettings.load())
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
