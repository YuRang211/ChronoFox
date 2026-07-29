"""검색 로직 (Qt-free 순수 모듈, R4-2).

`chronofox.windows.search_window.SearchWindow`(기존 검색 창)와 허브
(`chronofox.detail_schedule`)의 상단 검색바가 이 모듈의 함수를 공유한다. 매칭 규칙을
두 곳에 따로 구현하지 않는다 — 여기서 바뀌면 두 화면 모두 같이 바뀐다.

검색 대상 네 가지:
- 노트(`store.schedules()`, ``{ISO날짜: 문자열}``) — 기존 SearchWindow의 "schedule" 결과.
- 메모(memo_store 기반, 호출부가 ``{"id", "title", "content"}`` 리스트로 넘긴다).
- 할 일(``TaskService.tasks()``/``task_logic`` 평면 모델, ``text``/``notes`` 필드).
- 일정(``store.plans()``, ``title``/``start``/``end``/``kind`` 필드).

각 결과는 :class:`SearchResult` (``kind``/``label``/``preview``/``target``)로 통일한다.
``target``은 그대로 허브의 ``show_section(section_kind, target)`` 두 번째 인자로 먹일 수
있는 형태다(H-D8): 노트·일정은 ISO 날짜 문자열, 할 일은 task id, 메모는 memo id.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SearchResult:
    """검색 결과 한 건. ``target``은 결과 kind에 대응하는 허브 섹션의 딥링크 대상이다."""

    kind: str  # "note" | "plan" | "task" | "memo"
    label: str
    preview: str
    target: str


def preview_text(content: str) -> str:
    """검색 결과에 보여줄 미리보기 문자열을 만듭니다(첫 비어있지 않은 줄)."""
    return next((line.strip() for line in content.splitlines() if line.strip()), "")


def _normalize(query: str) -> str:
    return query.strip().lower()


def search_notes(query: str, schedules: dict[str, str]) -> list[SearchResult]:
    """날짜별 하루 메모(``store.schedules()``)에서 검색합니다.

    기존 SearchWindow 동작 보존: 본문·ISO 날짜 문자열(``YYYY-MM-DD``)·``%Y.%m.%d`` 표기
    세 가지 중 하나라도 질의어를 포함하면 매칭한다. 날짜순으로 정렬한다.
    """
    text = _normalize(query)
    if not text:
        return []
    results: list[SearchResult] = []
    for day_text, content in sorted(schedules.items()):
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        formatted = day.strftime("%Y.%m.%d")
        if text in content.lower() or text in day_text or text in formatted:
            results.append(SearchResult("note", formatted, preview_text(content), day.isoformat()))
    return results


def search_memos(query: str, memos: Iterable[dict]) -> list[SearchResult]:
    """메모 목록(``[{"id", "title", "content"}, ...]``)에서 검색합니다.

    제목의 "제목 없는 메모" 같은 표시용 대체 문구는 호출부(UI, locale 보유)의 몫이다 —
    여기서는 원문 그대로(빈 문자열 가능)를 ``label``에 담는다.
    """
    text = _normalize(query)
    if not text:
        return []
    results: list[SearchResult] = []
    for memo in memos:
        memo_id = str(memo.get("id", ""))
        title = str(memo.get("title", "")).strip()
        content = str(memo.get("content", ""))
        haystack = f"{title}\n{content}".lower()
        if text not in haystack:
            continue
        results.append(SearchResult("memo", title, preview_text(content), memo_id))
    return results


def search_tasks(query: str, tasks: Iterable[dict]) -> list[SearchResult]:
    """할 일 목록(todo-v3 평면 모델, ``TaskService.tasks()``)에서 검색합니다.

    제목(``text``)과 메모(``notes``)를 함께 본다.
    """
    text = _normalize(query)
    if not text:
        return []
    results: list[SearchResult] = []
    for task in tasks:
        task_id = str(task.get("id", ""))
        title = str(task.get("text", "")).strip()
        notes = str(task.get("notes", ""))
        haystack = f"{title}\n{notes}".lower()
        if text not in haystack:
            continue
        results.append(SearchResult("task", title, preview_text(notes), task_id))
    return results


def search_plans(query: str, plans: Iterable[dict]) -> list[SearchResult]:
    """일정(캘린더 이벤트, ``store.plans()``)에서 검색합니다.

    제목·시작일(ISO/``%Y.%m.%d``) 어느 쪽이든 질의어를 포함하면 매칭한다(노트 검색과
    동일한 날짜 매칭 관용구). ``target``은 이벤트 시작 날짜(ISO)다 — 허브의 "주간"
    섹션은 날짜를 target으로 받는다(H-D8).
    """
    text = _normalize(query)
    if not text:
        return []
    results: list[SearchResult] = []
    for plan in plans:
        title = str(plan.get("title", "")).strip()
        start_text = str(plan.get("start", ""))
        day_iso = start_text[:10]
        try:
            day = date.fromisoformat(day_iso)
        except ValueError:
            day = None
        formatted = day.strftime("%Y.%m.%d") if day else ""
        haystack = f"{title} {day_iso} {formatted}".lower()
        if text not in haystack:
            continue
        if day is None:
            continue
        all_day = plan.get("kind") == "long"
        time_text = "" if all_day else start_text[11:16]
        preview = formatted if not time_text else f"{formatted} {time_text}"
        results.append(SearchResult("plan", title, preview, day.isoformat()))
    return results


def search_all(
    query: str,
    *,
    schedules: dict[str, str] | None = None,
    memos: Iterable[dict] | None = None,
    tasks: Iterable[dict] | None = None,
    plans: Iterable[dict] | None = None,
) -> list[SearchResult]:
    """네 가지 검색 대상을 한 번에 검색합니다(노트 → 일정 → 할 일 → 메모 순서).

    각 인자는 생략(``None``)하면 해당 종류를 건너뛴다 — 호출부가 가진 데이터만 넘기면
    된다(SearchWindow는 노트·메모만, 허브는 네 가지 전부).
    """
    if not query.strip():
        return []
    results: list[SearchResult] = []
    if schedules is not None:
        results.extend(search_notes(query, schedules))
    if plans is not None:
        results.extend(search_plans(query, plans))
    if tasks is not None:
        results.extend(search_tasks(query, tasks))
    if memos is not None:
        results.extend(search_memos(query, memos))
    return results
