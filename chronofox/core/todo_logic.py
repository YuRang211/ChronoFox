"""반복 할 일(주기/스트릭/정렬/단계) 계산을 담당하는 Qt-free 순수 함수 모음.

todo-ux-v2 Phase1 D3(메타라인)·D4(그룹·정렬)와 Phase2 D7(단계 주기 리셋)의 핵심
계산을 여기 모아, Qt 위젯을 띄우지 않고도 단위 테스트로 주기 경계(월/연 롤오버 등)를
검증할 수 있게 한다. `todo_window.RepeatWindow`와 `detail_schedule/tasks_section.py`가
이 모듈을 공유해서 쓴다(공통 note — 행 렌더링 전체 통합 대신 계산 로직을 공유).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from datetime import date, timedelta

PERIODS = ("daily", "weekly", "monthly", "yearly")


def period_key(period: str, day: date) -> str:
    """주어진 날짜 기준 주기(daily/weekly/monthly/yearly)의 키를 반환합니다."""
    if period == "daily":
        return day.isoformat()
    if period == "weekly":
        year, week, _weekday = day.isocalendar()
        return f"{year}-W{week:02}"
    if period == "monthly":
        return day.strftime("%Y-%m")
    return day.strftime("%Y")


def previous_period_key(period: str, key: str) -> str:
    """주어진 주기 키의 바로 이전 주기 키를 계산합니다(스트릭 역산용).

    키 형식이 잘못돼 파싱할 수 없으면 빈 문자열을 반환합니다(호출부는
    빈 문자열이 counted_keys에 없다고 보고 안전하게 스트릭 계산을 멈춥니다).
    """
    if period == "daily":
        try:
            day = date.fromisoformat(key)
        except ValueError:
            return ""
        return (day - timedelta(days=1)).isoformat()
    if period == "weekly":
        try:
            year_str, week_str = key.split("-W")
            monday = date.fromisocalendar(int(year_str), int(week_str), 1)
        except (ValueError, IndexError):
            return ""
        return period_key("weekly", monday - timedelta(days=7))
    if period == "monthly":
        try:
            year_str, month_str = key.split("-")
            year, month = int(year_str), int(month_str)
        except (ValueError, IndexError):
            return ""
        if month <= 1:
            return f"{year - 1}-12"
        return f"{year}-{month - 1:02}"
    # yearly
    try:
        year = int(key)
    except ValueError:
        return ""
    return str(year - 1)


def compute_streak(period: str, counted_keys: Iterable[str], current_key: str) -> int:
    """counted_keys를 이용해 현재(미완료면 직전) 주기부터 역방향 연속 완료 수를 셉니다."""
    counted = set(counted_keys)
    anchor = current_key if current_key in counted else previous_period_key(period, current_key)
    if not anchor or anchor not in counted:
        return 0
    streak = 0
    key = anchor
    seen: set[str] = set()
    while key and key in counted and key not in seen:
        seen.add(key)
        streak += 1
        key = previous_period_key(period, key)
    return streak


def days_until(due_iso: str, today: date) -> int | None:
    """마감일(ISO 문자열)까지 남은 일수를 반환합니다. 지났으면 음수, 없거나 잘못된 값이면 None."""
    if not due_iso:
        return None
    try:
        due_date = date.fromisoformat(due_iso)
    except ValueError:
        return None
    return (due_date - today).days


def classify_and_sort(
    rows: Sequence[tuple[str, dict]],
    is_done: Callable[[str, dict], bool],
) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    """작업 목록을 미완료/완료로 나누고, 각각 중요 → order(없으면 안정 정렬) → created 순으로 정렬합니다(D4)."""
    pending: list[tuple[str, dict]] = []
    done: list[tuple[str, dict]] = []
    for period, task in rows:
        (done if is_done(period, task) else pending).append((period, task))

    def sort_key(item: tuple[str, dict]) -> tuple[int, float, str]:
        _period, task = item
        important_rank = 0 if task.get("important") else 1
        order = task.get("order")
        order_rank = float(order) if isinstance(order, int) and not isinstance(order, bool) else float("inf")
        created = str(task.get("created", ""))
        return (important_rank, order_rank, created)

    pending.sort(key=sort_key)
    done.sort(key=sort_key)
    return pending, done


# ---------------------------------------------------------------------------
# Phase2 D7 — 단계(steps)
# ---------------------------------------------------------------------------


def normalize_step(step: dict) -> dict:
    """단계(step) dict에 누락된 기본 필드를 채웁니다(D7 — additive, schema_version 무변경)."""
    step.setdefault("id", "")
    step.setdefault("text", "")
    step.setdefault("done", False)
    return step


def steps_progress(steps: Sequence[dict]) -> tuple[int, int]:
    """(완료된 단계 수, 전체 단계 수)를 반환합니다."""
    total = len(steps)
    done = sum(1 for step in steps if step.get("done"))
    return done, total


def reset_steps_for_period(task: dict, current_key: str) -> bool:
    """반복 할 일의 단계 완료 상태를 주기가 바뀌면 리셋합니다(D7 제품 결정).

    `task["steps_period"]`에 마지막으로 단계를 갱신한 주기 키를 저장해두고, 현재
    주기와 다르면 모든 단계의 done을 False로 되돌린 뒤 키를 갱신한다. steps가
    비어 있으면(아직 한 번도 단계를 추가한 적 없으면) 아무 것도 하지 않는다 —
    단계를 쓰지 않는 다수 작업에 불필요한 필드를 추가하지 않기 위해서다.
    무언가 바뀌었으면(리셋 또는 최초 키 기록) True를 반환한다(호출부의 저장 트리거용).
    """
    steps = task.get("steps")
    if not steps:
        return False
    if task.get("steps_period") == current_key:
        return False
    for step in steps:
        if step.get("done"):
            step["done"] = False
    task["steps_period"] = current_key
    return True


def last_completed_key(counted_keys: Iterable[str]) -> str:
    """counted_keys 중 가장 최근 주기 키를 반환합니다(없으면 빈 문자열).

    daily/weekly/monthly/yearly 키 형식은 모두 사전식 정렬이 시간 순 정렬과
    일치하므로(예: "2026-07-12", "2026-W28", "2026-07", "2026") 단순 max()로 구한다.
    """
    keys = [str(key) for key in counted_keys if key]
    return max(keys) if keys else ""
