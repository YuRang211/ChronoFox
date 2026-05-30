from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from math import ceil
from typing import TYPE_CHECKING
from urllib import request

from PySide6.QtCore import QTime, QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QMessageBox, QPushButton, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget

from app_constants import APP_NAME
from app_ui import add_soft_shadow, app_font, clear_layout, geometry_string, parse_geometry
from app_widgets import RoundedWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class ClockWindow(RoundedWindow):
    """현재 시각, 스톱워치, 타이머를 제공하는 작은 도구 창입니다."""

    naver_time_synced = Signal(object, str)

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.stopwatch_seconds = 0
        self.timer_remaining = 0
        self.timer_running = False
        self.stopwatch_running = False
        self.stopwatch_start_time: float | None = None
        self.stopwatch_elapsed_before_pause = 0.0
        self.timer_start_time: float | None = None
        self.timer_total_duration = 0.0
        self.timer_remaining_before_pause = 0.0
        self.last_clock_second = ""
        self.naver_offset: timedelta | None = None
        self.syncing_naver_time = False
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
        width, height, x, y = parse_geometry(app.config.get("clock_geometry", "380x340"), (380, 340, 360, 180))
        self.setGeometry(x, y, width, height)
        self.build_ui()
        self.sync_naver_time()

    def build_ui(self) -> None:
        c = self.colors
        self.styled_buttons: list[QPushButton] = []
        self.spinboxes: list[QSpinBox] = []
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(self.header("시계"))

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self.tab_style())
        add_soft_shadow(self.tabs, c, blur=14, alpha=24)
        self.tabs.addTab(self.clock_tab(), "현재")
        self.tabs.addTab(self.stopwatch_tab(), "스톱워치")
        self.tabs.addTab(self.timer_tab(), "타이머")
        self.tabs.addTab(self.alarm_tab(), "알람")
        layout.addWidget(self.tabs, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        if hasattr(self, "tabs"):
            self.tabs.setStyleSheet(self.tab_style())
        for button in getattr(self, "styled_buttons", []):
            button.setStyleSheet(self.button_style())
        for spin in getattr(self, "spinboxes", []):
            spin.setStyleSheet(self.input_style())
        if hasattr(self, "alarm_label"):
            self.alarm_label.setStyleSheet(f"color: {self.colors['muted']};")
        if hasattr(self, "time_source"):
            self.time_source.setStyleSheet(f"color: {self.colors['muted']};")
        if hasattr(self, "alarm_time"):
            self.alarm_time.setStyleSheet(self.time_input_style())
        if hasattr(self, "alarm_list"):
            self.alarm_list.setStyleSheet(self.alarm_list_style())
        self.update()

    def header(self, title_text: str) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel(title_text)
        title.setFont(app_font(15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        self.styled_buttons.append(close)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)
        return header

    def clock_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        self.current_time = QLabel("")
        self.current_time.setAlignment(Qt.AlignCenter)
        self.current_time.setFont(app_font(28, QFont.Bold))
        self.current_date = QLabel("")
        self.current_date.setAlignment(Qt.AlignCenter)
        self.current_date.setFont(app_font(11))
        self.time_source = QLabel("네이버 시간 동기화 중")
        self.time_source.setAlignment(Qt.AlignCenter)
        self.time_source.setFont(app_font(9))
        self.time_source.setStyleSheet(f"color: {self.colors['muted']};")
        layout.addWidget(self.current_time)
        layout.addWidget(self.current_date)
        layout.addWidget(self.time_source)
        self.refresh_clock()
        return widget

    def stopwatch_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        self.stopwatch_label = QLabel(self.format_stopwatch(0.0))
        self.stopwatch_label.setAlignment(Qt.AlignCenter)
        self.stopwatch_label.setFont(app_font(24, QFont.Bold))
        controls = QHBoxLayout()
        start = QPushButton("시작")
        pause = QPushButton("정지")
        reset = QPushButton("초기화")
        start.clicked.connect(self.start_stopwatch)
        pause.clicked.connect(self.pause_stopwatch)
        reset.clicked.connect(self.reset_stopwatch)
        for button in (start, pause, reset):
            button.setStyleSheet(self.button_style())
            self.styled_buttons.append(button)
            controls.addWidget(button)
        layout.addWidget(self.stopwatch_label)
        layout.addLayout(controls)
        return widget

    def timer_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setAlignment(Qt.AlignCenter)
        inputs = QHBoxLayout()
        self.timer_minutes = QSpinBox()
        self.timer_seconds = QSpinBox()
        self.timer_minutes.setRange(0, 999)
        self.timer_seconds.setRange(0, 59)
        self.timer_minutes.setSuffix(" 분")
        self.timer_seconds.setSuffix(" 초")
        for spin in (self.timer_minutes, self.timer_seconds):
            spin.setButtonSymbols(QSpinBox.NoButtons)
            spin.setFixedSize(92, 34)
            spin.setAlignment(Qt.AlignCenter)
            spin.setStyleSheet(self.input_style())
            self.spinboxes.append(spin)
            inputs.addWidget(spin)
        self.timer_label = QLabel(self.format_seconds(0))
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setFont(app_font(26, QFont.Bold))
        controls = QHBoxLayout()
        start = QPushButton("시작")
        pause = QPushButton("정지")
        reset = QPushButton("초기화")
        start.clicked.connect(self.start_timer)
        pause.clicked.connect(self.pause_timer)
        reset.clicked.connect(self.reset_timer)
        for button in (start, pause, reset):
            button.setStyleSheet(self.button_style())
            self.styled_buttons.append(button)
            controls.addWidget(button)
        layout.addLayout(inputs)
        layout.addWidget(self.timer_label)
        layout.addLayout(controls)
        return widget

    def alarm_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.alarm_label = QLabel("알람 시간을 추가해 둘 수 있습니다.")
        self.alarm_label.setAlignment(Qt.AlignCenter)
        self.alarm_label.setStyleSheet(f"color: {self.colors['muted']};")
        row = QHBoxLayout()
        self.alarm_time = QTimeEdit()
        self.alarm_time.setDisplayFormat("HH:mm")
        self.alarm_time.setTime(QTime.currentTime())
        self.alarm_time.setButtonSymbols(QTimeEdit.NoButtons)
        self.alarm_time.setStyleSheet(self.time_input_style())
        add = QPushButton("추가")
        add.setStyleSheet(self.button_style())
        self.styled_buttons.append(add)
        add.clicked.connect(self.add_alarm_stub)
        row.addWidget(self.alarm_time)
        row.addWidget(add)
        self.alarm_list = QListWidget()
        self.alarm_list.setStyleSheet(self.alarm_list_style())
        layout.addWidget(self.alarm_label)
        layout.addLayout(row)
        layout.addWidget(self.alarm_list, 1)
        return widget

    def on_tick(self) -> None:
        self.refresh_clock_if_needed()
        if self.stopwatch_running:
            self.stopwatch_label.setText(self.format_stopwatch(self.current_stopwatch_elapsed()))
        if self.timer_running:
            self.timer_remaining = self.current_timer_remaining()
            self.timer_label.setText(self.format_seconds(self.timer_remaining))
            if self.timer_remaining == 0:
                self.timer_running = False
                self.timer_start_time = None
                self.timer_remaining_before_pause = 0
                self.raise_()
                QMessageBox.information(self, APP_NAME, "타이머가 끝났습니다.")

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

    def start_stopwatch(self) -> None:
        if self.stopwatch_running:
            return
        self.stopwatch_start_time = time.monotonic()
        self.stopwatch_running = True

    def pause_stopwatch(self) -> None:
        if self.stopwatch_running:
            self.stopwatch_elapsed_before_pause = self.current_stopwatch_elapsed()
            self.stopwatch_start_time = None
        self.stopwatch_running = False

    def reset_stopwatch(self) -> None:
        self.stopwatch_running = False
        self.stopwatch_start_time = None
        self.stopwatch_elapsed_before_pause = 0.0
        self.stopwatch_seconds = 0
        self.stopwatch_label.setText(self.format_stopwatch(0.0))

    def start_timer(self) -> None:
        if self.timer_running:
            return
        if self.timer_remaining_before_pause > 0:
            self.timer_total_duration = self.timer_remaining_before_pause
        else:
            self.timer_total_duration = self.timer_minutes.value() * 60 + self.timer_seconds.value()
        self.timer_remaining = int(round(self.timer_total_duration))
        self.timer_label.setText(self.format_seconds(self.timer_remaining))
        self.timer_running = self.timer_total_duration > 0
        self.timer_start_time = time.monotonic() if self.timer_running else None
        self.timer_remaining_before_pause = 0.0

    def pause_timer(self) -> None:
        if self.timer_running:
            self.timer_remaining_before_pause = float(self.current_timer_remaining())
            self.timer_start_time = None
        self.timer_running = False

    def reset_timer(self) -> None:
        self.timer_running = False
        self.timer_start_time = None
        self.timer_total_duration = 0.0
        self.timer_remaining_before_pause = 0.0
        self.timer_remaining = self.timer_minutes.value() * 60 + self.timer_seconds.value()
        self.timer_label.setText(self.format_seconds(self.timer_remaining))

    def current_stopwatch_seconds(self) -> int:
        elapsed = self.current_stopwatch_elapsed()
        self.stopwatch_seconds = int(elapsed)
        return self.stopwatch_seconds

    def current_stopwatch_elapsed(self) -> float:
        elapsed = self.stopwatch_elapsed_before_pause
        if self.stopwatch_running and self.stopwatch_start_time is not None:
            elapsed += time.monotonic() - self.stopwatch_start_time
        return elapsed

    def current_timer_remaining(self) -> int:
        if not self.timer_running or self.timer_start_time is None:
            return max(0, int(ceil(self.timer_remaining_before_pause or self.timer_remaining)))
        elapsed = time.monotonic() - self.timer_start_time
        return max(0, int(ceil(self.timer_total_duration - elapsed)))

    def format_seconds(self, total: int) -> str:
        hours = total // 3600
        minutes = (total % 3600) // 60
        seconds = total % 60
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def format_stopwatch(self, elapsed: float) -> str:
        total_ms = max(0, int(elapsed * 1000))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) // 1000
        millis = total_ms % 1000
        if hours:
            return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"
        return f"{minutes:02}:{seconds:02}.{millis:03}"

    def add_alarm_stub(self) -> None:
        alarm_text = self.alarm_time.time().toString("HH:mm")
        self.alarm_list.addItem(f"{alarm_text}  ·  준비 중")

    def tab_style(self) -> str:
        c = self.colors
        return (
            f"QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 9px; background: {c['panel']}; }}"
            f"QTabBar::tab {{ color: {c['muted']}; padding: 7px 12px; border: 1px solid transparent; border-radius: 7px; }}"
            f"QTabBar::tab:selected {{ color: {c['text']}; background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 7px; }}"
        )

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QSpinBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QSpinBox:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
        )

    def time_input_style(self) -> str:
        c = self.colors
        return (
            f"QTimeEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QTimeEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
        )

    def alarm_list_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 6px; outline: none; }}"
            f"QListWidget::item {{ padding: 7px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {c['panel2']}; }}"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def closeEvent(self, event) -> None:
        self.app.config["clock_geometry"] = geometry_string(self)
        self.app.save()
        self.app.clock_window = None
        super().closeEvent(event)

