from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from search_window import SearchWindow
from todo_window import RepeatWindow


class FakeMemoStore:
    def __init__(self, memos: dict[str, str] | None = None) -> None:
        self._memos = memos or {}

    def memo_ids(self) -> list[str]:
        return sorted(self._memos)

    def load(self, memo_id: str) -> str:
        return self._memos.get(memo_id, "")


class SearchApp:
    def __init__(self) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "font_family": ""}
        self.data = {"schedules": {}}
        self.icon = QIcon()
        self.memo_store = FakeMemoStore({})
        self.search_window = None

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_search_results_open_on_item_activated(qtbot, monkeypatch) -> None:
    """UX5: itemActivated(Enter)도 itemDoubleClicked와 같은 open_result에 연결되어야 한다."""
    window = SearchWindow(SearchApp())
    qtbot.addWidget(window)
    assert window.results.count() >= 1

    calls: list[object] = []
    monkeypatch.setattr(window, "open_result", calls.append)
    window.results.itemActivated.emit(window.results.item(0))
    assert len(calls) == 1


def test_search_open_result_guard_blocks_reentry(qtbot) -> None:
    """UX5: 더블클릭+Enter가 같은 틱에서 겹쳐 발화해도 opening_result 가드가 재진입을 막는다."""
    window = SearchWindow(SearchApp())
    qtbot.addWidget(window)
    assert window.results.count() >= 1

    window.opening_result = True
    window.open_result(window.results.item(0))
    assert window.opening_result is True  # 가드가 이미 열려 있어 새 처리를 시작하지 않았다.


def test_search_window_shows_open_hint_label() -> None:
    """UX5: 결과를 여는 방법을 안내하는 힌트 라벨이 있어야 한다."""
    window = SearchWindow(SearchApp())
    assert hasattr(window, "hint_label")
    assert window.hint_label.text()


class TodoApp:
    def __init__(self) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "repeat_geometry": "480x460"}
        self.data = {"recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []}}
        self.icon = QIcon()
        self.repeat_window = None

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return


def test_todo_window_shows_empty_state_when_no_tasks(qtbot) -> None:
    """UX6: 할 일이 아예 없으면 안내 아이템을 보여준다."""
    window = RepeatWindow(TodoApp())
    qtbot.addWidget(window)

    assert window.list_widget.count() == 1
    item = window.list_widget.item(0)
    assert item.flags() == Qt.NoItemFlags
    assert "해야 할 일이 없습니다" in item.text()


def test_todo_window_shows_filter_empty_state_when_search_has_no_match(qtbot) -> None:
    """UX6: 할 일은 있지만 검색 결과가 없으면 필터 전용 안내를 보여준다."""
    app = TodoApp()
    app.data["recurring_tasks"]["daily"].append({"id": "t1", "text": "Water plants"})
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    window.search_input.setText("no-such-task-xyz")

    assert window.list_widget.count() == 1
    item = window.list_widget.item(0)
    assert item.flags() == Qt.NoItemFlags
    assert "이 조건에 맞는" in item.text()


def test_todo_add_button_has_tooltip(qtbot) -> None:
    """UX6: + 버튼에 접근성 tooltip이 있어야 한다."""
    window = RepeatWindow(TodoApp())
    qtbot.addWidget(window)

    assert window.add_button.toolTip()
