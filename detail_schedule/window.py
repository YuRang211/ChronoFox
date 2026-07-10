"""Detail-schedule 창의 코어: 초기화, 날짜/레인 계산, 네비게이션, 플랜 편집, 테마/언어.

위젯 조립(사이드바/탑바/시간뷰/사이드패널)은 layout.py의 DetailLayoutMixin이,
섹션별 화면(할 일/보관/월간)은 각각 tasks_section.py/archive_section.py/month_view.py의
믹스인이 담당하며, 이 파일의 DetailScheduleWindow가 그 믹스인들을 모두 합성한다.
"""

from __future__ import annotations

import calendar as calendar_module
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from app_constants import APP_NAME
from app_i18n import TrMixin
from app_styles import thin_scrollbar_style
from app_ui import geometry_string, parse_geometry
from app_widgets import RoundedWindow
from schedule_window import PlanWindow

from .archive_section import ArchiveSectionMixin
from .layout import DetailLayoutMixin
from .month_view import MonthViewMixin
from .palette import design_palette
from .tasks_section import TasksSectionMixin
from .widgets import SCROLLBAR_WIDTH, WEEKDAY_KEYS_SUNDAY_FIRST, MiniCalendar, _parse_dt

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp


class DetailScheduleWindow(
    TrMixin, DetailLayoutMixin, MonthViewMixin, TasksSectionMixin, ArchiveSectionMixin, RoundedWindow
):
    """디자인 시안을 그대로 옮긴 세부 일정(일/주/월) 관리 창입니다."""

    # 활성 기능을 먼저, 아직 준비 중인(비활성) 항목을 뒤에 둔다.
    NAV_ITEMS = [
        ("calendar", "detail.nav.calendar", "달력", "calendar"),
        ("tasks", "detail.nav.tasks", "해야 할 일", "tasks"),
        ("archive", "detail.nav.archive", "보관", "archive"),
        ("focus", "detail.nav.focus", "집중", "focus"),
        ("analytics", "detail.nav.analytics", "분석", "analytics"),
    ]
    DISABLED_NAV = {"focus", "analytics"}

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(design_palette(app.store), radius=16)
        self.app = app
        self.draw_window_border = True
        self.view_mode = app.store.get("detail_view_mode", "week")
        if self.view_mode not in {"day", "week", "month"}:
            self.view_mode = "week"
        self.section = "calendar"
        self.task_filter = "all"
        self.focused_day = date.today()
        self.days: list[date] = []
        self.day_index: dict[date, int] = {}
        self.lanes: dict[str, tuple[int, int]] = {}
        self.plan_window: PlanWindow | None = None
        self.mini_calendar: MiniCalendar | None = None
        self.setWindowTitle(self.window_title_text())
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.store.get("detail_geometry", "1040x720+120+50"), (1040, 720, 120, 50))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(960, 620)
        self.build_ui()

    # i18n -----------------------------------------------------------------
    def window_title_text(self) -> str:
        return self.tr("detail.window.title", "{app} 세부 일정", app=self.tr("app.name", APP_NAME))

    def timezone_label(self) -> str:
        offset = datetime.now().astimezone().utcoffset() or timedelta()
        hours = int(offset.total_seconds() // 3600)
        return f"GMT{hours:+d}"

    def month_title(self, month: date) -> str:
        month_name = self.tr(f"calendar.month.{month.month}", str(month.month))
        return self.tr("calendar.month_title", "{year}년 {month}").format(year=month.year, month=month_name)

    def weekday_initials(self) -> list[str]:
        return [self.tr(key, fb)[0] for key, fb in WEEKDAY_KEYS_SUNDAY_FIRST]

    # range math -----------------------------------------------------------
    def compute_days(self) -> None:
        if self.view_mode == "day":
            self.days = [self.focused_day]
        elif self.view_mode == "month":
            first = self.focused_day.replace(day=1)
            count = calendar_module.monthrange(first.year, first.month)[1]
            self.days = [first + timedelta(days=offset) for offset in range(count)]
        else:
            monday = self.focused_day - timedelta(days=self.focused_day.weekday())
            self.days = [monday + timedelta(days=offset) for offset in range(7)]
        self.day_index = {day: index for index, day in enumerate(self.days)}

    def range_label(self) -> str:
        if self.view_mode == "month":
            return self.month_title(self.focused_day)
        if not self.days:
            return ""
        if self.view_mode == "day":
            day = self.days[0]
            return self.tr("detail.range.day", "{year}.{month:02}.{day:02}", year=day.year, month=day.month, day=day.day)
        start, end = self.days[0], self.days[-1]
        if start.month == end.month:
            return self.tr(
                "detail.range.week_same_month",
                "{year}.{month:02}.{start_day:02} - {end_day:02}",
                year=start.year, month=start.month, start_day=start.day, end_day=end.day,
            )
        return self.tr(
            "detail.range.week",
            "{start_month:02}.{start_day:02} - {end_month:02}.{end_day:02}",
            start_month=start.month, start_day=start.day, end_month=end.month, end_day=end.day,
        )

    # plan helpers ---------------------------------------------------------
    def timed_plans_for_day(self, day: date) -> list[tuple[dict, datetime, datetime]]:
        rows: list[tuple[dict, datetime, datetime]] = []
        for plan in self.app.store.plans():
            if plan.get("kind") == "long":
                continue
            start_dt = _parse_dt(plan.get("start", ""))
            if start_dt is None or start_dt.date() != day:
                continue
            end_dt = _parse_dt(plan.get("end", "")) or (start_dt + timedelta(hours=1))
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(minutes=30)
            rows.append((plan, start_dt, end_dt))
        rows.sort(key=lambda row: row[1])
        return rows

    def all_day_plans_for_day(self, day: date) -> list[dict]:
        rows: list[dict] = []
        for plan in self.app.store.plans():
            if plan.get("kind") != "long":
                continue
            start_dt = _parse_dt(plan.get("start", ""))
            end_dt = _parse_dt(plan.get("end", "")) or start_dt
            if start_dt is None or end_dt is None:
                continue
            if start_dt.date() <= day <= end_dt.date():
                rows.append(plan)
        return rows

    def plans_intersecting_day(self, day: date) -> list[dict]:
        rows: list[tuple[dict, datetime]] = []
        for plan in self.app.store.plans():
            start_dt = _parse_dt(plan.get("start", ""))
            end_dt = _parse_dt(plan.get("end", "")) or start_dt
            if start_dt is None or end_dt is None:
                continue
            if start_dt.date() <= day <= end_dt.date():
                rows.append((plan, start_dt))
        rows.sort(key=lambda row: row[1])
        return [plan for plan, _ in rows]

    def compute_lanes(self) -> None:
        self.lanes = {}
        for day in self.days:
            events = self.timed_plans_for_day(day)
            cluster: list[tuple[dict, datetime, datetime]] = []
            cluster_end: datetime | None = None
            for plan, start_dt, end_dt in events:
                if cluster_end is not None and start_dt >= cluster_end:
                    self._assign_cluster_lanes(cluster)
                    cluster = []
                    cluster_end = None
                cluster.append((plan, start_dt, end_dt))
                cluster_end = end_dt if cluster_end is None else max(cluster_end, end_dt)
            self._assign_cluster_lanes(cluster)

    def _assign_cluster_lanes(self, cluster: list[tuple[dict, datetime, datetime]]) -> None:
        if not cluster:
            return
        lane_ends: list[datetime] = []
        assignments: dict[str, int] = {}
        for plan, start_dt, end_dt in cluster:
            placed = None
            for index, lane_end in enumerate(lane_ends):
                if start_dt >= lane_end:
                    lane_ends[index] = end_dt
                    placed = index
                    break
            if placed is None:
                placed = len(lane_ends)
                lane_ends.append(end_dt)
            assignments[str(plan.get("id", id(plan)))] = placed
        lane_count = len(lane_ends)
        for plan, _start_dt, _end_dt in cluster:
            key = str(plan.get("id", id(plan)))
            self.lanes[key] = (assignments[key], lane_count)

    def lane_for(self, plan_id) -> tuple[int, int]:
        return self.lanes.get(str(plan_id), (0, 1))

    def upcoming_plans(self, limit: int = 5) -> list[tuple[dict, datetime]]:
        now = datetime.now()
        rows: list[tuple[dict, datetime]] = []
        for plan in self.app.store.plans():
            start_dt = _parse_dt(plan.get("start", ""))
            if start_dt is None or start_dt < now:
                continue
            rows.append((plan, start_dt))
        rows.sort(key=lambda row: row[1])
        return rows[:limit]

    def view_event_count(self) -> int:
        return sum(len(self.timed_plans_for_day(day)) for day in self.days)

    # navigation -------------------------------------------------------
    def set_view_mode(self, mode: str) -> None:
        if mode not in {"day", "week", "month"} or mode == self.view_mode:
            return
        self.view_mode = mode
        self.app.store.set("detail_view_mode", mode)
        self.app.save()
        self.build_ui()

    def show_calendar_view(self) -> None:
        was_other = self.section != "calendar"
        self.section = "calendar"
        if was_other:
            if self.view_mode not in {"day", "week", "month"}:
                self.view_mode = "week"
            self.build_ui()
        else:
            self.set_view_mode("week")

    def go_previous(self) -> None:
        self.focused_day = self.shifted_focus(-1)
        self.refresh_after_focus_change()

    def go_next(self) -> None:
        self.focused_day = self.shifted_focus(1)
        self.refresh_after_focus_change()

    def shifted_focus(self, direction: int) -> date:
        if self.view_mode == "day":
            return self.focused_day + timedelta(days=direction)
        if self.view_mode == "month":
            month = self.focused_day.month - 1 + direction
            year = self.focused_day.year + month // 12
            return date(year, month % 12 + 1, 1)
        return self.focused_day + timedelta(days=7 * direction)

    def go_today(self) -> None:
        self.focused_day = date.today()
        self.refresh_after_focus_change()

    def refresh_after_focus_change(self) -> None:
        if self.view_mode == "month":
            self.build_ui()
        else:
            self.refresh_events()

    def open_day(self, day: date) -> None:
        self.focused_day = day
        self.view_mode = "day"
        self.app.store.set("detail_view_mode", "day")
        self.app.save()
        self.build_ui()

    # plan editing -----------------------------------------------------
    def add_plan(self) -> None:
        target = date.today() if date.today() in self.day_index else (self.days[0] if self.days else date.today())
        self.open_plan_editor(target, None)

    def edit_plan(self, plan: dict, day: date) -> None:
        self.open_plan_editor(day, plan)

    def open_plan_editor(self, day: date, plan: dict | None) -> None:
        if self.plan_window and self.plan_window.isVisible():
            self.plan_window.close()
        self.plan_window = PlanWindow(self.app, day, plan)
        self.plan_window.show()
        self.plan_window.raise_()
        self.plan_window.activateWindow()

    # theme / language ---------------------------------------------------
    def apply_theme(self) -> None:
        self.colors = design_palette(self.app.store)
        self.build_ui()
        self.update()

    def apply_language(self) -> None:
        self.setWindowTitle(self.window_title_text())
        self.build_ui()
        self.update()

    # styles -------------------------------------------------------------
    def view_button_style(self, active: bool) -> str:
        c = self.colors
        if active:
            return (
                f"QPushButton {{ background: transparent; color: {c['text']}; border: none; "
                f"border-bottom: 2px solid {c['accent']}; padding: 0 0 4px; font-size: 13px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background: transparent; color: {c['muted2']}; border: none; "
            "padding: 0 0 4px; font-size: 13px; font-weight: 500; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

    def scroll_style(self) -> str:
        c = self.colors
        return (
            f"QScrollArea {{ background: {c['bg']}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {c['bg']}; }}"
            + thin_scrollbar_style(
                c["border"], c["muted2"], track=c["bg"], width=SCROLLBAR_WIDTH, bar_margin="0", handle_margin="1px 2px"
            )
        )

    def closeEvent(self, event) -> None:
        self.app.store.set("detail_geometry", geometry_string(self))
        self.app.store.set("detail_view_mode", self.view_mode)
        self.app.save()
        self.app.detail_window = None
        super().closeEvent(event)
