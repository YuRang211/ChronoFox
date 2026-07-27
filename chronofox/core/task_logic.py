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
from datetime import date, datetime

from chronofox.core.todo_logic import compute_streak, period_key

PERIODS = ("daily", "weekly", "monthly", "yearly")

__all__ = [
    "PERIODS",
    "normalize_task",
    "normalize_recurrence",
    "normalize_task_list",
    "compute_next_due",
    "complete_task",
    "uncomplete_task",
    "is_active",
    "is_completed",
    "is_planned",
    "is_my_day",
    "smart_list_my_day",
    "smart_list_important",
    "smart_list_planned",
    "smart_list_all",
    "smart_list_completed",
    "tasks_by_due_date",
    "task_streak",
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
    due = task.get("due")
    basis = date.fromisoformat(due) if due else today
    return period_key(period, basis)


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

    current_key = _current_period_key(original, today)
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
        today,
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

    if any(next_instance.get(field) != expected_next.get(field) for field in comparable_fields):
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
    """`due`가 있는 미완료 task를 ISO 날짜 문자열별로 묶습니다(달력 표시 후보 — §4 규칙 8)."""
    result: dict[str, list[dict]] = {}
    for task in tasks:
        due = task.get("due")
        if not due or not is_active(task):
            continue
        result.setdefault(due, []).append(task)
    return result
