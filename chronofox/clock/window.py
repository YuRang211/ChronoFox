"""시계/스톱워치/타이머/알람 탭을 하나로 묶는 ClockWindow(각 Mixin을 조립한 최종 창)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from chronofox.core.app_constants import APP_NAME
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_ui import geometry_string, parse_geometry
from chronofox.ui.app_widgets import RoundedWindow

from .alarms import ClockAlarmMixin
from .layout import ClockLayoutMixin
from .styles import ClockStyleMixin
from .timer import AppTimerStateMixin, ClockTimerMixin

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp

class ClockWindow(
    TrMixin,
    ClockLayoutMixin,
    ClockTimerMixin,
    ClockAlarmMixin,
    ClockStyleMixin,
    AppTimerStateMixin,
    RoundedWindow,
):
    """현재 시각, 스톱워치, 타이머를 제공하는 작은 도구 창입니다."""

    NAV_ITEMS = [
        ("clock", "clock.tab.time", "시간", "clock"),
        ("stopwatch", "clock.tab.stopwatch", "스톱워치", "timer"),
        ("timer", "clock.tab.timer", "타이머", "hourglass"),
        ("alarm", "clock.tab.alarm", "알람", "alarm"),
    ]

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.timer_remaining_ms = 0
        self.timer_running = False
        self.stopwatch_running = False
        self.stopwatch_start_time: float | None = None
        self.stopwatch_elapsed_before_pause = 0.0
        self.timer_start_time: float | None = None
        self.timer_total_duration = 0.0
        self.timer_remaining_before_pause_ms = 0
        self.last_clock_second = ""
        self.alert_player = None
        self.alert_audio = None
        self.editing_alarm_id = ""
        self.tick = QTimer(self)
        self.tick.setInterval(50)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start()
        self.setWindowTitle(self.tr("clock.window.title", f"{APP_NAME} 시계"))
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.store.get("clock_geometry", "420x420"), (420, 420, 360, 180))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(390, 390)
        self.build_ui()

    def on_tick(self) -> None:
        """1초마다 호출되어 시계/스톱워치/타이머를 갱신합니다."""
        self.refresh_clock_if_needed()
        if self.stopwatch_running:
            self.stopwatch_label.setText(self.format_stopwatch(self.current_stopwatch_elapsed()))
        if self.timer_running:
            self.timer_remaining_ms = self.current_timer_remaining_ms()
            self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))
        else:
            if hasattr(self, "timer_label"):
                self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def refresh_clock_if_needed(self) -> None:
        """분이 바뀌었을 때만 시계 표시를 다시 그립니다."""
        now = self.current_clock_datetime()
        stamp = now.strftime("%H:%M:%S")
        if stamp == self.last_clock_second:
            return
        self.last_clock_second = stamp
        self.current_time.setText(stamp)
        self.current_date.setText(now.strftime("%Y.%m.%d"))

    def refresh_clock(self) -> None:
        """현재 시각으로 시계 표시를 다시 그립니다."""
        now = self.current_clock_datetime()
        self.last_clock_second = now.strftime("%H:%M:%S")
        self.current_time.setText(self.last_clock_second)
        self.current_date.setText(now.strftime("%Y.%m.%d"))

    def current_clock_datetime(self) -> datetime:
        """테스트에서 주입 가능한 현재 시각을 반환합니다."""
        return datetime.now()

    def apply_language(self) -> None:
        """현재 언어 설정에 맞춰 화면 텍스트를 다시 그립니다."""
        current_index = self.content_stack.currentIndex() if hasattr(self, "content_stack") else 0
        self.setWindowTitle(self.tr("clock.window.title", f"{APP_NAME} 시계"))
        self.build_ui()
        self.switch_tab(current_index)
        self.refresh_clock()

    def closeEvent(self, event) -> None:
        self.app.store.set("clock_geometry", geometry_string(self), notify_topic=None)
        self.app.save()
        self.app.clock_window = None
        super().closeEvent(event)
