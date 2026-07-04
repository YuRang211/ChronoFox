from __future__ import annotations

import json
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"

# 일정창/검색창 i18n 작업으로 추가된 키. 이 창들이 다시 하드코딩으로 돌아가면 깨지도록 잠근다.
REQUIRED_KEYS = [
    "search.window.title",
    "search.title",
    "search.placeholder",
    "search.empty.prompt",
    "search.empty.none",
    "search.kind.schedule",
    "search.kind.memo",
    "search.memo.untitled",
    "search.error.open",
    "schedule.week",
    "schedule.tab.schedule",
    "schedule.tab.todo",
    "schedule.tab.plans",
    "schedule.action.add_plan",
    "plan.window.title.add",
    "plan.window.title.edit",
    "plan.heading.add",
    "plan.heading.edit",
    "plan.all_day",
    "plan.title.placeholder",
    "plan.color.label",
    "plan.description.placeholder",
    "clock.action.stop",
    "common.add",
    "common.close",
]


def load_locale(name: str) -> dict[str, str]:
    raw = json.loads((LOCALES_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in raw.items()}


def test_new_window_keys_exist_in_both_languages() -> None:
    korean = load_locale("ko")
    english = load_locale("en")
    for key in REQUIRED_KEYS:
        assert key in korean, f"ko.json에 {key} 누락"
        assert key in english, f"en.json에 {key} 누락"


def test_schedule_and_search_windows_expose_apply_language() -> None:
    from schedule_window import PlanWindow, ScheduleWindow
    from search_window import SearchWindow

    for window_class in (ScheduleWindow, PlanWindow, SearchWindow):
        assert hasattr(window_class, "apply_language"), f"{window_class.__name__}.apply_language 누락"


def test_timed_event_term_is_consistent_across_screens() -> None:
    """UX12: 시간 일정 추가 동작은 화면마다 같은 용어를 써야 한다 (일정/Event)."""
    for lang in ("ko", "en"):
        loc = load_locale(lang)
        add_terms = {loc["detail.add_event"], loc["schedule.action.add_plan"], loc["plan.heading.add"]}
        assert len(add_terms) == 1, f"{lang}: 일정 추가 용어 불일치 {add_terms}"
        # 창 제목에도 같은 용어가 들어간다.
        assert loc["plan.heading.add"] in loc["plan.window.title.add"]


def test_todo_term_is_consistent_across_screens() -> None:
    """UX12: 반복 할 일 명칭은 화면마다 같아야 한다 (해야 할 일/To Do)."""
    for lang in ("ko", "en"):
        loc = load_locale(lang)
        todo_terms = {
            loc["detail.nav.tasks"],
            loc["detail.tasks.title"],
            loc["schedule.tab.todo"],
            loc["menu.todo"],
            loc["todo.title"],
        }
        assert len(todo_terms) == 1, f"{lang}: 할 일 용어 불일치 {todo_terms}"
