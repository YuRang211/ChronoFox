from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING
from urllib import request

from PySide6.QtCore import QTimer, Signal

from app_constants import APP_NAME
from app_ui import geometry_string, parse_geometry
from app_widgets import RoundedWindow
from .alarms import ClockAlarmMixin
from .layout import ClockLayoutMixin
from .styles import ClockStyleMixin
from .timer import ClockTimerMixin

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class ClockWindow(ClockLayoutMixin, ClockTimerMixin, ClockAlarmMixin, ClockStyleMixin, RoundedWindow):
    """현재 시각, 스톱워치, 타이머를 제공하는 작은 도구 창입니다."""

    naver_time_synced = Signal(object, str)
    NAV_ITEMS = [
        ("clock", "시간", "clock"),
        ("stopwatch", "스톱워치", "timer"),
        ("timer", "타이머", "hourglass"),
        ("alarm", "알람", "alarm"),
    ]

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.stopwatch_seconds = 0
        self.timer_remaining_ms = 0
        self.timer_running = False
        self.stopwatch_running = False
        self.stopwatch_start_time: float | None = None
        self.stopwatch_elapsed_before_pause = 0.0
        self.timer_start_time: float | None = None
        self.timer_total_duration = 0.0
        self.timer_remaining_before_pause_ms = 0
        self.last_clock_second = ""
        self.last_alarm_check_second = ""
        self.naver_offset: timedelta | None = None
        self.syncing_naver_time = False
        self.alert_player = None
        self.alert_audio = None
        self.editing_alarm_id = ""
        self.naver_time_synced.connect(self.set_naver_time_offset)
        self.tick = QTimer(self)
        self.tick.setInterval(50)
        self.tick.timeout.connect(self.on_tick)
        self.tick.start()
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(60 * 1000)
        self.sync_timer.timeout.connect(self.sync_naver_time)
        self.sync_timer.start()
        self.setWindowTitle(f"{APP_NAME} 시계")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("clock_geometry", "420x420"), (420, 420, 360, 180))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(390, 390)
        self.build_ui()
        self.sync_naver_time()

    def on_tick(self) -> None:
        self.refresh_clock_if_needed()
        self.check_alarms()
        if self.stopwatch_running:
            self.stopwatch_label.setText(self.format_stopwatch(self.current_stopwatch_elapsed()))
        if self.timer_running:
            self.timer_remaining_ms = self.current_timer_remaining_ms()
            self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))
            if self.timer_remaining_ms == 0:
                self.timer_running = False
                self.timer_start_time = None
                self.timer_remaining_before_pause_ms = 0
                self.show_alert("타이머가 끝났습니다.")

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
        if self.naver_offset is None:
            return datetime.now()
        return (datetime.now(timezone.utc) + self.naver_offset).astimezone()

    def sync_naver_time(self) -> None:
        if self.syncing_naver_time:
            return
        self.syncing_naver_time = True
        threading.Thread(target=self.fetch_naver_time, daemon=True).start()

    def fetch_naver_time(self) -> None:
        offset: timedelta | None = None
        status = "PC 시간"
        try:
            req = request.Request("https://www.naver.com/", method="HEAD", headers={"User-Agent": "FoxCalendar/1.0"})
            sent_at = datetime.now(timezone.utc)
            with request.urlopen(req, timeout=3) as response:
                date_header = response.headers.get("Date")
            received_at = datetime.now(timezone.utc)
            if date_header:
                server_time = parsedate_to_datetime(date_header)
                if server_time.tzinfo is None:
                    server_time = server_time.replace(tzinfo=timezone.utc)
                midpoint = sent_at + (received_at - sent_at) / 2
                offset = server_time.astimezone(timezone.utc) - midpoint + timedelta(milliseconds=500)
                status = "네이버 시간"
        except Exception:
            offset = None
            status = "PC 시간 (동기화 실패)"
        self.naver_time_synced.emit(offset, status)

    def set_naver_time_offset(self, offset: timedelta | None, status: str) -> None:
        self.naver_offset = offset
        self.syncing_naver_time = False
        if hasattr(self, "time_source"):
            self.time_source.setText(status)
        self.refresh_clock()

    def closeEvent(self, event) -> None:
        self.app.config["clock_geometry"] = geometry_string(self)
        self.app.save()
        self.app.clock_window = None
        super().closeEvent(event)
