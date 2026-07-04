from __future__ import annotations

import os
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from schedule_window import PlanWindow


class PlanApp:
    def __init__(self) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "font_family": ""}
        self.icon = QIcon()
        self.added: list[dict] = []

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def add_plan(self, plan: dict) -> None:
        self.added.append(plan)

    def update_plan(self, plan: dict) -> None:
        self.added.append(plan)


def test_timed_event_shows_and_uses_selected_date(qtbot) -> None:
    """UX 리뷰 수정: 시간 일정도 날짜가 보이고 다른 날짜로 저장할 수 있어야 한다."""
    app = PlanApp()
    today = date.today()
    window = PlanWindow(app, today)
    qtbot.addWidget(window)

    # 시간 모드에서도 시작 날짜 선택이 보인다 (종료 날짜는 종일 전용).
    assert not window.all_day_switch.checked
    assert window.date_row.isVisibleTo(window)
    assert not window.end_date.isVisibleTo(window)

    target = today + timedelta(days=3)
    window.start_date.setDate(QDate(target.year, target.month, target.day))
    window.title_input.setText("Moved event")
    window.save_plan()

    assert len(app.added) == 1
    assert app.added[0]["start"][:10] == target.isoformat()
    assert app.added[0]["end"][:10] == target.isoformat()


def test_plan_heading_includes_date(qtbot) -> None:
    app = PlanApp()
    today = date.today()
    window = PlanWindow(app, today)
    qtbot.addWidget(window)

    assert window.heading_day() == today
