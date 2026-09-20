"""앱 소유 시간 상태를 표시하고 조작하는 단일 시계 도구 창."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QCheckBox, QHBoxLayout, QLabel, QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget

from chronofox.clock.styles import ClockStyleMixin
from chronofox.clock.timer import AppTimerStateMixin, ClockTimerMixin
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_theme import resolve_theme
from chronofox.ui.app_ui import app_font, clamp_window_position, geometry_string, parse_geometry
from chronofox.ui.app_widgets import RoundedWindow


class ClockToolsWindow(TrMixin, ClockTimerMixin, AppTimerStateMixin, ClockStyleMixin, RoundedWindow):
    TAB_KEYS = ("timer", "stopwatch", "clock")

    def __init__(self, app):
        self.app = app
        super().__init__(resolve_theme(app.store))
        self.setWindowIcon(app.icon)
        self.setMinimumSize(340, 280)
        self.resize(380, 320)
        self._input_duration = None
        self.display_timer = QTimer(self)
        self.display_timer.setInterval(200)
        self.display_timer.timeout.connect(self.refresh_display)
        self.build_ui()
        self.select_tab(app.store.get("clock_tools_tab", "timer"))
        geometry = app.store.get("clock_tools_geometry", "380x320+160+160")
        w, h, x, y = parse_geometry(geometry, (380, 320, 160, 160))
        self.resize(max(w, 340), max(h, 280))
        screen = QApplication.screenAt(QPoint(x, y)) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(self.width(), available.width() - 16), min(self.height(), available.height() - 16))
        self.move(*clamp_window_position(self.width(), self.height(), x, y, available))

    def build_ui(self):
        self._input_duration = None
        self._appearance = (self.app.store.get("language", "ko"), resolve_theme(self.app.store))
        self.setWindowTitle(self.tr("clock.tools.title", "시계 도구"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(10)
        top = QHBoxLayout()
        title = QLabel(self.tr("clock.tools.title", "시계 도구"))
        title.setFont(app_font(11, QFont.Bold))
        top.addWidget(title)
        top.addStretch()
        self.topmost = QCheckBox(self.tr("clock.tools.topmost", "항상 위"))
        self.topmost.toggled.connect(self.set_topmost)
        top.addWidget(self.topmost)
        close = QPushButton("×")
        close.setAccessibleName(self.tr("common.close", "닫기"))
        close.setFixedWidth(28)
        close.clicked.connect(self.close)
        top.addWidget(close)
        layout.addLayout(top)
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet(self.tab_style())
        self.tabs.addTab(self.build_timer(), self.tr("clock.tab.timer", "타이머"))
        self.tabs.addTab(self.build_stopwatch(), self.tr("clock.tab.stopwatch", "스톱워치"))
        self.tabs.addTab(self.build_clock(), self.tr("clock.tab.time", "시간"))
        self.tabs.currentChanged.connect(self.remember_tab)
        layout.addWidget(self.tabs)
        c = self.colors
        self.setStyleSheet(f"QLabel, QCheckBox {{ color: {c['text']}; }}" + self.button_style())
        self.refresh_display()

    def page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        return page, layout

    def time_label(self):
        label = QLabel()
        label.setAlignment(Qt.AlignCenter)
        label.setFont(app_font(26, QFont.Bold))
        return label

    def build_timer(self):
        page, layout = self.page()
        self.timer_label = self.time_label()
        layout.addWidget(self.timer_label)
        inputs = QHBoxLayout()
        self.timer_hours, self.timer_minutes, self.timer_seconds = QSpinBox(), QSpinBox(), QSpinBox()
        for spin, maximum, key, unit in zip(self.timer_inputs, (99, 59, 59),
                                          ("hours", "minutes", "seconds"), ("시간", "분", "초"), strict=True):
            spin.setRange(0, maximum)
            spin.setButtonSymbols(QSpinBox.NoButtons)
            spin.setAlignment(Qt.AlignCenter)
            spin.setStyleSheet(self.input_style())
            spin.setAccessibleName(self.tr(f"clock.unit.{key}", unit))
            spin.valueChanged.connect(self.on_input_changed)
            inputs.addWidget(spin)
            inputs.addWidget(QLabel(self.tr(f"clock.unit.{key}", unit)))
        layout.addLayout(inputs)
        presets = QHBoxLayout()
        self.preset_buttons = []
        for minutes in (5, 10, 25):
            button = QPushButton(self.tr("clock.tools.preset", "{minutes}분", minutes=minutes))
            button.clicked.connect(lambda _checked=False, value=minutes: self.set_timer_preset(value))
            presets.addWidget(button)
            self.preset_buttons.append(button)
        layout.addLayout(presets)
        controls = QHBoxLayout()
        self.timer_cancel_button = QPushButton(self.tr("clock.action.cancel", "취소"))
        self.timer_cancel_button.clicked.connect(self.reset_timer)
        self.timer_start_button = QPushButton()
        self.timer_start_button.clicked.connect(self.toggle_timer)
        controls.addWidget(self.timer_cancel_button)
        controls.addWidget(self.timer_start_button)
        layout.addLayout(controls)
        return page

    @property
    def timer_inputs(self):
        return self.timer_hours, self.timer_minutes, self.timer_seconds

    def build_stopwatch(self):
        page, layout = self.page()
        self.stopwatch_label = self.time_label()
        layout.addWidget(self.stopwatch_label)
        controls = QHBoxLayout()
        reset = QPushButton(self.tr("clock.action.reset", "초기화"))
        reset.clicked.connect(self.reset_stopwatch)
        self.stopwatch_start_button = QPushButton()
        self.stopwatch_start_button.clicked.connect(self.toggle_stopwatch)
        controls.addWidget(reset)
        controls.addWidget(self.stopwatch_start_button)
        layout.addLayout(controls)
        return page

    def build_clock(self):
        page, layout = self.page()
        self.clock_label = self.time_label()
        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        layout.addStretch()
        layout.addWidget(self.clock_label)
        layout.addWidget(self.date_label)
        layout.addStretch()
        return page

    @property
    def current_tab(self):
        return self.TAB_KEYS[self.tabs.currentIndex()]

    def select_tab(self, key):
        self.tabs.setCurrentIndex(self.TAB_KEYS.index(key) if key in self.TAB_KEYS else 0)
        self.remember_tab()

    def remember_tab(self, *_args):
        self.app.store.set("clock_tools_tab", self.current_tab, notify_topic=None)

    def set_topmost(self, checked):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, checked)
        self.show()

    def on_input_changed(self, *_args):
        if hasattr(self, "timer_start_button") and not self.timer_running and not self.timer_remaining_before_pause_ms:
            self.app.timer_requested_ms = self.timer_input_milliseconds()
            self.refresh_timer_from_inputs()
            self.refresh_display()

    def set_timer_preset(self, minutes):
        if self.timer_running or self.timer_remaining_before_pause_ms:
            return
        self.set_input_duration(minutes * 60_000)
        self.on_input_changed()

    def set_input_duration(self, duration):
        seconds = max(0, int(duration)) // 1000
        for spin, value in zip(self.timer_inputs, (seconds // 3600, seconds // 60 % 60, seconds % 60), strict=True):
            spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(False)
        self._input_duration = duration

    def toggle_timer(self):
        self.pause_timer() if self.timer_running else self.start_timer()

    def start_timer(self):
        if not self.timer_running and not self.timer_remaining_before_pause_ms:
            self.app.timer_requested_ms = self.timer_input_milliseconds()
        super().start_timer()
        self.refresh_display()

    def pause_timer(self):
        # 완료 직후 UI가 앱의 다음 tick보다 먼저 상태를 멈춰 발화를 삼키지 않는다.
        if self.timer_running and self.current_timer_remaining_ms() == 0:
            self.app.check_background_timer()
        super().pause_timer()
        self.refresh_display()

    def reset_timer(self):
        super().reset_timer()
        self.refresh_display()

    def refresh_display(self):
        duration = getattr(self.app, "timer_requested_ms", self.app.timer_total_duration)
        if duration != self._input_duration:
            self.set_input_duration(duration)
        running = self.timer_running
        paused = not running and self.timer_remaining_before_pause_ms > 0
        remaining = self.current_timer_remaining_ms()
        self.timer_label.setText(self.format_milliseconds(remaining))
        key, fallback = ("pause", "일시정지") if running else (("resume", "계속") if paused else
                         (("restart", "다시 시작") if duration > 0 and remaining == 0 else ("start", "시작")))
        self.timer_start_button.setText(self.tr(f"clock.action.{key}", fallback))
        self.timer_start_button.setEnabled(running or paused or self.timer_input_milliseconds() > 0)
        for widget in (*self.timer_inputs, *self.preset_buttons):
            widget.setEnabled(not running and not paused)
        self.stopwatch_label.setText(self.format_stopwatch(self.current_stopwatch_elapsed()))
        self.stopwatch_start_button.setText(self.tr("clock.action.pause", "일시정지") if self.stopwatch_running
                                            else self.tr("clock.action.start", "시작"))
        now = self.app.current_clock_datetime()
        self.clock_label.setText(now.strftime("%H:%M:%S"))
        self.date_label.setText(now.strftime("%Y.%m.%d"))

    def showEvent(self, event):
        super().showEvent(event)
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        self.resize(min(self.width(), available.width() - 16), min(self.height(), available.height() - 16))
        self.move(*clamp_window_position(self.width(), self.height(), self.x(), self.y(), available))
        if self._appearance != (self.app.store.get("language", "ko"), resolve_theme(self.app.store)):
            self.apply_theme()
        self.refresh_display()
        self.display_timer.start()

    def apply_theme(self):
        selected = self.current_tab
        topmost = self.topmost.isChecked()
        self.colors.update(resolve_theme(self.app.store))
        old = QWidget()
        old.setLayout(self.layout())
        old.deleteLater()
        self.build_ui()
        self.select_tab(selected)
        self.topmost.blockSignals(True)
        self.topmost.setChecked(topmost)
        self.topmost.blockSignals(False)
        self.update()

    def apply_language(self):
        self.apply_theme()

    def hideEvent(self, event):
        self.display_timer.stop()
        self.app.store.set("clock_tools_geometry", geometry_string(self), notify_topic=None)
        super().hideEvent(event)

    def closeEvent(self, event):
        if self.app.force_quit:
            super().closeEvent(event)
        else:
            self.hide()
            event.ignore()
