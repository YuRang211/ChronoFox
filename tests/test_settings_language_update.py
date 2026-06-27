from __future__ import annotations

import os
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QPushButton

from app_theme import resolve_theme
from desktop_note_calendar import FoxCalendarApp
from settings_window import SettingsWindow
from todo_window import AddRepeatTaskWindow, RepeatWindow


class SettingsApp:
    def __init__(self) -> None:
        self.config = {
            "theme_mode": "light",
            "language": "ko",
            "settings_geometry": "620x520",
            "calendar_opacity": 56,
            "holiday_enabled": True,
            "font_family": "",
        }
        self.icon = QIcon()
        self.language_calls = 0

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return

    def startup_enabled(self) -> bool:
        return False

    def set_startup(self, enabled: bool, show_message: bool = True) -> None:
        return

    def set_calendar_opacity(self, value: int) -> None:
        self.config["calendar_opacity"] = value

    def apply_theme(self) -> None:
        return

    def apply_language(self, source=None) -> None:
        self.language_calls += 1


def test_settings_info_page_has_update_check_button(qtbot) -> None:
    window = SettingsWindow(SettingsApp())
    qtbot.addWidget(window)
    window.switch_settings_page(3)

    buttons = window.findChildren(QPushButton)
    assert any(button.text() == "업데이트 확인" for button in buttons)


def test_setting_language_change_notifies_app(qtbot) -> None:
    app = SettingsApp()
    window = SettingsWindow(app)
    qtbot.addWidget(window)

    window.set_language("en")

    assert app.config["language"] == "en"
    assert app.language_calls == 1


def test_calendar_month_title_uses_selected_language() -> None:
    app = FoxCalendarApp.__new__(FoxCalendarApp)

    app.config = {"language": "en"}
    assert app.month_title_text(date(2025, 6, 1)) == "June 2025"

    app.config = {"language": "ko"}
    assert app.month_title_text(date(2025, 6, 1)) == "2025년 6월"


class TodoLanguageApp:
    def __init__(self) -> None:
        self.config = {
            "theme_mode": "light",
            "language": "en",
            "repeat_geometry": "480x460",
        }
        self.data = {
            "recurring_tasks": {
                "daily": [
                    {
                        "id": "task-1",
                        "text": "Write notes",
                        "created": date.today().isoformat(),
                        "done_count": 2,
                        "list_name": "작업",
                    }
                ],
                "weekly": [],
                "monthly": [],
                "yearly": [],
            }
        }
        self.icon = QIcon()
        self.repeat_window = None
        self.save_calls = 0

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        self.save_calls += 1


def test_todo_window_uses_english_language(qtbot) -> None:
    window = RepeatWindow(TodoLanguageApp())
    qtbot.addWidget(window)

    button_texts = {button.text() for button in window.findChildren(QPushButton)}

    assert window.windowTitle() == "ChronoFox To Do"
    assert window.header_title.text() == "To Do"
    assert window.search_input.placeholderText() == "Search"
    assert window.list_label.text() == "List"
    assert window.list_combo.itemText(0) == "All Lists"
    assert {"All", "My Day", "Today", "Important", "Completed"}.issubset(button_texts)
    assert {"Today", "Edit"}.issubset(button_texts)
    assert "해야 할 일" not in window.header_title.text()


def test_todo_editor_uses_english_language(qtbot) -> None:
    repeat_window = RepeatWindow(TodoLanguageApp())
    editor = AddRepeatTaskWindow(repeat_window)
    qtbot.addWidget(repeat_window)
    qtbot.addWidget(editor)

    assert editor.windowTitle() == "ChronoFox Add To Do"
    assert editor.header_title.text() == "Add To Do"
    assert editor.text_input.placeholderText() == "To do"
    assert editor.list_input.placeholderText() == "List"
    assert editor.important_check.text() == "Important"
    assert editor.my_day_check.text() == "Add to My Day"
    assert editor.due_check.text() == "Due Date"
    assert editor.notes_input.placeholderText() == "Memo"
