from __future__ import annotations

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from detail_schedule_window import DetailScheduleWindow


class DetailApp:
    def __init__(self, language: str = "ko") -> None:
        today = date.today()
        start = datetime(today.year, today.month, today.day, 9, 0)
        end = start + timedelta(hours=1)
        self.config = {
            "theme_mode": "light",
            "language": language,
            "detail_view_mode": "week",
            "detail_geometry": "1000x680+140+60",
            "font_family": "",
        }
        self.data = {
            "plans": [
                {
                    "id": "p1",
                    "kind": "day",
                    "title": "Standup",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "color": "#7c6cf0",
                    "description": "",
                }
            ]
        }
        self.icon = QIcon()
        self.detail_window = None

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_detail_window_builds_and_renders_event(qtbot) -> None:
    window = DetailScheduleWindow(DetailApp())
    qtbot.addWidget(window)

    assert len(window.days) == 7
    assert any(block.plan.get("id") == "p1" for block in window.grid.blocks)


def test_detail_window_day_view_switch(qtbot) -> None:
    app = DetailApp()
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)

    window.set_view_mode("day")

    assert len(window.days) == 1
    assert app.config["detail_view_mode"] == "day"


def test_detail_window_english_labels(qtbot) -> None:
    window = DetailScheduleWindow(DetailApp("en"))
    qtbot.addWidget(window)

    assert window.windowTitle() == "ChronoFox Detailed Schedule"
    assert window.view_buttons["week"].text() == "Week"
    assert window.view_buttons["day"].text() == "Day"
    assert window.view_buttons["month"].text() == "Month"


def test_detail_window_follows_app_theme(qtbot) -> None:
    dark = DetailScheduleWindow(DetailApp())
    dark.app.config["theme_mode"] = "dark"
    dark.apply_theme()
    qtbot.addWidget(dark)
    assert dark.colors["bg"] == "#0a0a0c"

    light = DetailScheduleWindow(DetailApp())
    light.app.config["theme_mode"] = "light"
    light.apply_theme()
    qtbot.addWidget(light)
    assert light.colors["bg"] == "#ffffff"
    assert light.colors["accent"] == "#f0853b"


def test_detail_window_month_view_renders_in_tab(qtbot) -> None:
    import calendar as calendar_module

    app = DetailApp()
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)

    window.set_view_mode("month")

    today = date.today()
    expected_days = calendar_module.monthrange(today.year, today.month)[1]
    assert window.view_mode == "month"
    assert len(window.days) == expected_days
    # 월간 뷰에서는 시간 그리드가 없어야 한다.
    assert not hasattr(window, "grid") or window.grid is None or not window.grid.blocks
