"""Render the main window to a PNG (docs screenshot helper).

Usage::

    python scripts/capture_window.py [output.png] [--offscreen] [--wait 2.0]

The window is shown briefly; `--wait` gives slow device checks time to
finish before the grab. Use `--offscreen` on machines without a desktop
session (fonts may fall back to boxes).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    offscreen = "--offscreen" in args
    wait_seconds = 0.0
    tab_index = 0
    if "--tab" in args:
        index = args.index("--tab")
        try:
            tab_index = int(args[index + 1])
        except (IndexError, ValueError):
            tab_index = 0
        del args[index : index + 2]
    if "--wait" in args:
        index = args.index("--wait")
        try:
            wait_seconds = float(args[index + 1])
        except (IndexError, ValueError):
            wait_seconds = 0.0
        del args[index : index + 2]
    args = [arg for arg in args if arg != "--offscreen"]
    if offscreen:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from app.main_window import MainWindow
    from app.style import STYLESHEET
    from config.settings import AppSettings

    target = Path(args[0]) if args else REPO_ROOT / "docs" / "screenshots" / "main_window.png"
    target.parent.mkdir(parents=True, exist_ok=True)

    application = QApplication([sys.argv[0]])
    application.setStyleSheet(STYLESHEET)
    window = MainWindow(AppSettings.load())
    window.resize(1200, 820)
    window.show()

    if 0 <= tab_index < window._tabs.count():
        window._tabs.setCurrentIndex(tab_index)
    deadline = time.monotonic() + max(0.0, wait_seconds)
    while time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.05)

    if not window.grab().save(str(target)):
        print(f"failed to save screenshot to {target}", file=sys.stderr)
        return 1
    print(str(target))
    window.close()
    application.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
