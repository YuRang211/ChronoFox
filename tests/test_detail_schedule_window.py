from __future__ import annotations

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from detail_schedule_window import DetailScheduleWindow


class FakeMemoStore:
    def __init__(self, memos: dict[str, str]) -> None:
        self._memos = memos

    def memo_ids(self) -> list[str]:
        return sorted(self._memos)

    def load(self, memo_id: str) -> str:
        return self._memos.get(memo_id, "")


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
            "memo_titles": {},
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
        self.repeat_window = None
        self.memo_store = FakeMemoStore({})
        self.opened_memos: list[str] = []

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return

    def open_memo(self, memo_id: str) -> None:
        self.opened_memos.append(memo_id)

    def create_memo(self) -> None:
        self.opened_memos.append("new")


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

    assert window.windowTitle() == "ChronoFox Management"
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
    # UX13: 앱 전체 accent를 메인 달력 파랑으로 통일
    assert light.colors["accent"] == "#2563eb"


def test_detail_window_tasks_section_lists_tasks(qtbot) -> None:
    app = DetailApp()
    app.data["recurring_tasks"] = {
        "daily": [{"id": "t1", "text": "Drink water", "list_name": "작업"}]
    }
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)

    window.show_tasks_view()

    assert window.section == "tasks"
    assert hasattr(window, "tasks_box")
    # 할 일 행 한 개가 임베드되어 렌더링된다 (행 + stretch).
    assert window.tasks_box.count() >= 2


def test_detail_window_tasks_filter_completed_empty(qtbot) -> None:
    app = DetailApp()
    app.data["recurring_tasks"] = {
        "daily": [{"id": "t1", "text": "Drink water", "list_name": "작업"}]
    }
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)

    window.show_tasks_view()
    window.set_task_filter("completed")

    # 완료된 할 일이 없으므로 빈 안내만 표시된다.
    assert window.task_filter == "completed"
    assert window.tasks_box.count() == 2  # 빈 안내 라벨 + stretch


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


def test_detail_window_archive_lists_saved_memos(qtbot) -> None:
    app = DetailApp()
    app.memo_store = FakeMemoStore(
        {
            "20260101090000000000": "첫 메모\n본문",
            "20260102090000000000": "둘째 메모",
        }
    )
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)

    window.show_archive_view()

    assert window.section == "archive"
    assert hasattr(window, "archive_box")
    # 메모 2개 행 + stretch
    assert window.archive_box.count() == 3
    # 최신순(메모 id 내림차순)
    assert window.saved_memos()[0][0] == "20260102090000000000"


def test_detail_window_archive_empty(qtbot) -> None:
    window = DetailScheduleWindow(DetailApp())
    qtbot.addWidget(window)

    window.show_archive_view()

    # 저장된 메모가 없으므로 빈 안내 + stretch
    assert window.section == "archive"
    assert window.archive_box.count() == 2


def test_detail_window_focus_analytics_disabled(qtbot) -> None:
    from PySide6.QtWidgets import QPushButton

    window = DetailScheduleWindow(DetailApp("en"))
    qtbot.addWidget(window)

    assert "focus" in window.DISABLED_NAV
    assert "analytics" in window.DISABLED_NAV
    assert len(window.DISABLED_NAV) == 2
    button_texts = {button.text().strip() for button in window.findChildren(QPushButton)}
    # 건의하기 버튼이 Upgrade Pro를 대체했다.
    assert "Suggest" in button_texts
    assert "Upgrade Pro" not in button_texts
