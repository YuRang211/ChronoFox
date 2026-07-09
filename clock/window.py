from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from app_constants import APP_NAME
from app_i18n import TrMixin
from app_ui import geometry_string, parse_geometry
from app_widgets import RoundedWindow

from .alarms import ClockAlarmMixin
from .layout import ClockLayoutMixin
from .styles import ClockStyleMixin
from .timer import ClockTimerMixin

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class ClockWindow(TrMixin, ClockLayoutMixin, ClockTimerMixin, ClockAlarmMixin, ClockStyleMixin, RoundedWindow):
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
        now = self.current_clock_datetime()
        stamp = now.strftime("%H:%M:%S")
        if stamp == self.last_clock_second:
            return
        self.last_clock_second = stamp
        self.current_time.setText(stamp)
        self.current_date.setText(now.strftime("%Y.%m.%d"))

    def refresh_clock(self) -> None:
        now = self.current_clock_datetime()
        self.last_clock_second = now.strftime("%H:%M:%S")
        self.current_time.setText(self.last_clock_second)
        self.current_date.setText(now.strftime("%Y.%m.%d"))

    def current_clock_datetime(self) -> datetime:
        return datetime.now()

    def apply_language(self) -> None:
        current_index = self.content_stack.currentIndex() if hasattr(self, "content_stack") else 0
        self.setWindowTitle(self.tr("clock.window.title", f"{APP_NAME} 시계"))
        self.build_ui()
        self.switch_tab(current_index)
        self.refresh_clock()

    def closeEvent(self, event) -> None:
        self.app.store.set("clock_geometry", geometry_string(self))
        self.app.save()
        self.app.clock_window = None
        super().closeEvent(event)

    @property
    def stopwatch_running(self) -> bool:
        return self.app.stopwatch_running

    @stopwatch_running.setter
    def stopwatch_running(self, value: bool) -> None:
        self.app.stopwatch_running = value

    @property
    def stopwatch_start_time(self) -> float | None:
        return self.app.stopwatch_start_time

    @stopwatch_start_time.setter
    def stopwatch_start_time(self, value: float | None) -> None:
        self.app.stopwatch_start_time = value

    @property
    def stopwatch_elapsed_before_pause(self) -> float:
        return self.app.stopwatch_elapsed_before_pause

    @stopwatch_elapsed_before_pause.setter
    def stopwatch_elapsed_before_pause(self, value: float) -> None:
        self.app.stopwatch_elapsed_before_pause = value

    @property
    def timer_running(self) -> bool:
        return self.app.timer_running

    @timer_running.setter
    def timer_running(self, value: bool) -> None:
        self.app.timer_running = value

    @property
    def timer_start_time(self) -> float | None:
        return self.app.timer_start_time

    @timer_start_time.setter
    def timer_start_time(self, value: float | None) -> None:
        self.app.timer_start_time = value

    @property
    def timer_total_duration(self) -> float:
        return self.app.timer_total_duration

    @timer_total_duration.setter
    def timer_total_duration(self, value: float) -> None:
        self.app.timer_total_duration = value

    @property
    def timer_remaining_before_pause_ms(self) -> int:
        return self.app.timer_remaining_before_pause_ms

    @timer_remaining_before_pause_ms.setter
    def timer_remaining_before_pause_ms(self, value: int) -> None:
        self.app.timer_remaining_before_pause_ms = value

    @property
    def timer_remaining_ms(self) -> int:
        return self.app.timer_remaining_ms

    @timer_remaining_ms.setter
    def timer_remaining_ms(self, value: int) -> None:
        self.app.timer_remaining_ms = value
