from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect
from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from desktop_note_calendar import FoxCalendarApp
from todo_window import AddRepeatTaskWindow, RepeatWindow


class VisibleThemeWindow:
    def __init__(self) -> None:
        self.theme_calls = 0
        self.note_theme_calls = 0

    def isVisible(self) -> bool:
        return True

    def apply_theme(self) -> None:
        self.theme_calls += 1

    def apply_note_theme(self) -> None:
        self.note_theme_calls += 1


class ThemeRefreshApp(FoxCalendarApp):
    def __init__(self, memo_window: VisibleThemeWindow) -> None:
        self.config = {"theme_mode": "light"}
        self.colors = resolve_theme(self.config)
        object.__setattr__(self, "clock_window", VisibleThemeWindow())
        object.__setattr__(self, "repeat_window", VisibleThemeWindow())
        object.__setattr__(self, "settings_window", VisibleThemeWindow())
        object.__setattr__(self, "search_window", VisibleThemeWindow())
        object.__setattr__(self, "schedule_windows", {"today": VisibleThemeWindow()})
        object.__setattr__(self, "memo_windows", {"memo": memo_window})
        self.day_cells = []

    def refresh_theme_styles(self) -> None:
        return

    def render_calendar(self) -> None:
        return

    def apply_note_theme(self) -> None:
        for window in self.memo_windows.values():
            if window.isVisible():
                window.apply_note_theme()

    def update(self) -> None:
        return


class RepeatApp(FoxCalendarApp):
    def __init__(self) -> None:
        self.config = {"theme_mode": "light"}
        self.icon = QIcon()
        self.data = {"recurring_tasks": {}}

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_app_theme_refresh_updates_open_memo_windows() -> None:
    memo = VisibleThemeWindow()
    app = ThemeRefreshApp(memo)

    app.apply_theme()

    assert memo.note_theme_calls == 1


def test_repeat_task_form_keeps_draft_text_when_theme_changes(qtbot) -> None:
    repeat_window = RepeatWindow(RepeatApp())
    repeat_window.setGeometry(QRect(100, 100, 480, 460))
    form = AddRepeatTaskWindow(repeat_window)
    qtbot.addWidget(form)

    form.text_input.setText("draft task")
    form.notes_input.setText("draft notes")
    form.apply_theme()

    assert form.text_input.text() == "draft task"
    assert form.notes_input.text() == "draft notes"
