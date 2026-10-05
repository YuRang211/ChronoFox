"""todo-v3 평면 `tasks: []` 모델의 정규화·완료·반복·스마트 목록 계산을 담당하는 Qt-free 순수 함수 모음.

`planning/PROJECT.md` §4 "todo-v3 계약"(T1) 구현. 현행 `recurring_tasks[period]` 버킷 모델과
달리, 이 모듈이 다루는 각 task는 `tasks: []`의 독립된 dict 항목이다. 반복 작업의 완료는 완료된
인스턴스를 그대로 보존하고 다음 pending 인스턴스 하나를 별도 항목으로 새로 만든다(§4 규칙 2).

Qt import는 core 계층 규약상 절대 금지다. 현재 시각·날짜는 항상 `now`/`today` 인자로만 받는다
(결정적 함수 — `quick_input_parser.parse(text, now)` 선례와 동일한 요건). 주기 키·스트릭 계산은
`todo_logic.py`(구 모델의 Qt-free 선례)의 `period_key`/`previous_period_key`/`compute_streak`를
그대로 재사용해 두 모델이 같은 주기 경계 규칙을 공유하게 한다.

공개 API는 크게 네 갈래다.
- 정규화: `normalize_task`, `normalize_recurrence`, `normalize_task_list`
- 완료/취소: `complete_task`, `uncomplete_task`
- 스마트 목록: `is_active`, `is_planned`, `smart_list_*`
- 달력 연동: `tasks_by_due_date`
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime, timedelta

from chronofox.core.todo_logic import compute_streak, period_key

PERIODS = ("daily", "weekly", "monthly", "quarterly", "yearly")

# 할 일 알림은 알람과 같은 10분 catch-up 창을 사용한다.
REMINDER_CATCHUP_WINDOW = timedelta(minutes=10)

__all__ = [
    "PERIODS",
    "REMINDER_CATCHUP_WINDOW",
    "normalize_task",
    "normalize_recurrence",
    "normalize_task_list",
    "compute_next_due",
    "complete_task",
    "uncomplete_task",
    "is_active",
    "is_completed",
    "is_upcoming",
    "recurrence_available_on",
    "current_task_rows",
    "task_series_history",
    "is_planned",
    "is_my_day",
    "smart_list_my_day",
    "smart_list_important",
    "smart_list_planned",
    "smart_list_all",
    "smart_list_completed",
    "tasks_by_due_date",
    "task_streak",
    "due_task_reminders",
]


# ---------------------------------------------------------------------------
# 정규화 (§4 목표 스키마 — additive, 미지 필드 보존)
# ---------------------------------------------------------------------------


def normalize_recurrence(recurrence: dict) -> dict:
    """recurrence dict에 누락 필드를 채웁니다(`period`/`anchor_day`/`streak_keys`). in-place + 반환."""
    recurrence.setdefault("period", "daily")
    recurrence.setdefault("anchor_day", None)
    recurrence.setdefault("streak_keys", [])
    return recurrence


def normalize_task(task: dict) -> dict:
    """task dict에 §4 목표 스키마의 누락 필드를 채웁니다. 미지 필드는 손대지 않고 보존합니다(다운그레이드 안전망).

    `setdefault`만 사용하므로 이미 있는 값(모르는 필드 포함)은 절대 덮어쓰지 않습니다. in-place로
    수정하고 같은 dict를 반환합니다(`todo_logic.normalize_step` 선례와 동일한 관용구).
    """
    task.setdefault("id", "")
    task.setdefault("text", "")
    task.setdefault("notes", "")
    task.setdefault("created", "")
    task.setdefault("completed_at", None)
    task.setdefault("due", None)
    task.setdefault("remind_at", None)
    task.setdefault("important", False)
    task.setdefault("my_day_date", None)
    task.setdefault("list_id", None)
    task.setdefault("steps", [])
    task.setdefault("order", None)
    task.setdefault("recurrence", None)
    if task["recurrence"] is not None:
        normalize_recurrence(task["recurrence"])
    return task


def normalize_task_list(task_list: dict) -> dict:
    """`task_lists[*]` dict에 누락 필드(`id`/`name`)를 채웁니다. in-place + 반환."""
    task_list.setdefault("id", "")
    task_list.setdefault("name", "")
    return task_list


# ---------------------------------------------------------------------------
# 다음 발생일 계산 (§4 규칙 3·4 — anchor 보존 + 월말 클램프 + 2/29 + 과거 연쇄 금지)
# ---------------------------------------------------------------------------


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return (date(year + 1, 1, 1) - date(year, 12, 1)).days
    return (date(year, month + 1, 1) - date(year, month, 1)).days


def _advance_once(period: str, current: date, anchor_day: int | None) -> date:
    """`current`를 한 주기만큼 전진시킵니다. monthly/yearly는 `anchor_day`를 그 달/해의 말일로 클램프합니다."""
    if period == "daily":
        return date.fromordinal(current.toordinal() + 1)
    if period == "weekly":
        return date.fromordinal(current.toordinal() + 7)
    if period == "quarterly":
        month = ((current.month - 1) // 3 + 1) * 3 + 1
        return date(current.year + (month > 12), 1 if month > 12 else month, 1)

    anchor = anchor_day if anchor_day is not None else current.day
    if period == "monthly":
        year, month = current.year, current.month + 1
        if month > 12:
            month = 1
            year += 1
        day = min(anchor, _days_in_month(year, month))
        return date(year, month, day)
    if period == "yearly":
        year = current.year + 1
        month = current.month
        day = min(anchor, _days_in_month(year, month))
        return date(year, month, day)
    raise ValueError(f"unknown recurrence period: {period!r}")


def compute_next_due(period: str, current_due: date, anchor_day: int | None, today: date) -> date:
    """`current_due` 기준 다음 발생일을 계산합니다.

    §4 규칙 3(anchor 보존 + 월말 클램프 + 2/29 처리)과 규칙 4(과거 발생 연쇄 생성 금지)를 함께
    적용합니다: 한 번 전진한 뒤 결과가 `today` 이전이거나 같으면(지연 완료) `today` 이후가 될 때까지
    계속 전진하되, 중간 발생분은 반환하지 않고 최종 결과 하나만 돌려줍니다.
    """
    next_due = _advance_once(period, current_due, anchor_day)
    while next_due <= today:
        next_due = _advance_once(period, next_due, anchor_day)
    return next_due


# ---------------------------------------------------------------------------
# 완료 / 완료 취소 (§4 규칙 1·2·4)
# ---------------------------------------------------------------------------


def _current_period_key(task: dict, today: date) -> str:
    period = task["recurrence"]["period"]
    value = task["recurrence"].get("start_date") or task.get("due")
    basis = date.fromisoformat(value) if value else today
    return period_key(period, basis)


def recurrence_available_on(task: dict) -> date | None:
    """반복 회차 시작일을 읽는다. 기존 마감일 및 무기한 재생성분도 보존한다."""
    recurrence = task.get("recurrence")
    if not recurrence:
        return None
    for value in (recurrence.get("start_date"), task.get("due")):
        if value:
            try:
                return date.fromisoformat(str(value))
            except ValueError:
                continue
    # 구버전의 무기한 재생성분은 부모 회차 키가 ID 끝에 기록돼 있다.
    period = recurrence.get("period", "daily")
    if period in PERIODS and "::" in str(task.get("id", "")):
        try:
            created = date.fromisoformat(str(task.get("created", ""))[:10])
        except ValueError:
            return None
        key = period_key(period, created)
        if str(task["id"]).endswith("::" + key) and key in recurrence.get("streak_keys", []):
            return _next_period_start(period, created)
    return None


def _next_period_start(period: str, today: date) -> date:
    if period == "weekly":
        return today + timedelta(days=7 - today.weekday())
    if period == "monthly":
        return _advance_once(period, today.replace(day=1), 1)
    if period == "yearly":
        return date(today.year + 1, 1, 1)
    return _advance_once(period, today, today.day)


def is_upcoming(task: dict, today: date) -> bool:
    """미래 반복 회차만 예정으로 분류하며 1회성 작업은 숨기지 않는다."""
    start = recurrence_available_on(task)
    return is_active(task) and start is not None and start > today


def _task_chains(tasks: Iterable[dict]) -> list[list[dict]]:
    items = list(tasks)
    ids: dict[str, list[int]] = {}
    for index, task in enumerate(items):
        ids.setdefault(str(task.get("id", "")), []).append(index)
    edges: dict[int, int] = {}
    incoming: dict[int, list[int]] = {}
    for index, task in enumerate(items):
        target = ids.get(str(task.get("next_instance_id", "")), [])
        if (len(target) != 1 or len(ids.get(str(task.get("id", "")), [])) != 1
                or not task.get("recurrence") or not is_completed(task)):
            continue
        other = target[0]
        if other != index and items[other].get("recurrence"):
            edges[index] = other
            incoming.setdefault(other, []).append(index)
    edges = {source: target for source, target in edges.items() if len(incoming[target]) == 1}
    checked: set[int] = set()
    cyclic: set[int] = set()
    for source in edges:
        path: list[int] = []
        positions: dict[int, int] = {}
        current = source
        while current in edges and current not in checked:
            if current in positions:
                cyclic.update(path[positions[current]:])
                break
            positions[current] = len(path)
            path.append(current)
            current = edges[current]
        checked.update(path)
    neighbors: list[set[int]] = [set() for _ in items]
    # Damaged branches/cycles cannot establish ownership of another item's history.
    for source, target in edges.items():
        if source not in cyclic and target not in cyclic:
            neighbors[source].add(target)
            neighbors[target].add(source)
    visited: set[int] = set()
    groups = []
    for index in range(len(items)):
        if index in visited:
            continue
        stack = [index]
        component = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(neighbors[current] - visited)
        groups.append([items[position] for position in sorted(component)])
    return groups


def current_task_rows(tasks: Iterable[dict], today: date) -> list[dict]:
    """Project each linked recurring chain to its current row without changing stored history."""
    rows = []
    for group in _task_chains(tasks):
        pending = [task for task in group if is_active(task)]
        if len(pending) != 1:
            # Ambiguous or broken chains must not silently discard user items.
            rows.extend(group)
            continue
        current = pending[0]
        if is_upcoming(current, today):
            parent = next((task for task in group
                           if task.get("next_instance_id") == current.get("id") and is_completed(task)), None)
            if parent is not None:
                current = parent
        rows.append(current)
    rows.sort(key=_sort_key)
    return rows


def task_series_history(tasks: Iterable[dict], task_id: str) -> list[dict]:
    """Return actual completion snapshots linked to an item, never matched by title."""
    for group in _task_chains(tasks):
        if any(task.get("id") == task_id for task in group):
            return sorted((task for task in group if is_completed(task)),
                          key=lambda task: str(task.get("completed_at") or ""), reverse=True)
    return []


def _build_next_instance(task: dict, today: date, now: datetime, current_key: str, updated_streak: list[str]) -> dict:
    """완료된 반복 task로부터 다음 pending 인스턴스를 결정적으로 만듭니다.

    `complete_task`와 `uncomplete_task`(무변경 판정)가 이 함수를 공유해서, 두 시점에 같은 입력이면
    바이트 단위로 같은 인스턴스가 나오게 합니다(결정성 요건).
    """
    recurrence = task["recurrence"]
    period = recurrence["period"]
    due = task.get("due")

    next_due: str | None
    if due:
        anchor_day = recurrence.get("anchor_day")
        next_due = compute_next_due(period, date.fromisoformat(due), anchor_day, today).isoformat()
    else:
        next_due = None

    basis = recurrence_available_on(task)
    next_start = (
        compute_next_due(period, basis, recurrence.get("anchor_day"), today)
        if basis else _next_period_start(period, today)
    )

    next_steps = []
    for step in task.get("steps") or []:
        next_steps.append({**step, "done": False})

    return normalize_task(
        {
            "id": f"{task['id']}::{current_key}",
            "text": task.get("text", ""),
            "notes": task.get("notes", ""),
            "created": now.isoformat(),
            "completed_at": None,
            "due": next_due,
            "remind_at": None,
            "important": task.get("important", False),
            "my_day_date": None,
            "list_id": task.get("list_id"),
            "steps": next_steps,
            "order": task.get("order"),
            "recurrence": {
                "period": period,
                "anchor_day": recurrence.get("anchor_day"),
                "streak_keys": list(updated_streak),
                "start_date": next_start.isoformat(),
            },
        }
    )


def complete_task(task: dict, today: date, now: datetime) -> tuple[dict, dict | None]:
    """task를 완료 처리합니다.

    1회성(`recurrence`가 None)이면 `completed_at`만 기록하고 `(완료된_task, None)`을 반환합니다
    (§4 규칙 1 — 활성 스마트 목록에서는 `is_active`가 False가 되어 자연히 사라집니다).

    반복 task면 완료 인스턴스를 보존한 채 다음 pending 인스턴스 하나를 새로 만들어
    `(완료된_task, 다음_인스턴스)`를 반환합니다(§4 규칙 2). 둘 다 호출부가 `tasks` 배열에
    반영해야 하는 별개의 항목입니다 — 이 함수는 배열을 직접 다루지 않습니다.
    """
    completed = dict(task)
    completed["completed_at"] = now.isoformat()

    recurrence = completed.get("recurrence")
    if recurrence is None:
        return completed, None

    current_key = _current_period_key(completed, today)
    updated_streak = [*recurrence.get("streak_keys", []), current_key]
    completed["recurrence"] = {**recurrence, "streak_keys": updated_streak}

    next_instance = _build_next_instance(completed, today, now, current_key, updated_streak)
    return completed, next_instance


def uncomplete_task(original: dict, next_instance: dict | None, today: date) -> tuple[dict, dict | None, bool]:
    """`complete_task`의 완료를 되돌립니다.

    1회성(`recurrence`가 None)이면 항상 `completed_at`을 지우고 `(되돌린_task, None, True)`를
    반환합니다.

    반복 task는 **항상 되돌립니다**(체크 해제는 사용자가 언제든 할 수 있어야 한다 — 우리가 채택한
    MS To Do 모델과 동일). 달라지는 것은 재생성분의 운명뿐입니다:

    - `next_instance`가 완료 시점 그대로(무변경)면 `(되돌린_task, None, True)`를 반환한다.
      두 번째 값 `None`이 호출부에 "이 재생성분을 배열에서 제거하라"는 신호다.
    - `next_instance`가 이미 편집·완료됐으면 `(되돌린_task, next_instance, True)`를 반환한다.
      **사용자가 손댄 항목은 지우지 않는다** — 원본만 미완료로 돌리고 스트릭을 롤백하며,
      재생성분은 독립 항목으로 남긴다(잠시 중복이 보이는 편이 편집 내용을 삭제하는 것보다 안전하다).

    되돌리기를 거부하지 않는 이유: 거부하면 사용자가 실수로 체크한 반복 작업을 재생성분에 손댄
    뒤로는 영구히 되돌릴 수 없어, "체크가 풀리지 않는" 상태가 된다(2026-07-22 검수 판정).
    """
    recurrence = original.get("recurrence")
    if recurrence is None:
        reverted = dict(original)
        reverted["completed_at"] = None
        return reverted, None, True

    try:
        completed_day = date.fromisoformat(str(original.get("completed_at", ""))[:10])
    except ValueError:
        completed_day = today
    current_key = _current_period_key(original, completed_day)
    streak_keys = recurrence.get("streak_keys", [])
    if not streak_keys or streak_keys[-1] != current_key:
        # 완료 흔적(마지막 스트릭 키)이 없으면 스트릭은 건드리지 않되 체크는 풀어준다.
        reverted = dict(original)
        reverted["completed_at"] = None
        return reverted, next_instance, True

    if next_instance is None:
        reverted = dict(original)
        reverted["completed_at"] = None
        reverted["recurrence"] = {**recurrence, "streak_keys": streak_keys[:-1]}
        return reverted, None, True

    rolled_back_streak = streak_keys[:-1]
    # `now`는 `created`에만 영향을 주고 아래 비교 필드에는 영향이 없으므로 더미 값으로 충분하다.
    expected_next = _build_next_instance(
        {**original, "recurrence": {**recurrence, "streak_keys": rolled_back_streak}},
        completed_day,
        datetime.min,
        current_key,
        streak_keys,
    )

    comparable_fields = (
        "text",
        "notes",
        "due",
        "remind_at",
        "important",
        "my_day_date",
        "list_id",
        "steps",
        "order",
        "recurrence",
    )
    reverted = dict(original)
    reverted["completed_at"] = None
    reverted["recurrence"] = {**recurrence, "streak_keys": rolled_back_streak}

    comparable_next = dict(next_instance)
    if "start_date" not in (next_instance.get("recurrence") or {}):
        expected_next["recurrence"].pop("start_date", None)
    if any(comparable_next.get(field) != expected_next.get(field) for field in comparable_fields):
        # 사용자가 손댄 재생성분은 지우지 않고 독립 항목으로 남긴다(원본만 되돌린다).
        return reverted, next_instance, True
    return reverted, None, True


def task_streak(task: dict, today: date) -> int:
    """반복 task의 현재(완료면 이번, 미완료면 직전) 주기부터 역방향 연속 완료 수를 반환합니다.

    `recurrence`가 없으면 0입니다. `todo_logic.compute_streak`를 그대로 재사용합니다.
    """
    recurrence = task.get("recurrence")
    if recurrence is None:
        return 0
    current_key = _current_period_key(task, today)
    return compute_streak(recurrence["period"], recurrence.get("streak_keys", []), current_key)


# ---------------------------------------------------------------------------
# 스마트 목록 판정·정렬 (§4 규칙 5·6)
# ---------------------------------------------------------------------------


def is_active(task: dict) -> bool:
    """미완료(`completed_at`이 없음) 여부."""
    return task.get("completed_at") is None


def is_completed(task: dict) -> bool:
    return not is_active(task)


def is_my_day(task: dict, today: date) -> bool:
    """나의 하루 판정 — `my_day_date == 오늘`만 사용합니다(§4 규칙 5. 날짜가 지나면 자동 제외됨)."""
    return is_active(task) and task.get("my_day_date") == today.isoformat()


def is_planned(task: dict) -> bool:
    """계획됨 판정 — `due` 또는 `remind_at`을 보유."""
    return is_active(task) and bool(task.get("due") or task.get("remind_at"))


def _sort_key(task: dict) -> tuple[int, float, str]:
    """중요 → order(없으면 안정 정렬) → created 순 정렬 키(`todo_logic.classify_and_sort`와 동일 규약)."""
    important_rank = 0 if task.get("important") else 1
    order = task.get("order")
    order_rank = float(order) if isinstance(order, int) and not isinstance(order, bool) else float("inf")
    created = str(task.get("created", ""))
    return (important_rank, order_rank, created)


def smart_list_my_day(tasks: Iterable[dict], today: date) -> list[dict]:
    items = [t for t in tasks if is_my_day(t, today)]
    items.sort(key=_sort_key)
    return items


def smart_list_important(tasks: Iterable[dict]) -> list[dict]:
    items = [t for t in tasks if is_active(t) and t.get("important")]
    items.sort(key=_sort_key)
    return items


def smart_list_planned(tasks: Iterable[dict]) -> list[dict]:
    items = [t for t in tasks if is_planned(t)]
    items.sort(key=_sort_key)
    return items


def smart_list_all(tasks: Iterable[dict]) -> list[dict]:
    """전체 = 미완료 전부."""
    items = [t for t in tasks if is_active(t)]
    items.sort(key=_sort_key)
    return items


def smart_list_completed(tasks: Iterable[dict]) -> list[dict]:
    """완료 = `completed_at` 보유, 최근순."""
    items = [t for t in tasks if is_completed(t)]
    items.sort(key=lambda t: str(t.get("completed_at") or ""), reverse=True)
    return items


# ---------------------------------------------------------------------------
# 달력 연동 (§4 규칙 8)
# ---------------------------------------------------------------------------


def tasks_by_due_date(tasks: Iterable[dict]) -> dict[str, list[dict]]:
    """1회성 마감일 또는 반복 시작일로 미완료 작업을 달력에 배치한다."""
    result: dict[str, list[dict]] = {}
    for task in tasks:
        start = recurrence_available_on(task)
        due = start.isoformat() if start else task.get("due")
        if not due or not is_active(task):
            continue
        result.setdefault(due, []).append(task)
    return result


# ---------------------------------------------------------------------------
# 알림 판정 (T3 — §4 규칙 9, §6 알림 계약: 알람과 동일한 10분 catch-up 창)
# ---------------------------------------------------------------------------


def due_task_reminders(
    tasks: Iterable[dict], now: datetime, catchup: timedelta = REMINDER_CATCHUP_WINDOW
) -> list[dict]:
    """`remind_at`이 도래한 미완료 task를 반환합니다(§6 — 알람과 동일한 10분 catch-up 계약).

    판정 규칙:
    - 완료된 task(`is_active`가 False)는 제외한다.
    - `remind_at`이 없으면 제외한다.
    - `remind_fired == remind_at`(이미 이 발화분을 처리함)이면 제외한다 — 중복 발화 방지.
      `remind_at`이 바뀌면 값이 달라지므로 자연히 다시 발화 대상이 된다.
    - `remind_at <= now < remind_at + catchup`이면 발화 대상이다. `catchup`을 넘겨 지연된
      항목은 이 목록에서 제외한다(정시 폴링 도구가 아니라 판정 함수라, 넘긴 뒤 처리는
      호출부의 몫이다).

    순수 함수라 아무것도 마킹하지 않는다 — `remind_fired` 갱신·저장·notify는 호출부
    (`TaskService.due_task_reminders`)의 책임이다.
    """
    due: list[dict] = []
    for task in tasks:
        if not is_active(task):
            continue
        remind_at = task.get("remind_at")
        if not remind_at:
            continue
        if task.get("remind_fired") == remind_at:
            continue
        try:
            remind_dt = datetime.fromisoformat(remind_at)
        except ValueError:
            continue
        if remind_dt <= now < remind_dt + catchup:
            due.append(task)
    return due
