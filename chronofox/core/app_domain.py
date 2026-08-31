"""S4(M5): FoxCalendarApp의 plan/schedule/recurring 도메인 책임 분리 (D8).

PlanService는 ``app``(FoxCalendarApp)을 받아 store 기반 plan/schedule/recurring-task
도메인 로직을 담당한다. app은 이 클래스의 메서드를 얇게 위임만 하며, 호출부
(schedule_window.py 등)는 계속 ``app.add_plan(...)`` 같은 기존 메서드를 무수정으로
호출한다(D8).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from chronofox.core import app_config
from chronofox.core.task_logic import complete_task as _complete_task
from chronofox.core.task_logic import due_task_reminders as _due_task_reminders
from chronofox.core.task_logic import is_active as _task_is_active
from chronofox.core.task_logic import normalize_recurrence, normalize_task, normalize_task_list
from chronofox.core.task_logic import smart_list_all as _smart_list_all
from chronofox.core.task_logic import smart_list_completed as _smart_list_completed
from chronofox.core.task_logic import smart_list_important as _smart_list_important
from chronofox.core.task_logic import smart_list_my_day as _smart_list_my_day
from chronofox.core.task_logic import smart_list_planned as _smart_list_planned
from chronofox.core.task_logic import uncomplete_task as _uncomplete_task
from chronofox.core.todo_logic import TASK_PERIOD_CHOICES, normalize_step
from chronofox.ui.app_i18n import translate
from chronofox.ui.app_theme import PLAN_LANE_COLORS

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp


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
                        "kind": plan.get("kind"),
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
        for period_key, label_key, fallback in TASK_PERIOD_CHOICES:
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
        for period, _label_key, _fallback in TASK_PERIOD_CHOICES:
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
        # P-5b: 독립 할 일 창은 제거됐으므로 허브를 포함한 모든 화면은 topic 구독으로
        # 갱신한다. 같은 데이터를 두 경로로 직접 fanout하지 않는다.
        app.store.notify("tasks")


class TaskService:
    """todo-v3 ``tasks: []`` 평면 모델의 저장·조회·완료·알림을 담당합니다.

    할 일 허브, Quick Input, 알림 스캔은 이 서비스를 공용 저장 경계로 사용한다. 기존
    ``recurring_tasks`` 버킷은 일정 창의 이전 반복 기능 호환을 위해 별도로 유지한다.

    판정·계산은 전부 `task_logic.py`(Qt-free, T1)를 그대로 재사용한다 — 이 클래스는
    store 접근·id 발급·배열 반영·저장·notify만 담당하고 규칙을 재구현하지 않는다.
    """

    def __init__(self, app: FoxCalendarApp) -> None:
        self.app = app

    # 잠금 -------------------------------------------------------------
    def locked(self) -> bool:
        """§4 T2 계약 — v2→v3 마이그레이션 실패 시 할 일 쓰기만 세션 동안 잠근다.
        읽기(조회·스마트 목록·알림 판정)는 잠금과 무관하게 항상 동작한다."""
        return app_config.tasks_locked()

    # 조회 ---------------------------------------------------------------
    def tasks(self) -> list[dict]:
        """전체 task 목록(live 참조)을 반환합니다."""
        return self.app.store.tasks()

    def task_lists(self) -> list[dict]:
        """전체 목록(task_lists) 메타데이터(live 참조)를 반환합니다."""
        return self.app.store.task_lists()

    def find_task(self, task_id: str) -> dict | None:
        """id로 task를 찾아 반환합니다."""
        for task in self.app.store.tasks():
            if task.get("id") == task_id:
                return task
        return None

    def find_task_list(self, list_id: str) -> dict | None:
        """id로 목록(task_lists)을 찾아 반환합니다."""
        for task_list in self.app.store.task_lists():
            if task_list.get("id") == list_id:
                return task_list
        return None

    # 스마트 목록 (읽기 전용 — task_logic 판정 재사용, §4 규칙 5·6) ----------
    def smart_list_my_day(self) -> list[dict]:
        """나의 하루(`my_day_date == 오늘`)."""
        return _smart_list_my_day(self.app.store.tasks(), date.today())

    def smart_list_important(self) -> list[dict]:
        """중요 표시된 미완료 task."""
        return _smart_list_important(self.app.store.tasks())

    def smart_list_planned(self) -> list[dict]:
        """계획됨(`due` 또는 `remind_at` 보유)."""
        return _smart_list_planned(self.app.store.tasks())

    def smart_list_all(self) -> list[dict]:
        """전체 = 미완료 전부."""
        return _smart_list_all(self.app.store.tasks())

    def smart_list_completed(self) -> list[dict]:
        """완료된 task, 최근 완료순."""
        return _smart_list_completed(self.app.store.tasks())

    # 쓰기 (잠금 시 no-op) -------------------------------------------------
    def add_task(
        self,
        text: str,
        *,
        notes: str = "",
        due: str | None = None,
        remind_at: str | None = None,
        important: bool = False,
        my_day_date: str | None = None,
        list_id: str | None = None,
        steps: list[dict] | None = None,
        order: int | None = None,
        recurrence: dict | None = None,
    ) -> dict | None:
        """1회성 또는 반복 task를 새로 만들어 저장합니다.

        `recurrence`(`{"period": ..., "anchor_day": ...}`)가 주어지면 반복 task로,
        생략하면 1회성 task로 만듭니다(§4 규칙 7 — Quick Input 무신호/반복신호 구분과
        동일한 갈래를 호출부가 이미 판정해 넘겨준다고 가정한다). 잠금 상태(§4 T2 계약)면
        아무것도 바꾸지 않고 None을 반환합니다.
        """
        if self.locked():
            return None
        app = self.app
        normalized_steps = [normalize_step(dict(step)) for step in (steps or [])]
        task_recurrence = normalize_recurrence(dict(recurrence)) if recurrence else None
        task = normalize_task(
            {
                "id": uuid.uuid4().hex,
                "text": text,
                "notes": notes,
                "created": datetime.now().isoformat(),
                "completed_at": None,
                "due": due,
                "remind_at": remind_at,
                "important": important,
                "my_day_date": my_day_date,
                "list_id": list_id,
                "steps": normalized_steps,
                "order": order,
                "recurrence": task_recurrence,
            }
        )
        app.store.tasks().append(task)
        app.save()
        app.store.notify("tasks")
        return task

    def update_task(self, task_id: str, **fields) -> dict | None:
        """기존 task의 §4 스키마 필드 일부를 갱신합니다. 스키마 밖의 키는 무시합니다.
        잠금 상태거나 task_id를 찾지 못하면 아무것도 바꾸지 않고 None을 반환합니다.

        `remind_at`을 바꾸면 과거 `remind_fired` 값과 자연히 달라지므로(§6 catch-up 계약)
        별도 초기화 없이도 새 시각 기준으로 다시 발화 대상이 됩니다.
        """
        if self.locked():
            return None
        task = self.find_task(task_id)
        if task is None:
            return None
        allowed = {
            "text", "notes", "due", "remind_at", "important",
            "my_day_date", "list_id", "steps", "order", "recurrence",
        }
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key == "steps" and value is not None:
                value = [normalize_step(dict(step)) for step in value]
            if key == "recurrence" and value is not None:
                value = normalize_recurrence(dict(value))
            task[key] = value
        self.app.save()
        self.app.store.notify("tasks")
        return task

    def delete_task(self, task_id: str) -> bool:
        """task를 삭제합니다. 잠금 상태거나 대상이 없으면 아무것도 바꾸지 않고 False."""
        if self.locked():
            return False
        tasks = self.app.store.tasks()
        before = len(tasks)
        tasks[:] = [task for task in tasks if task.get("id") != task_id]
        if len(tasks) == before:
            return False
        self.app.save()
        self.app.store.notify("tasks")
        return True

    def toggle_complete(self, task_id: str) -> dict | None:
        """task 완료/완료취소를 토글합니다(§4 규칙 1·2·4·11·12·13). 잠금 상태거나 대상이
        없으면 아무것도 바꾸지 않고 None을 반환합니다.

        완료 처리는 `task_logic.complete_task`를 그대로 호출한다. 반복 task면 돌아온
        다음 pending 인스턴스를 `tasks` 배열에 함께 추가하고, 완료된 task에 additive 필드
        `next_instance_id`(이 완료가 만들어낸 재생성분의 id — 재생성분 추적 전용, §4 스키마
        밖 필드)를 기록해 나중에 완료 취소할 때 어떤 인스턴스가 짝인지 다시 찾을 수 있게
        한다.

        완료 취소는 `next_instance_id`로 짝을 찾아 `task_logic.uncomplete_task`에 넘긴다.
        반환된 두 번째 값이 None이면(재생성분이 무변경) 그 재생성분을 배열에서 제거한다
        (§4 규칙 11). 사용자가 편집·완료해 독립 항목으로 남는 경우는 이미 배열에 있는
        같은 객체를 그대로 두고 원본만 되돌린다. 되돌린 원본에서는 `next_instance_id`를
        지운다 — 더 이상 그 재생성분을 "짝"으로 추적하지 않는다(재생성분은 독립 task로
        남는다).
        """
        if self.locked():
            return None
        task = self.find_task(task_id)
        if task is None:
            return None

        today = date.today()
        now = datetime.now()
        tasks = self.app.store.tasks()

        if _task_is_active(task):
            completed, next_instance = _complete_task(task, today, now)
            completed.pop("next_instance_id", None)
            if next_instance is not None:
                completed["next_instance_id"] = next_instance["id"]
            for index, existing in enumerate(tasks):
                if existing.get("id") == task_id:
                    tasks[index] = completed
                    break
            if next_instance is not None:
                tasks.append(next_instance)
            result = completed
        else:
            next_instance_id = task.get("next_instance_id")
            next_instance = self.find_task(next_instance_id) if next_instance_id else None
            reverted, result_next, _reverted_flag = _uncomplete_task(task, next_instance, today)
            reverted.pop("next_instance_id", None)
            if result_next is None and next_instance is not None:
                # 재생성분이 완료 시점 그대로(무변경)라 제거 대상(§4 규칙 11).
                tasks[:] = [t for t in tasks if t.get("id") != next_instance.get("id")]
            for index, existing in enumerate(tasks):
                if existing.get("id") == task_id:
                    tasks[index] = reverted
                    break
            result = reverted

        self.app.save()
        self.app.store.notify("tasks")
        return result

    def toggle_my_day(self, task_id: str) -> dict | None:
        """나의 하루 포함 여부를 토글합니다(§4 규칙 5). 잠금 상태거나 대상이 없으면 None."""
        if self.locked():
            return None
        task = self.find_task(task_id)
        if task is None:
            return None
        today_iso = date.today().isoformat()
        task["my_day_date"] = None if task.get("my_day_date") == today_iso else today_iso
        self.app.save()
        self.app.store.notify("tasks")
        return task

    def toggle_important(self, task_id: str) -> dict | None:
        """중요 표시를 토글합니다. 잠금 상태거나 대상이 없으면 None."""
        if self.locked():
            return None
        task = self.find_task(task_id)
        if task is None:
            return None
        task["important"] = not bool(task.get("important"))
        self.app.save()
        self.app.store.notify("tasks")
        return task

    def add_task_list(self, name: str) -> dict | None:
        """새 목록(task_lists)을 추가합니다. 잠금 상태면 아무것도 바꾸지 않고 None."""
        if self.locked():
            return None
        task_list = normalize_task_list({"id": uuid.uuid4().hex, "name": name})
        self.app.store.task_lists().append(task_list)
        self.app.save()
        self.app.store.notify("tasks")
        return task_list

    # 순서/단계 (화면이 store.tasks()를 직접 건드리지 않도록 실제 쓰기는 여기서 한다) --

    def ensure_task_order(self) -> bool:
        """`order`가 없는(또는 정수가 아닌) task에 현재 저장 순서(index)를 채웁니다(D8 계승,
        additive). 잠금 상태면 아무것도 바꾸지 않고 False. 반환값은 변경 여부다.

        의도적으로 `notify("tasks")`를 호출하지 않는다 — 이 메서드는 화면 갱신
        시작부(tasks_section.refresh_tasks_view)마다 방어적으로
        호출되는 조용한 정규화라서, notify를 쏘면 "tasks"를 구독한 다른 창(예:
        DetailScheduleWindow.refresh_events)이 같은 갱신 도중 재진입해 화면을 이중으로
        그리는 문제가 실제로 재현됐다(T4). `order` 채움 자체는 이번 갱신이 곧바로 반영하므로
        별도 알림이 없어도 화면은 최신 상태로 그려진다."""
        if self.locked():
            return False
        changed = False
        for index, task in enumerate(self.app.store.tasks()):
            order = task.get("order")
            if not isinstance(order, int) or isinstance(order, bool):
                task["order"] = index
                changed = True
        if changed:
            self.app.save()
        return changed

    def reassign_order(self, ordered_task_ids: list[str]) -> None:
        """주어진 순서(ordered_task_ids)대로 각 task의 `order`를 0부터 재기록합니다
        (D8 위/아래 버튼 재정렬 — 화면이 미완료 목록의 새 순서를 계산해 넘긴다).
        목록에 없는 id는 무시합니다. 잠금 상태면 아무것도
        바꾸지 않습니다."""
        if self.locked():
            return
        by_id = {task.get("id"): task for task in self.app.store.tasks()}
        for index, task_id in enumerate(ordered_task_ids):
            task = by_id.get(task_id)
            if task is not None:
                task["order"] = index
        self.app.save()
        self.app.store.notify("tasks")

    def add_step(self, task_id: str, text: str) -> bool:
        """task에 단계(step)를 추가합니다(D7 계승). 빈 입력이거나 잠금 상태거나 task를
        찾지 못하면 아무것도 바꾸지 않고 False."""
        if self.locked():
            return False
        text = text.strip()
        if not text:
            return False
        task = self.find_task(task_id)
        if task is None:
            return False
        steps = task.setdefault("steps", [])
        steps.append(normalize_step({"id": uuid.uuid4().hex, "text": text, "done": False}))
        self.app.save()
        self.app.store.notify("tasks")
        return True

    def toggle_step(self, task_id: str, step_id: str, checked: bool) -> None:
        """task의 특정 단계 완료 여부를 설정합니다(D7 계승). 잠금 상태거나 대상이 없으면
        아무것도 바꾸지 않습니다."""
        if self.locked():
            return
        task = self.find_task(task_id)
        if task is None:
            return
        for step in task.get("steps", []):
            if step.get("id") == step_id:
                step["done"] = checked
                break
        self.app.save()
        self.app.store.notify("tasks")

    def delete_step(self, task_id: str, step_id: str) -> None:
        """task에서 단계를 삭제합니다(D7 계승). 잠금 상태거나 대상이 없으면 아무것도
        바꾸지 않습니다."""
        if self.locked():
            return
        task = self.find_task(task_id)
        if task is None:
            return
        steps = task.get("steps", [])
        steps[:] = [step for step in steps if step.get("id") != step_id]
        self.app.save()
        self.app.store.notify("tasks")

    # 알림 (T3 — §4 규칙 9, §6 알림 계약: 알람과 동일한 10분 catch-up) -------
    def due_task_reminders(self, now: datetime | None = None) -> list[dict]:
        """`remind_at`이 도래한 미완료 task를 찾아 반환합니다. 판정 자체는
        `task_logic.due_task_reminders`(순수 함수)를 그대로 쓰고, 이 메서드는 그 위에
        중복 발화 방지 마킹(`remind_fired`)과 저장·notify를 더한다.

        실제 UI 발화(트레이 풍선 등)는 이 메서드를 호출하는 쪽(T4, 예: 기존
        `on_reminder_scan` 30초 스캔 경로)의 책임이다 — 여기서는 "무엇을 발화해야
        하는가"를 반환하는 데까지만 한다.

        잠금 상태에서도 판정(읽기)은 계속 동작하지만, `remind_fired` 마킹(쓰기)은
        잠금이면 건너뛴다 — 다음 스캔에서 같은 항목이 다시 반환되어, 락이 풀리기 전까지
        중복 발화를 방지하는 쓰기가 손실되지 않는다.
        """
        due = _due_task_reminders(self.app.store.tasks(), now or datetime.now())
        if due and not self.locked():
            for task in due:
                task["remind_fired"] = task.get("remind_at")
            self.app.save()
            self.app.store.notify("tasks")
        return due
