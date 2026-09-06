"""Today 섹션의 네 그룹을 계산하는 Qt 독립 순수 함수입니다.

완료와 나의 하루 판정은 task_logic을 재사용합니다. 그룹 경계는 다음과 같습니다.

- 오늘 일정 = `plans` 중 오늘에 걸쳐 있는 것(`시작일 <= 오늘 <= 종료일`, 시작 시각 오름차순).
- 놓친 항목 = `due < 오늘`인 미완료 할 일.
- 오늘 마감 = `due == 오늘`인 미완료 할 일.
- 나의 하루 = `smart_list_my_day(tasks, today)` 중 앞 두 그룹에 들어가지 않은 것.
- 완료된 항목(`completed_at`)은 `is_active`/`smart_list_my_day`가 이미 걸러낸다.
- 하루메모는 읽기 전용 Today의 탐색 대상과 맞지 않아 포함하지 않습니다.

한 항목은 한 그룹에만 나오며 우선순위는 놓친 > 오늘 마감 > 나의 하루입니다.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from chronofox.core.task_logic import is_active, smart_list_my_day

# 그룹별 초과분 계산을 위해 TodayGroup.total은 상한 적용 전 개수를 보존한다.
MAX_GROUP_ITEMS = 5

__all__ = ["MAX_GROUP_ITEMS", "TodayGroup", "TodaySummary", "build_today_summary"]


@dataclass(frozen=True)
class TodayGroup:
    """한 그룹의 표시 대상(`MAX_GROUP_ITEMS`로 상한 적용됨)과 상한 적용 전 전체 개수."""

    items: list[dict]
    total: int


@dataclass(frozen=True)
class TodaySummary:
    """Today 섹션의 네 그룹을 표시 순서대로 보관합니다.
    나의 하루)와 같다."""

    today_events: TodayGroup
    missed: TodayGroup
    due_today: TodayGroup
    my_day: TodayGroup


def _cap(items: list[dict]) -> TodayGroup:
    return TodayGroup(items=items[:MAX_GROUP_ITEMS], total=len(items))


def _parse_plan_start(plan: dict) -> datetime | None:
    start = plan.get("start")
    if not start:
        return None
    try:
        return datetime.fromisoformat(str(start))
    except ValueError:
        return None


def _plan_end_date(plan: dict, start_dt: datetime) -> date:
    """계획의 종료 날짜. `PlanService.plan_end_date`와 같은 규칙 — `end`가 없거나 깨졌으면
    시작일로 보고, 종료가 시작보다 앞서면 시작일로 끌어올린다."""
    raw = plan.get("end") or plan.get("start")
    try:
        end_day = date.fromisoformat(str(raw)[:10])
    except ValueError:
        end_day = start_dt.date()
    return max(start_dt.date(), end_day)


def _today_plans(plans: Iterable[dict], today: date) -> list[dict]:
    """오늘에 걸쳐 있는 일정을 시작 시각 오름차순으로 반환합니다.

    `start` 날짜가 오늘인 것만 고르면 3일짜리 기간 일정(`kind="long"`)이 둘째 날부터
    Today에서 사라진다. 앱의 나머지 전부(`PlanService.plans_for_day`, 달력 막대)가
    `시작일 <= 날짜 <= 종료일`로 판정하므로 여기서도 같은 규칙을 쓴다.
    """
    rows: list[tuple[dict, datetime]] = []
    for plan in plans:
        start_dt = _parse_plan_start(plan)
        if start_dt is None:
            continue
        if not (start_dt.date() <= today <= _plan_end_date(plan, start_dt)):
            continue
        rows.append((plan, start_dt))
    rows.sort(key=lambda row: (row[1], str(row[0].get("title", ""))))
    return [plan for plan, _start_dt in rows]


def _parse_due(task: dict) -> date | None:
    due = task.get("due")
    if not due:
        return None
    try:
        return date.fromisoformat(str(due))
    except ValueError:
        return None


def _missed_tasks(tasks: Iterable[dict], today: date) -> list[dict]:
    """오늘 전에 마감된 미완료 할 일을 오래 놓친 순으로 반환합니다."""
    rows: list[tuple[dict, date]] = []
    for task in tasks:
        if not is_active(task):
            continue
        due_date = _parse_due(task)
        if due_date is None or due_date >= today:
            continue
        rows.append((task, due_date))
    rows.sort(key=lambda row: (row[1], str(row[0].get("created", ""))))
    return [task for task, _due_date in rows]


def _due_today_tasks(tasks: Iterable[dict], today: date) -> list[dict]:
    """오늘 마감인 미완료 할 일을 생성 순서로 반환합니다."""
    items = [task for task in tasks if is_active(task) and _parse_due(task) == today]
    items.sort(key=lambda task: str(task.get("created", "")))
    return items


def build_today_summary(*, plans: Iterable[dict], tasks: Iterable[dict], today: date) -> TodaySummary:
    """Today 섹션의 네 그룹을 계산합니다.

    `plans`/`tasks`는 `app.store.plans()`/`app.task_service.tasks()`가 반환하는 live 참조를
    그대로 넘겨받아도 되지만, 이 함수 자체는 어떤 인자도 변형하지 않습니다(순수 함수).
    """
    tasks_list = list(tasks)

    today_events = _today_plans(plans, today)
    missed = _missed_tasks(tasks_list, today)
    due_today = _due_today_tasks(tasks_list, today)

    # 한 항목은 한 그룹에만 나오도록 놓친 작업과 오늘 마감 작업을 나의 하루에서 제외한다.
    dedup_ids = {str(task.get("id")) for task in missed} | {str(task.get("id")) for task in due_today}
    my_day = [task for task in smart_list_my_day(tasks_list, today) if str(task.get("id")) not in dedup_ids]

    return TodaySummary(
        today_events=_cap(today_events),
        missed=_cap(missed),
        due_today=_cap(due_today),
        my_day=_cap(my_day),
    )
