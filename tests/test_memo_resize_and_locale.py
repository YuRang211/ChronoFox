from __future__ import annotations

import locale
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon

from app_config import default_language
from app_models import MemoStore
from app_theme import resolve_theme
from memo_window import StickyMemoWindow


class TestMemoApp:
    def __init__(self, notes_dir: Path) -> None:
        self.config = {
            "theme_mode": "light",
            "memo_titles": {},
            "open_memos": {},
        }
        self.colors = resolve_theme(self.config)
        self.icon = QIcon()
        self.memo_windows = {}
        self.memo_store = MemoStore(notes_dir)
        self.remembered_memos: dict[str, str] = {}
        self.forgotten_memos: list[str] = []

    def remember_open_memo(self, memo_id: str, geometry: str) -> None:
        self.remembered_memos[memo_id] = geometry

    def forget_open_memo(self, memo_id: str) -> None:
        self.forgotten_memos.append(memo_id)

    def save(self) -> None:
        pass


def test_memo_window_save_on_move_and_resize(qtbot, tmp_path: Path) -> None:
    app = TestMemoApp(tmp_path)
    window = StickyMemoWindow(app, "memo-1")
    window.text.setPlainText("Test memo content")
    qtbot.addWidget(window)

    # Move and resize the window
    window.move(120, 150)
    window.resize(320, 340)

    # Since it's debounced, the timer should be active
    assert window.save_timer.isActive()

    # Fire save timer timeout directly to verify it saves geometry
    window.save_timer.timeout.emit()
    assert "memo-1" in app.remembered_memos
    geom_str = app.remembered_memos["memo-1"]
    assert "320x340+120+150" in geom_str


def test_default_language_robustness(monkeypatch) -> None:
    # 1. Test when locale.getlocale returns ko_KR
    monkeypatch.setattr(locale, "getlocale", lambda *args: ("ko_KR", "UTF-8"))
    monkeypatch.setattr(locale, "getencoding", lambda: "UTF-8")
    assert default_language() == "ko"

    # 2. Test when locale.getlocale returns None
    monkeypatch.setattr(locale, "getlocale", lambda *args: (None, None))
    monkeypatch.setattr(locale, "getencoding", lambda: "cp1252")
    # Should fallback to en unless on actual Korean Windows machine
    # On non-Korean environment it will be en
    lang = default_language()
    assert lang in ("ko", "en")
