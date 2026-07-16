"""S4(M5): FoxCalendarApp의 창 오케스트레이션/영속 책임 분리 (D8).

WindowManager는 ``app``(FoxCalendarApp)을 받아 일정/설정/검색/세부일정/시계/
할일/메모 창을 열고 닫고 위치를 기억하는 로직을 담당한다. 창 슬롯 속성
(``app.detail_window`` 등)은 그대로 app 위에 유지된다 — 각 창(schedule_window.py
등 8개 파일)의 ``self.app.detail_window = None`` 같은 기존 참조가 무수정으로
계속 동작해야 하기 때문이다(D8). app은 이 클래스의 메서드를 얇게 위임만 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget

from chronofox.clock import ClockWindow
from chronofox.detail_schedule import DetailScheduleWindow
from chronofox.ui.app_ui import clamp_window_position, geometry_string
from chronofox.windows.memo_window import StickyMemoWindow
from chronofox.windows.schedule_window import ScheduleWindow
from chronofox.windows.search_window import SearchWindow
from chronofox.windows.settings_window import SettingsWindow
from chronofox.windows.todo_window import RepeatWindow

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp


class WindowManager:
    """일정/설정/검색/세부일정/시계/할일/메모 창의 열기·복원·영속을 담당합니다."""

    def __init__(self, app: FoxCalendarApp) -> None:
        self.app = app

    # schedule --------------------------------------------------------
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

    # settings / search / detail / clock / repeat ----------------------
    def open_settings(self) -> None:
        """설정 창을 엽니다."""
        app = self.app
        if app.settings_window and app.settings_window.isVisible():
            app.settings_window.raise_()
            app.settings_window.activateWindow()
            return
        app.settings_window = SettingsWindow(app)
        app.settings_window.show()

    def open_search(self, query: str = "") -> None:
        """검색 창을 엽니다."""
        app = self.app
        if app.search_window and app.search_window.isVisible():
            app.search_window.raise_()
            app.search_window.activateWindow()
            if query:
                app.search_window.query.setText(query)
            return
        app.search_window = SearchWindow(app)
        if query:
            app.search_window.query.setText(query)
        app.search_window.show()

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
        """시계 창을 엽니다."""
        app = self.app
        if app.clock_window and app.clock_window.isVisible():
            app.clock_window.raise_()
            app.clock_window.activateWindow()
            return
        app.clock_window = ClockWindow(app)
        app.clock_window.show()

    def open_repeat(self) -> None:
        """반복 작업(할 일) 창을 엽니다."""
        app = self.app
        if app.repeat_window and app.repeat_window.isVisible():
            app.repeat_window.raise_()
            app.repeat_window.activateWindow()
            return
        app.repeat_window = RepeatWindow(app)
        app.repeat_window.show()

    def reopen_settings(self) -> None:
        """설정 창이 열려 있으면 다시 그려 갱신합니다."""
        app = self.app
        if app.settings_window:
            app.settings_window.close()
        self.open_settings()

    # memo --------------------------------------------------------------
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

        RESTORE1: skip_exit_flush가 True면 조기 반환한다 — 백업 복원 직후에는 디스크에
        이미 복원본이 쓰여 있고, 여기서 flush하면 열린 메모창의 옛 내용(memo_store.save는
        app_config의 _save_blocked 가드를 거치지 않고 .md 파일에 직접 쓴다)이 그 위를
        덮어써 복원을 무효화한다.
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

        RESTORE1: skip_exit_flush가 True면 조기 반환한다(사유는 persist_open_memos 참고).
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
