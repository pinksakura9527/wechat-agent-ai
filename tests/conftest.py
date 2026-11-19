"""Shared pytest fixtures.

Tests must run without an emulator and without a desktop session: llmadb is
mocked where needed and Qt uses the offscreen platform.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Must be set before QApplication is created by pytest-qt.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture()
def data_home(tmp_path, monkeypatch):
    """Point the app data directory at a temporary folder."""
    monkeypatch.setenv("WECHAT_AGENT_HOME", str(tmp_path / "home"))
    return tmp_path / "home"
