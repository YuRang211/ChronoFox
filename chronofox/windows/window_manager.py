"""FoxCalendarApp의 창 생성, 탐색, 영속화를 관리합니다.

창 슬롯 속성은 기존 호출 계약을 위해 app에 유지하고 생성·탐색·저장만 위임받습니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from chronofox.detail_schedule import DetailScheduleWindow
from chronofox.ui.app_ui import clamp_window_position, geometry_string
from chronofox.windows.memo_window import StickyMemoWindow
from chronofox.windows.quick_input_window import QuickInputWindow
from chronofox.windows.schedule_window import ScheduleWindow

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp


# 시계 도구 탭 인덱스를 알람 섹션의 보조 영역 target으로 변환한다.
CLOCK_TAB_AUX_TARGETS: dict[int, str | None] = {0: "aux:clock", 1: "aux:stopwatch", 2: "aux:timer", 3: None}


class WindowManager:
    """일정/설정/검색/세부일정/시계/할일/메모 창의 열기·복원·영속을 담당합니다."""

    def __init__(self, app: FoxCalendarApp) -> None:
        self.app = app

    # 일정
    def open_schedule_near(self, day) -> None:
        """가장 가까운 일정 창을 찾아 엽니다."""
        app = self.app
        app.selected_day = day
        app.render_calendar()
        width, height = 430, 360
        sender = app.sender()
        if isinstance(sender, QWidget):
            point = sender.mapToGlobal(QPoint(12, 28))
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            x, y = clamp_window_position(width, height, point.x(), point.y(), screen.availableGeometry())
            geometry = f"{width}x{height}+{x}+{y}"
        else:
            geometry = None
        self.open_schedule(day, geometry)

    def open_schedule(self, day, geometry: str | None = None) -> None:
        """특정 날짜의 일정 창을 엽니다."""
        app = self.app
        key = day.isoformat()
        if key in app.schedule_windows and app.schedule_windows[key].isVisible():
            app.schedule_windows[key].raise_()
            app.schedule_windows[key].activateWindow()
            return
        if geometry is None:
            width, height = 430, 360
            anchor = app.geometry()
            screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
            x, y = clamp_window_position(width, height, anchor.x() + 32, anchor.y() + 64, screen.availableGeometry())
            geometry = f"{width}x{height}+{x}+{y}"
        window = ScheduleWindow(app, day, geometry)
        app.schedule_windows[key] = window
        window.show()

    # 허브 진입점
    def open_settings(self, page: str | None = None) -> None:
        """설정 창 대신 허브를 설정 섹션으로 엽니다.

        ``page``가 있으면 설정 탭 target으로 변환합니다.

        `isinstance` 가드: `QAction.triggered`/`QPushButton.clicked`에 이 메서드를
        람다 없이 직접 connect하면 Qt가 클릭 시의 `checked`(bool)를 이 자리에 채워
        넣는다 — 트레이·헤더 메뉴의 "설정" 항목이 그 패턴이라(체크 불가능한 액션이라
        항상 `False`), 문자열이 아닌 값은 target 계산에서 무시한다."""
        self.open_detail_schedule()
        target = f"page:{page}" if isinstance(page, str) and page else None
        self.app.detail_window.show_section("settings", target)

    def open_search(self, query: str = "") -> None:
        """검색 창 대신 허브 상단 상시 검색바로 리다이렉트합니다.

        검색은 섹션이 아니라 상시 표시 영역이므로 허브를 열고 입력창에 직접 포커스합니다."""
        self.open_detail_schedule()
        hub = self.app.detail_window
        hub.raise_()
        hub.activateWindow()
        if query:
            hub.search_input.setText(query)
        hub.search_input.setFocus()

    def open_detail_schedule(self) -> None:
        """세부 일정(월간/작업/보관함) 창을 엽니다."""
        app = self.app
        if app.detail_window and app.detail_window.isVisible():
            app.detail_window.raise_()
            app.detail_window.activateWindow()
            return
        app.detail_window = DetailScheduleWindow(app)
        app.detail_window.show()

    def open_clock(self) -> None:
        """시계 창 대신 허브를 알람 섹션으로 엽니다.

        기존 진입점 호환을 유지하면서 허브의 알람 섹션으로 연결합니다."""
        self.open_detail_schedule()
        self.app.detail_window.show_section("alarms")

    def open_clock_tab(self, index: int) -> None:
        """시계 도구 탭 인덱스를 허브 알람 섹션의 보조 영역으로 연결합니다."""
        target = CLOCK_TAB_AUX_TARGETS.get(index)
        self.open_detail_schedule()
        self.app.detail_window.show_section("alarms", target)

    def open_repeat(self) -> None:
        """할 일 진입점을 허브의 tasks 섹션으로 연결합니다."""
        self.open_detail_schedule()
        self.app.detail_window.show_section("tasks")

    def open_quick_input(self) -> None:
        """빠른 입력창을 열고 이미 표시 중이면 재사용합니다.
        아니면 매번 새로 만든다 — 다른 창들(search/settings/repeat 등)과 같은 관례다."""
        app = self.app
        if app.quick_input_window and app.quick_input_window.isVisible():
            app.quick_input_window.raise_()
            app.quick_input_window.activateWindow()
            return
        app.quick_input_window = QuickInputWindow(app)
        app.quick_input_window.show()
        app.quick_input_window.raise_()
        app.quick_input_window.activateWindow()

    def reopen_settings(self) -> None:
        """설정 화면(허브 설정 섹션)을 다시 그려 최신 상태로 갱신합니다.

        허브 창을 닫지 않고 현재 자리에서 다시 구성합니다."""
        self.open_settings()
        if self.app.detail_window is not None:
            self.app.detail_window.build_ui()

    # 메모
    def create_memo(self) -> None:
        """새 메모 창을 만들고 엽니다."""
        memo_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        self.open_memo(memo_id)

    def open_memo(self, memo_id: str, geometry: str | None = None) -> None:
        """기존 메모 창을 엽니다."""
        app = self.app
        if memo_id in app.memo_windows and app.memo_windows[memo_id].isVisible():
            app.memo_windows[memo_id].raise_()
            return
        window = StickyMemoWindow(app, memo_id, geometry)
        app.memo_windows[memo_id] = window
        if app.memo_has_content(memo_id):
            self.remember_open_memo(memo_id, geometry_string(window))
        window.show()
        window.raise_()

    def restore_open_memos(self) -> None:
        """복원 목록에 남아 있고 내용이 있는 메모창만 다시 엽니다."""
        app = self.app
        for memo_id, geometry in list(app.store.get("open_memos", {}).items()):
            if app.memo_has_content(memo_id):
                self.open_memo(memo_id, geometry)
            else:
                self.forget_open_memo(memo_id)

    def delete_memo(self, memo_id: str) -> None:
        """열린 창의 종료 저장으로 되살아나지 않도록 메모와 메타데이터를 삭제합니다."""
        app = self.app
        window = app.memo_windows.get(memo_id)
        if window is not None:
            window.discard_and_close()
        app.memo_store.delete(memo_id)

        titles = dict(app.store.get("memo_titles", {}))
        titles.pop(memo_id, None)
        app.store.set("memo_titles", titles)
        open_memos = dict(app.store.get("open_memos", {}))
        open_memos.pop(memo_id, None)
        app.store.set("open_memos", open_memos)
        app.save()

    def remember_open_memo(self, memo_id: str, geometry: str) -> None:
        """열린 메모 창을 다음 실행 때 복원할 목록에 기록합니다."""
        app = self.app
        app.store.get("open_memos", {})[memo_id] = geometry
        app.save()

    def forget_open_memo(self, memo_id: str) -> None:
        """닫힌 메모 창을 복원 목록에서 제거합니다."""
        app = self.app
        app.store.get("open_memos", {}).pop(memo_id, None)
        app.save()

    def persist_open_memos(self) -> None:
        """종료 직전에 열린 메모의 내용과 위치를 한 번 더 저장합니다.

        복원 직후에는 열린 메모의 옛 내용이 복원본을 덮지 않도록 flush를 건너뜁니다.
        """
        app = self.app
        if getattr(app, "skip_exit_flush", False):
            return
        for _memo_id, window in list(app.memo_windows.items()):
            if window.isVisible():
                window.save_now()
        app.save()

    def persist_open_windows(self) -> None:
        """백업, 내보내기, 종료 전에 열린 편집창의 대기 중인 저장을 모두 반영합니다.

        복원 직후에는 메모와 일정창의 옛 상태가 복원본을 덮지 않도록 건너뜁니다.
        """
        app = self.app
        if getattr(app, "skip_exit_flush", False):
            return
        for _memo_id, window in list(app.memo_windows.items()):
            if window.isVisible():
                window.save_now()
        for _day_text, window in list(app.schedule_windows.items()):
            if window.isVisible():
                window.save_now()
        app.save()

    def recall_hidden_memos(self) -> None:
        """복원 대상 메모를 달력 근처로 다시 모아 화면 밖 메모를 회수합니다."""
        app = self.app
        active_ids = [
            memo_id
            for memo_id in app.store.get("open_memos", {})
            if app.memo_has_content(memo_id)
        ]
        if not active_ids:
            return

        anchor = app.geometry()
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        base_x, base_y = clamp_window_position(280, 260, anchor.x() + 24, anchor.y() + 54, available, margin=12)

        for index, memo_id in enumerate(active_ids):
            window = app.memo_windows.get(memo_id)
            if window is None or not window.isVisible():
                self.open_memo(memo_id, app.store.get("open_memos", {}).get(memo_id))
                window = app.memo_windows.get(memo_id)
            if window is None:
                continue

            offset = index * 28
            x, y = clamp_window_position(window.width(), window.height(), base_x + offset, base_y + offset, available, margin=12)
            window.move(x, y)
            window.show()
            window.raise_()
            window.activateWindow()
            self.remember_open_memo(memo_id, geometry_string(window))
