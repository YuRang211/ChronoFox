from __future__ import annotations

from app_store import AppStore
from desktop_note_calendar import FoxCalendarApp


def test_recurring_tasks_for_today_accepts_localized_period_tuples() -> None:
    app = FoxCalendarApp.__new__(FoxCalendarApp)
    app.store = AppStore(
        {},
        {
            "recurring_tasks": {
                "daily": [{"id": "daily-1", "text": "Daily task"}],
                "weekly": [{"id": "weekly-1", "text": "Weekly task"}],
                "monthly": [],
                "yearly": [],
            }
        },
        lambda _c: None,
        lambda _d: None,
    )

    rows = app.recurring_tasks_for_today()

    assert [(period, task["id"]) for period, task in rows] == [
        ("daily", "daily-1"),
        ("weekly", "weekly-1"),
    ]


def test_period_label_accepts_localized_period_tuples() -> None:
    app = FoxCalendarApp.__new__(FoxCalendarApp)
    app.store = AppStore({"language": "ko"}, {}, lambda _c: None, lambda _d: None)

    assert app.period_label("daily") == "매일"
    assert app.period_label("unknown") == "unknown"
