from __future__ import annotations

from PySide6.QtCore import Qt

from search_window import SearchWindow
from todo_window import RepeatWindow


def test_search_results_open_on_item_activated(qtbot, monkeypatch, fake_app) -> None:
    """UX5: itemActivated(Enter)도 itemDoubleClicked와 같은 open_result에 연결되어야 한다."""
    window = SearchWindow(fake_app())
    qtbot.addWidget(window)
    assert window.results.count() >= 1

    calls: list[object] = []
    monkeypatch.setattr(window, "open_result", calls.append)
    window.results.itemActivated.emit(window.results.item(0))
    assert len(calls) == 1


def test_search_open_result_guard_blocks_reentry(qtbot, fake_app) -> None:
    """UX5: 더블클릭+Enter가 같은 틱에서 겹쳐 발화해도 opening_result 가드가 재진입을 막는다."""
    window = SearchWindow(fake_app())
    qtbot.addWidget(window)
    assert window.results.count() >= 1

    window.opening_result = True
    window.open_result(window.results.item(0))
    assert window.opening_result is True  # 가드가 이미 열려 있어 새 처리를 시작하지 않았다.


def test_search_window_shows_open_hint_label(fake_app) -> None:
    """UX5: 결과를 여는 방법을 안내하는 힌트 라벨이 있어야 한다."""
    window = SearchWindow(fake_app())
    assert hasattr(window, "hint_label")
    assert window.hint_label.text()


def test_todo_window_shows_empty_state_when_no_tasks(qtbot, fake_app) -> None:
    """UX6: 할 일이 아예 없으면 안내 아이템을 보여준다."""
    window = RepeatWindow(fake_app(repeat_geometry="480x460"))
    qtbot.addWidget(window)

    assert window.list_widget.count() == 1
    item = window.list_widget.item(0)
    assert item.flags() == Qt.NoItemFlags
    assert "해야 할 일이 없습니다" in item.text()


def test_todo_window_shows_filter_empty_state_when_search_has_no_match(qtbot, fake_app) -> None:
    """UX6: 할 일은 있지만 검색 결과가 없으면 필터 전용 안내를 보여준다."""
    app = fake_app(repeat_geometry="480x460")
    app.data["recurring_tasks"]["daily"].append({"id": "t1", "text": "Water plants"})
    window = RepeatWindow(app)
    qtbot.addWidget(window)

    window.search_input.setText("no-such-task-xyz")
    window.search_timer.timeout.emit()  # PERF1: 검색은 디바운스되므로 타이머 발화를 수동 트리거한다.

    assert window.list_widget.count() == 1
    item = window.list_widget.item(0)
    assert item.flags() == Qt.NoItemFlags
    assert "이 조건에 맞는" in item.text()


def test_todo_add_button_has_tooltip(qtbot, fake_app) -> None:
    """UX6: + 버튼에 접근성 tooltip이 있어야 한다."""
    window = RepeatWindow(fake_app(repeat_geometry="480x460"))
    qtbot.addWidget(window)

    assert window.add_button.toolTip()


def test_todo_search_input_debounces_row_rebuild(qtbot, fake_app) -> None:
    """PERF1: 검색 textChanged는 동기로 refresh_all을 부르지 않고 디바운스 타이머를 시작하며,
    타이머가 발화하면 그때 행을 재구성한다. 프로그램적 refresh_all 직접 호출은 즉시 반영 유지."""
    from app_constants import SEARCH_DEBOUNCE_MS

    app = fake_app(repeat_geometry="480x460")
    app.data["recurring_tasks"]["daily"].append({"id": "t1", "text": "Water plants"})
    window = RepeatWindow(app)
    qtbot.addWidget(window)
    assert window.list_widget.count() == 1
    assert window.list_widget.itemWidget(window.list_widget.item(0)) is not None  # 실제 태스크 행

    window.search_input.setText("no-such-task-xyz")

    # 동기 재구성 없음: 행은 그대로 남아 있고 타이머만 대기 중이다.
    assert window.list_widget.itemWidget(window.list_widget.item(0)) is not None
    assert window.search_timer.isActive()
    assert window.search_timer.isSingleShot()
    assert window.search_timer.interval() == SEARCH_DEBOUNCE_MS

    window.search_timer.timeout.emit()  # 타이머 발화를 수동 트리거

    assert not window.search_timer.isActive()
    item = window.list_widget.item(0)
    assert item.flags() == Qt.NoItemFlags  # 이제 필터 빈 상태 안내 아이템으로 교체됨
    assert "이 조건에 맞는" in item.text()
