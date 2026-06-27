from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon

from app_models import MemoStore
from app_theme import resolve_theme
from memo_window import StickyMemoWindow


class MemoWindowApp:
    def __init__(self, notes_dir: Path) -> None:
        self.config = {
            "theme_mode": "dark",
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


def test_empty_memo_title_displays_blank(qtbot, tmp_path: Path) -> None:
    app = MemoWindowApp(tmp_path)

    window = StickyMemoWindow(app, "memo-1")
    qtbot.addWidget(window)

    assert window.title_label.text() == ""


def test_clearing_memo_title_displays_blank(qtbot, tmp_path: Path) -> None:
    app = MemoWindowApp(tmp_path)
    app.config["memo_titles"]["memo-1"] = "회의 메모"
    window = StickyMemoWindow(app, "memo-1")
    qtbot.addWidget(window)

    window.start_title_edit()
    window.title_edit.clear()
    window.finish_title_edit()

    assert window.title_label.text() == ""
    assert "memo-1" not in app.config["memo_titles"]
