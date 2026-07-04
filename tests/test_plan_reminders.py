from __future__ import annotations

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from desktop_note_calendar import FoxCalendarApp
from schedule_window import PlanWindow


def make_reminder_app(plans: list[dict]) -> FoxCalendarApp:
    app = FoxCalendarApp.__new__(FoxCalendarApp)
    app.config = {"language": "ko"}
    app.data = {"plans": plans}
    app.saved = 0
    app.fired: list[tuple[str, int]] = []
    app.save = lambda: setattr(app, "saved", app.saved + 1)  # type: ignore[method-assign]
    app.notify_plan_reminder = lambda plan, start_dt, minutes: app.fired.append(  # type: ignore[method-assign]
        (str(plan.get("id")), minutes)
    )
    return app


def timed_plan(plan_id: str, start: datetime, reminder: int) -> dict:
    return {
        "id": plan_id,
        "kind": "day",
        "title": f"Plan {plan_id}",
        "start": start.isoformat(timespec="seconds"),
        "end": (start + timedelta(hours=1)).isoformat(timespec="seconds"),
        "reminder_minutes": reminder,
        "reminder_fired": "",
    }


def test_reminder_fires_inside_window_and_only_once() -> None:
    now = datetime.now()
    plan = timed_plan("p1", now + timedelta(minutes=8), reminder=10)
    app = make_reminder_app([plan])

    app.check_plan_reminders()
    assert app.fired == [("p1", 10)]
    assert plan["reminder_fired"] == plan["start"]
    assert app.saved == 1

    # 같은 시작 시각으로는 다시 울리지 않는다.
    app.check_plan_reminders()
    assert app.fired == [("p1", 10)]


def test_reminder_skips_past_none_and_all_day() -> None:
    now = datetime.now()
    plans = [
        timed_plan("future", now + timedelta(hours=2), reminder=10),  # 아직 발화 창 전
        timed_plan("stale", now - timedelta(hours=1), reminder=10),  # 5분 창을 지난 과거
        timed_plan("none", now + timedelta(minutes=5), reminder=-1),  # 알림 없음
        {**timed_plan("allday", now + timedelta(minutes=5), reminder=10), "kind": "long"},
    ]
    app = make_reminder_app(plans)

    app.check_plan_reminders()

    assert app.fired == []
    assert app.saved == 0


def test_reminder_rearms_when_start_changes() -> None:
    now = datetime.now()
    plan = timed_plan("p1", now + timedelta(minutes=8), reminder=10)
    plan["reminder_fired"] = "old-start"
    app = make_reminder_app([plan])

    app.check_plan_reminders()

    assert app.fired == [("p1", 10)]


class PlanApp:
    def __init__(self) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "font_family": ""}
        self.icon = QIcon()
        self.added: list[dict] = []

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def add_plan(self, plan: dict) -> None:
        self.added.append(plan)


def test_plan_window_saves_reminder_choice(qtbot) -> None:
    app = PlanApp()
    window = PlanWindow(app, date.today())
    qtbot.addWidget(window)

    assert window.reminder_row.isVisibleTo(window)
    window.reminder_combo.setCurrentIndex(window.reminder_combo.findData(10))
    window.title_input.setText("With reminder")
    window.save_plan()

    assert app.added[0]["reminder_minutes"] == 10
    assert app.added[0]["reminder_fired"] == ""
