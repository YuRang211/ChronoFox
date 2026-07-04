from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QAbstractSpinBox, QPushButton

from app_design import chronofox_panel_colors
from app_theme import resolve_theme
from clock.alarm_dialog import AlarmEditorDialog
from clock.alarm_row import AlarmRow
from clock.window import ClockWindow


class ClockApp:
    def __init__(self, theme_mode: str = "light", language: str = "ko") -> None:
        self.config = {
            "theme_mode": theme_mode,
            "language": language,
            "clock_geometry": "420x420",
            "alarms": [],
        }
        self.data = {"alarms": []}
        self.icon = QIcon()
        self.clock_window = None

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_chronofox_panel_colors_follow_dark_theme() -> None:
    colors = chronofox_panel_colors(resolve_theme({"theme_mode": "dark"}))

    assert colors["panel"] != "#ffffff"
    assert colors["text"] == "#f5f5f7"


def test_clock_uses_local_computer_time_source(qtbot) -> None:
    window = ClockWindow(ClockApp())
    qtbot.addWidget(window)

    assert not hasattr(window, "sync_timer")
    assert "네이버" not in window.time_source.text()
    assert window.time_source.text() == "컴퓨터 시간"


def test_alarm_editor_uses_dark_tokens_and_natural_spin_controls(qtbot) -> None:
    clock = ClockWindow(ClockApp(theme_mode="dark"))
    qtbot.addWidget(clock)

    dialog = AlarmEditorDialog(clock)
    qtbot.addWidget(dialog)

    assert dialog.colors["panel"] != "#ffffff"
    assert dialog.colors["text"] == "#f5f5f7"
    assert dialog.alarm_time.buttonSymbols() == QAbstractSpinBox.NoButtons
    assert dialog.alarm_date.buttonSymbols() == QAbstractSpinBox.NoButtons
    assert dialog.alarm_snooze_minutes.buttonSymbols() == QAbstractSpinBox.NoButtons


def test_alarm_row_uses_english_language(qtbot) -> None:
    clock = ClockWindow(ClockApp(language="en"))
    qtbot.addWidget(clock)
    alarm = {
        "id": "alarm-1",
        "time": "07:00",
        "label": "알람",
        "kind": "repeat",
        "repeat_days": [0, 1, 2, 3, 4, 5, 6],
        "snooze_minutes": 5,
        "notify_mode": "popup",
    }

    row = AlarmRow(clock, alarm)
    qtbot.addWidget(row)
    button_texts = {button.text() for button in row.findChildren(QPushButton)}

    assert row.label.text() == "Alarm"
    assert "Every day" in row.detail.text()
    assert "Snooze 5 min" in row.detail.text()
    assert "Popup" in row.detail.text()
    assert {"Edit", "Delete"}.issubset(button_texts)
    assert "매일" not in row.detail.text()


def test_alarm_row_detail_full_width_with_tooltip(qtbot) -> None:
    """UX15: 상세 줄이 버튼에 밀려 잘리지 않도록 2단 배치 + 전체 텍스트 tooltip."""
    from PySide6.QtCore import Qt

    clock = ClockWindow(ClockApp(language="en"))
    qtbot.addWidget(clock)
    alarm = {
        "id": "alarm-2",
        "time": "07:00",
        "kind": "repeat",
        "repeat_days": [0, 1, 2, 3, 4],
        "snooze_minutes": 5,
        "notify_mode": "popup",
    }

    row = AlarmRow(clock, alarm)
    qtbot.addWidget(row)

    assert row.detail.toolTip() == row.detail.text()
    # 카드 배경이 실제로 칠해지도록 styled-background가 켜져 있어야 한다.
    assert row.testAttribute(Qt.WA_StyledBackground)
