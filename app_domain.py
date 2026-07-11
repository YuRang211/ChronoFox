"""S4(M5): FoxCalendarApp의 plan/schedule/recurring 도메인 책임 분리 (D8).

PlanService는 ``app``(FoxCalendarApp)을 받아 store 기반 plan/schedule/recurring-task
도메인 로직을 담당한다. app은 이 클래스의 메서드를 얇게 위임만 하며, 호출부
(schedule_window.py 등)는 계속 ``app.add_plan(...)`` 같은 기존 메서드를 무수정으로
호출한다(D8).
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from app_i18n import translate
from app_theme import PLAN_LANE_COLORS
from todo_window import RepeatWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp


class PlanService:
    """일정(plan)·하루메모(schedule)·반복 할 일 도메인 로직을 담당합니다."""

    def __init__(self, app: FoxCalendarApp) -> None:
        self.app = app

    # schedule (하루 메모) -------------------------------------------------
    def get_schedule(self, day: date) -> str:
        """특정 날짜의 일정 리스트를 반환합니다."""
        return self.app.store.schedules().get(day.isoformat(), "")

    def set_schedule(self, day: date, text: str) -> None:
        """특정 날짜의 일정 리스트를 저장합니다."""
        app = self.app
        schedules = app.store.schedules()
        clean = text.rstrip()
        current = schedules.get(day.isoformat(), "")
        if current == clean:
            return
        if clean:
            schedules[day.isoformat()] = clean
        else:
            schedules.pop(day.isoformat(), None)
        app.save()
        # S4(M6/D9): 수동 render_calendar() 호출 대신 store 구독(app이 "schedules"를
        # 구독해 render_calendar를 스스로 호출)으로 대체한다.
        app.store.notify("schedules")

    # plan 조회 -----------------------------------------------------------
    def plans_for_day(self, day: date) -> list[dict]:
        """특정 날짜에 걸쳐 있는 계획 목록을 반환합니다."""
        return [
            plan
            for plan in self.sorted_plans()
            if self.plan_start_date(plan) <= day <= self.plan_end_date(plan)
        ]

    def sorted_plans(self) -> list[dict]:
        """계획 목록을 시작일 기준으로 정렬해 반환합니다."""
        return sorted(
            self.app.store.plans(),
            key=lambda plan: (self.plan_start_date(plan), self.plan_end_date(plan), plan.get("title", "")),
        )

    def plan_start_date(self, plan: dict) -> date:
        """계획의 시작 날짜를 반환합니다."""
        try:
            return date.fromisoformat(str(plan.get("start", ""))[:10])
        except ValueError:
            return date.today()

    def plan_end_date(self, plan: dict) -> date:
        """계획의 종료 날짜를 반환합니다."""
        try:
            end_day = date.fromisoformat(str(plan.get("end", plan.get("start", "")))[:10])
        except ValueError:
            end_day = self.plan_start_date(plan)
        return max(self.plan_start_date(plan), end_day)

    def plan_bars_for_day(self, day: date) -> list[dict]:
        """특정 날짜에 그릴 계획 막대(bar) 정보를 계산합니다."""
        return self.plan_bars_for_days([day]).get(day, [])

    def plan_bars_for_days(self, days: list[date]) -> dict[date, list[dict]]:
        """여러 날짜에 걸쳐 그릴 계획 막대(bar) 정보를 계산합니다."""
        colors = PLAN_LANE_COLORS
        target_days = set(days)
        lane_ends: list[date] = []
        lanes: dict[str, int] = {}
        plan_rows: list[tuple[int, dict, date, date, str]] = []
        for index, plan in enumerate(self.sorted_plans()):
            start_day = self.plan_start_date(plan)
            end_day = self.plan_end_date(plan)
            plan_id = str(plan.get("id", id(plan)))
            lane = next((idx for idx, lane_end in enumerate(lane_ends) if start_day > lane_end), None)
            if lane is None:
                lane = len(lane_ends)
                lane_ends.append(end_day)
            else:
                lane_ends[lane] = end_day
            lanes[plan_id] = lane
            plan_rows.append((index, plan, start_day, end_day, plan_id))

        bars_by_day: dict[date, list[dict]] = {day: [] for day in target_days}
        for index, plan, start_day, end_day, plan_id in plan_rows:
            title = plan.get("title", "")
            # 시간 일정은 칩에 시작 시각을 함께 보여준다 (예: "09:00 회의").
            if plan.get("kind") != "long":
                start_hhmm = str(plan.get("start", ""))[11:16]
                if start_hhmm:
                    title = f"{start_hhmm} {title}".strip()
            for day in target_days:
                if not (start_day <= day <= end_day):
                    continue
                bars_by_day[day].append(
                    {
                        "title": title,
                        "color": plan.get("color") or colors[index % len(colors)],
                        "from_prev": day > start_day,
                        "to_next": day < end_day,
                        # 여러 주에 걸친 바는 각 주의 첫 칸(일요일)에도 제목을 반복해 알아볼 수 있게 한다.
                        "show_title": day == start_day or (day > start_day and day.weekday() == 6),
                        "lane": lanes.get(plan_id, 0),
                    }
                )
        return bars_by_day

    # plan 변경 -----------------------------------------------------------
    # S4(M6/D9): render_calendar()/refresh_detail_window() 수동 fanout을
    # store.notify("plans")로 대체한다 — 달력은 app이 "plans"를 구독해 스스로
    # 다시 그리고, DetailScheduleWindow는 열려 있을 때 스스로 구독해 새로고침한다.
    # 일정창(schedule_windows)의 apply_theme()는 구독 대상이 아닌 임시 창이라 계속
    # 직접 호출한다.
    def add_plan(self, plan: dict) -> None:
        """새 계획을 추가하고 저장합니다."""
        app = self.app
        app.store.plans().append(plan)
        app.save()
        app.store.notify("plans")
        schedule = app.schedule_windows.get(str(plan.get("start", ""))[:10])
        if schedule and schedule.isVisible():
            schedule.apply_theme()

    def update_plan(self, updated_plan: dict) -> None:
        """기존 계획 내용을 수정하고 저장합니다."""
        app = self.app
        plans = app.store.plans()
        for index, plan in enumerate(plans):
            if plan.get("id") == updated_plan.get("id"):
                plans[index] = updated_plan
                break
        app.save()
        app.store.notify("plans")
        for window in list(app.schedule_windows.values()):
            if window.isVisible():
                window.apply_theme()

    def delete_plan(self, plan_id: str) -> None:
        """계획을 삭제하고 저장합니다."""
        app = self.app
        app.store.plans()[:] = [
            plan for plan in app.store.plans() if plan.get("id") != plan_id
        ]
        app.save()
        app.store.notify("plans")

    def find_plan(self, plan_id: str) -> dict | None:
        """id로 계획을 찾아 반환합니다."""
        for plan in self.app.store.plans():
            if plan.get("id") == plan_id:
                return plan
        return None

    def plan_display_text(self, plan: dict) -> str:
        """계획을 화면에 보여줄 문자열로 변환합니다."""
        title = plan.get("title", "")
        start = str(plan.get("start", "")).replace("T", " ")[:16]
        end = str(plan.get("end", "")).replace("T", " ")[:16]
        if plan.get("kind") == "long":
            return f"{title} | {start[:10]} - {end[:10]}"
        return f"{title} | {start[11:16]} - {end[11:16]}"

    # recurring tasks -------------------------------------------------------
    def period_label(self, period: str) -> str:
        """반복 주기(daily/weekly/monthly/yearly)를 화면용 라벨로 변환합니다."""
        for period_key, label_key, fallback in RepeatWindow.PERIODS:
            if period_key == period:
                return translate(self.app.store.get("language", "ko"), label_key, fallback)
        return period

    def recurring_current_key(self, period: str) -> str:
        """현재 반복 주기에 해당하는 날짜 키를 반환합니다."""
        today = date.today()
        if period == "daily":
            return today.isoformat()
        if period == "weekly":
            year, week, _weekday = today.isocalendar()
            return f"{year}-W{week:02}"
        if period == "monthly":
            return today.strftime("%Y-%m")
        return today.strftime("%Y")

    def recurring_tasks_for_today(self) -> list[tuple[str, dict]]:
        """오늘 기준으로 표시할 반복 작업 목록을 반환합니다."""
        rows: list[tuple[str, dict]] = []
        for period, _label_key, _fallback in RepeatWindow.PERIODS:
            rows.extend((period, task) for task in self.app.store.recurring_tasks().setdefault(period, []))
        return rows

    def find_recurring_task(self, period: str, task_id: str) -> dict | None:
        """id로 반복 작업을 찾아 반환합니다."""
        for task in self.app.store.recurring_tasks().setdefault(period, []):
            if task.get("id") == task_id:
                return task
        return None

    def set_recurring_done(self, period: str, task: dict, checked: bool) -> None:
        """반복 작업의 완료 여부를 갱신합니다."""
        app = self.app
        current = self.recurring_current_key(period)
        counted = task.setdefault("counted_keys", [])
        if checked:
            if current not in counted:
                task["done_count"] = int(task.get("done_count", 0)) + 1
                counted.append(current)
            task["done"] = current
        else:
            if task.get("done") == current and current in counted:
                task["done_count"] = max(0, int(task.get("done_count", 0)) - 1)
                counted.remove(current)
            task["done"] = ""
        app.save()
        # S4(M6/D9): repeat_window는 계속 직접 새로고침(같은 위젯이 즉시 반응해야
        # 체크박스가 튀지 않는다), DetailScheduleWindow 등 다른 구독자는 notify로.
        if app.repeat_window and app.repeat_window.isVisible():
            app.repeat_window.refresh_all()
        app.store.notify("tasks")
