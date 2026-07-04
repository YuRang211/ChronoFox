from __future__ import annotations

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from clock.window import ClockWindow
from desktop_note_calendar import FoxCalendarApp
from todo_window import RepeatWindow


class TodoApp:
    def __init__(self) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "repeat_geometry": "480x460"}
        self.data = {"recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []}}
        self.icon = QIcon()
        self.repeat_window = None

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_elapsed_text_avoids_zero_units(qtbot) -> None:
    """UX16: '0주 지남' 대신 '오늘' 또는 일 단위로 보여준다."""
    window = RepeatWindow(TodoApp())
    qtbot.addWidget(window)
    today = date.today()

    created_today = {"created": today.isoformat()}
    assert window.elapsed_text("weekly", created_today) == "오늘"
    assert window.elapsed_text("daily", created_today) == "오늘"

    three_days = {"created": (today - timedelta(days=3)).isoformat()}
    assert window.elapsed_text("weekly", three_days) == "3일 지남"


def test_calendar_bars_show_start_time_and_weekly_title() -> None:
    """UX16: 시간 일정 칩에 시작 시각 표시 + 여러 주 바는 주 시작 셀에 제목 반복."""
    app = FoxCalendarApp.__new__(FoxCalendarApp)
    monday = date(2026, 7, 6)  # 월요일
    next_sunday = monday + timedelta(days=6)  # 다음 주 시작(일요일)
    app.data = {
        "plans": [
            {
                "id": "timed",
                "kind": "day",
                "title": "회의",
                "start": f"{monday.isoformat()}T09:30:00",
                "end": f"{monday.isoformat()}T10:30:00",
            },
            {
                "id": "long",
                "kind": "long",
                "title": "스프린트",
                "start": f"{monday.isoformat()}T00:00:00",
                "end": f"{(monday + timedelta(days=8)).isoformat()}T23:59:00",
            },
        ]
    }

    days = [monday, next_sunday]
    bars = app.plan_bars_for_days(days)

    timed_bar = next(bar for bar in bars[monday] if "회의" in bar["title"])
    assert timed_bar["title"] == "09:30 회의"

    long_bar_week2 = next(bar for bar in bars[next_sunday] if "스프린트" in bar["title"])
    assert long_bar_week2["from_prev"] is True
    assert long_bar_week2["show_title"] is True


class ClockApp:
    def __init__(self, alarms: list[dict]) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "clock_geometry": "420x420"}
        self.data = {"alarms": alarms}
        self.icon = QIcon()
        self.clock_window = None

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_next_alarm_label_shows_soonest_enabled(qtbot) -> None:
    """UX16: 시간 탭에 다음 알람 요약 표시."""
    soon = (datetime.now() + timedelta(hours=1)).strftime("%H:%M")
    alarms = [
        {"id": "on", "time": soon, "enabled": True, "kind": "repeat", "repeat_days": [0, 1, 2, 3, 4, 5, 6]},
        {"id": "off", "time": "00:01", "enabled": False, "kind": "repeat", "repeat_days": [0, 1, 2, 3, 4, 5, 6]},
    ]
    window = ClockWindow(ClockApp(alarms))
    qtbot.addWidget(window)

    best = window.next_alarm_occurrence()
    assert best is not None
    assert f"{best:%H:%M}" == soon
    assert soon in window.next_alarm_label.text()
    assert "다음 알람" in window.next_alarm_label.text()


def test_next_alarm_empty_when_all_disabled(qtbot) -> None:
    alarms = [{"id": "off", "time": "07:00", "enabled": False, "kind": "repeat", "repeat_days": [0]}]
    window = ClockWindow(ClockApp(alarms))
    qtbot.addWidget(window)

    assert window.next_alarm_occurrence() is None
    assert window.next_alarm_label.text() == ""
