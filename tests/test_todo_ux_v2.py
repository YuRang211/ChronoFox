"""todo-ux-v2 Phase1(D2~D5) 검증: 순수 헬퍼(todo_logic) 단위 테스트 + RepeatWindow/관리 탭 통합 테스트."""

from __future__ import annotations

from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from detail_schedule_window import DetailScheduleWindow
from todo_logic import classify_and_sort, compute_streak, days_until, period_key, previous_period_key
from todo_window import RepeatWindow

# ---------------------------------------------------------------------------
# 순수 헬퍼: period_key / previous_period_key
# ---------------------------------------------------------------------------


def test_period_key_formats_per_period() -> None:
    day = date(2026, 7, 12)  # 일요일, 2026-W28
    assert period_key("daily", day) == "2026-07-12"
    assert period_key("weekly", day) == "2026-W28"
    assert period_key("monthly", day) == "2026-07"
    assert period_key("yearly", day) == "2026"


def test_previous_period_key_daily() -> None:
    assert previous_period_key("daily", "2026-07-12") == "2026-07-11"
    # 월 경계
    assert previous_period_key("daily", "2026-07-01") == "2026-06-30"


def test_previous_period_key_weekly() -> None:
    # 2026-W28의 이전 주는 W27이어야 한다.
    assert previous_period_key("weekly", "2026-W28") == "2026-W27"


def test_previous_period_key_monthly_crosses_year_boundary() -> None:
    assert previous_period_key("monthly", "2026-07") == "2026-06"
    assert previous_period_key("monthly", "2026-01") == "2025-12"


def test_previous_period_key_yearly() -> None:
    assert previous_period_key("yearly", "2026") == "2025"


def test_previous_period_key_invalid_input_returns_empty() -> None:
    assert previous_period_key("daily", "not-a-date") == ""
    assert previous_period_key("weekly", "garbage") == ""
    assert previous_period_key("monthly", "garbage") == ""
    assert previous_period_key("yearly", "garbage") == ""


# ---------------------------------------------------------------------------
# 순수 헬퍼: compute_streak (D3 — 주기 경계 포함)
# ---------------------------------------------------------------------------


def test_compute_streak_continuing_when_current_period_done() -> None:
    """오늘까지 3일 연속 완료면 스트릭은 3이다."""
    counted = ["2026-07-10", "2026-07-11", "2026-07-12"]
    assert compute_streak("daily", counted, "2026-07-12") == 3


def test_compute_streak_falls_back_to_previous_period_when_current_incomplete() -> None:
    """오늘(현재 주기)은 아직 미완료지만 어제까지 연속 완료했다면, 어제부터 역방향으로 센다."""
    counted = ["2026-07-10", "2026-07-11"]  # 07-12(오늘)는 미완료
    assert compute_streak("daily", counted, "2026-07-12") == 2


def test_compute_streak_broken_by_gap_returns_only_trailing_run() -> None:
    """중간에 빠진 날이 있으면 거기서 끊기고, 최근 연속 구간만 센다."""
    counted = ["2026-07-08", "2026-07-10", "2026-07-11", "2026-07-12"]  # 07-09 누락
    assert compute_streak("daily", counted, "2026-07-12") == 3


def test_compute_streak_zero_when_neither_current_nor_previous_done() -> None:
    counted = ["2026-07-01"]
    assert compute_streak("daily", counted, "2026-07-12") == 0


def test_compute_streak_weekly_continuing_across_year_boundary() -> None:
    # 2026-W01의 이전 주는 2025-W52다 — 연도 경계를 넘어가도 스트릭이 이어져야 한다.
    assert previous_period_key("weekly", "2026-W01") == "2025-W52"
    counted = ["2025-W52", "2026-W01"]
    assert compute_streak("weekly", counted, "2026-W01") == 2


def test_compute_streak_monthly_and_yearly() -> None:
    assert compute_streak("monthly", ["2026-05", "2026-06", "2026-07"], "2026-07") == 3
    assert compute_streak("yearly", ["2024", "2025", "2026"], "2026") == 3


# ---------------------------------------------------------------------------
# 순수 헬퍼: days_until (마감 D-n)
# ---------------------------------------------------------------------------


def test_days_until_future_and_past_and_today() -> None:
    today = date(2026, 7, 12)
    assert days_until("2026-07-15", today) == 3
    assert days_until("2026-07-12", today) == 0
    assert days_until("2026-07-09", today) == -3


def test_days_until_empty_or_invalid_returns_none() -> None:
    today = date(2026, 7, 12)
    assert days_until("", today) is None
    assert days_until("not-a-date", today) is None


# ---------------------------------------------------------------------------
# 순수 헬퍼: classify_and_sort (D4 — 그룹·정렬)
# ---------------------------------------------------------------------------


def _is_done_by_flag(_period: str, task: dict) -> bool:
    return bool(task.get("_done"))


def test_classify_and_sort_splits_pending_and_done() -> None:
    rows = [
        ("daily", {"id": "a", "_done": False, "created": "2026-07-01"}),
        ("daily", {"id": "b", "_done": True, "created": "2026-07-02"}),
        ("weekly", {"id": "c", "_done": False, "created": "2026-07-03"}),
    ]
    pending, done = classify_and_sort(rows, _is_done_by_flag)
    assert [task["id"] for _p, task in pending] == ["a", "c"]
    assert [task["id"] for _p, task in done] == ["b"]


def test_classify_and_sort_orders_important_first_then_created() -> None:
    rows = [
        ("daily", {"id": "old", "_done": False, "important": False, "created": "2026-07-01"}),
        ("daily", {"id": "new-important", "_done": False, "important": True, "created": "2026-07-05"}),
        ("daily", {"id": "new", "_done": False, "important": False, "created": "2026-07-03"}),
    ]
    pending, _done = classify_and_sort(rows, _is_done_by_flag)
    assert [task["id"] for _p, task in pending] == ["new-important", "old", "new"]


def test_classify_and_sort_uses_order_field_when_present_else_stable() -> None:
    rows = [
        ("daily", {"id": "third", "_done": False, "order": 2, "created": "2026-07-01"}),
        ("daily", {"id": "first", "_done": False, "order": 0, "created": "2026-07-01"}),
        ("daily", {"id": "no-order-a", "_done": False, "created": "2026-07-01"}),
        ("daily", {"id": "no-order-b", "_done": False, "created": "2026-07-01"}),
    ]
    pending, _done = classify_and_sort(rows, _is_done_by_flag)
    # order가 있는 항목이 먼저(0, 2), order가 없는 항목들은 뒤에서 원래 순서(stable)를 유지한다.
    assert [task["id"] for _p, task in pending] == ["first", "third", "no-order-a", "no-order-b"]


# ---------------------------------------------------------------------------
# RepeatWindow 통합: D2 인라인 빠른 추가
# ---------------------------------------------------------------------------


def test_quick_add_appends_daily_task_clears_input_and_refocuses(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)
    window.show()
    QApplication.processEvents()

    window.quick_add_input.setText("우유 사기")
    window.quick_add_task()

    daily_tasks = app.data["recurring_tasks"]["daily"]
    assert len(daily_tasks) == 1
    assert daily_tasks[0]["text"] == "우유 사기"
    assert window.quick_add_input.text() == ""
    QApplication.processEvents()
    assert window.quick_add_input.hasFocus()


def test_quick_add_ignores_blank_input(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    window.quick_add_input.setText("   ")
    window.quick_add_task()

    assert app.data["recurring_tasks"]["daily"] == []


# ---------------------------------------------------------------------------
# RepeatWindow 통합: D4 그룹·정렬·접힘(기본 접힘, 세션 단위)
# ---------------------------------------------------------------------------


def test_done_section_collapsed_by_default_and_toggle_expands(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    current_key = window.current_key("daily")
    app.data["recurring_tasks"]["daily"].extend(
        [
            {"id": "pending-1", "text": "미완료", "done": ""},
            {"id": "done-1", "text": "완료됨", "done": current_key, "counted_keys": [current_key]},
        ]
    )
    window.refresh_all()

    assert window.done_collapsed is True
    # 미완료 헤더 + 미완료 행 + 완료됨 헤더(접힘, 행 없음) = 3
    assert window.list_widget.count() == 3

    window.toggle_done_section()

    assert window.done_collapsed is False
    # 미완료 헤더 + 미완료 행 + 완료됨 헤더 + 완료됨 행 = 4
    assert window.list_widget.count() == 4


def test_completed_filter_shows_flat_list_without_headers(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    current_key = window.current_key("daily")
    app.data["recurring_tasks"]["daily"].append(
        {"id": "done-1", "text": "완료됨", "done": current_key, "counted_keys": [current_key]}
    )
    window.set_filter("completed")

    # 헤더 없이 완료된 작업 행 1개만 보인다.
    assert window.list_widget.count() == 1


# ---------------------------------------------------------------------------
# RepeatWindow 통합: D3 메타라인 텍스트
# ---------------------------------------------------------------------------


def test_task_meta_text_not_done_is_danger(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    task = window.normalize_task({"id": "t1", "text": "설거지"})
    text, danger = window.task_meta_text("daily", task)

    assert danger is True
    assert "아직 안 함" in text
    assert window.period_label("daily") in text
    assert "회 완료" not in text  # D3: N회 완료는 행에서 제거


def test_task_meta_text_done_shows_period_status_and_no_danger(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    current = window.current_key("daily")
    task = window.normalize_task({"id": "t1", "text": "물주기", "done": current, "counted_keys": [current]})
    text, danger = window.task_meta_text("daily", task)

    assert danger is False
    assert "오늘 완료" in text


def test_task_meta_text_shows_streak_only_when_two_or_more(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    current = window.current_key("daily")
    yesterday = previous_period_key("daily", current)

    solo_task = window.normalize_task({"id": "solo", "text": "혼자", "done": current, "counted_keys": [current]})
    text_solo, _danger = window.task_meta_text("daily", solo_task)
    assert "연속" not in text_solo

    streak_task = window.normalize_task(
        {"id": "streak", "text": "연속", "done": current, "counted_keys": [yesterday, current]}
    )
    text_streak, _danger = window.task_meta_text("daily", streak_task)
    assert "연속 2일" in text_streak


def test_task_meta_text_due_shows_dday_and_overdue_is_danger(qtbot, fake_app) -> None:
    app = fake_app(repeat_geometry="480x460")
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    from datetime import timedelta

    current = window.current_key("daily")
    future_due = (date.today() + timedelta(days=3)).isoformat()
    past_due = (date.today() - timedelta(days=2)).isoformat()

    future_task = window.normalize_task(
        {"id": "future", "text": "미래 마감", "done": current, "counted_keys": [current], "due": future_due}
    )
    text_future, danger_future = window.task_meta_text("daily", future_task)
    assert "D-3" in text_future
    assert danger_future is False

    overdue_task = window.normalize_task(
        {"id": "overdue", "text": "지난 마감", "done": current, "counted_keys": [current], "due": past_due}
    )
    text_overdue, danger_overdue = window.task_meta_text("daily", overdue_task)
    assert "2일 지남" in text_overdue
    assert danger_overdue is True


# ---------------------------------------------------------------------------
# 관리 탭(detail_schedule tasks_section) 통합 — 무거운 실창 생성이라 slow로 표시
# ---------------------------------------------------------------------------


class _DetailQuickAddApp:
    def __init__(self) -> None:
        from PySide6.QtGui import QIcon

        from app_store import AppStore

        self.config = {
            "theme_mode": "light",
            "language": "ko",
            "detail_view_mode": "week",
            "detail_geometry": "1000x680+140+60",
            "font_family": "",
        }
        self.data = {"recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []}}
        self.store = AppStore(self.config, self.data, lambda _c: None, lambda _d: None)
        self.icon = QIcon()
        self.detail_window = None
        self.repeat_window = None
        self.save_calls = 0

    def dialog_colors(self) -> dict[str, str]:
        from app_theme import resolve_theme

        return resolve_theme(self.config)

    def save(self) -> None:
        self.save_calls += 1


@pytest.mark.slow  # F4 D3: DetailScheduleWindow 대형 실창 빌드 — fast lane 제외
def test_detail_tasks_quick_add_appends_task_and_clears_input(qtbot) -> None:
    app = _DetailQuickAddApp()
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)
    window.show_tasks_view()

    window.tasks_quick_add_input.setText("빨래 개기")
    window.quick_add_task_item()

    assert len(app.data["recurring_tasks"]["daily"]) == 1
    assert app.data["recurring_tasks"]["daily"][0]["text"] == "빨래 개기"
    assert window.tasks_quick_add_input.text() == ""


@pytest.mark.slow  # F4 D3: DetailScheduleWindow 대형 실창 빌드 — fast lane 제외
def test_detail_tasks_done_section_collapsed_by_default(qtbot) -> None:
    app = _DetailQuickAddApp()
    window = DetailScheduleWindow(app)
    qtbot.addWidget(window)
    window.show_tasks_view()

    current_key = window.task_controller().current_key("daily")
    app.data["recurring_tasks"]["daily"].extend(
        [
            {"id": "pending-1", "text": "미완료"},
            {"id": "done-1", "text": "완료됨", "done": current_key, "counted_keys": [current_key]},
        ]
    )
    window.refresh_tasks_view()

    assert window.tasks_done_collapsed is True
    # 미완료 헤더 + 미완료 행 + 완료됨 헤더(접힘) + stretch = 4
    assert window.tasks_box.count() == 4

    window.toggle_tasks_done_section()

    assert window.tasks_done_collapsed is False
    assert window.tasks_box.count() == 5
