from __future__ import annotations

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget

from app_ui import app_font, clear_layout
from .nav import ClockNavButton


class ClockLayoutMixin:
    """Widget construction and theme refresh for the clock window."""

    def build_ui(self) -> None:
        c = self.colors
        self.styled_buttons: list[QPushButton] = []
        self.spinboxes: list[QSpinBox] = []
        self.nav_buttons: list[ClockNavButton] = []
        self.panels: list[QFrame] = []
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.header_widget())

        self.content_stack = QStackedWidget()
        self.content_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        self.content_stack.addWidget(self.clock_tab())
        self.content_stack.addWidget(self.stopwatch_tab())
        self.content_stack.addWidget(self.timer_tab())
        self.content_stack.addWidget(self.alarm_tab())
        layout.addWidget(self.content_stack, 1)

        self.nav_frame = QFrame()
        self.nav_frame.setObjectName("clockFooterNav")
        self.nav_frame.setStyleSheet(self.footer_nav_style())
        nav_layout = QHBoxLayout(self.nav_frame)
        nav_layout.setContentsMargins(24, 10, 24, 14)
        nav_layout.setSpacing(2)
        for index, (_key, label, icon) in enumerate(self.NAV_ITEMS):
            button = ClockNavButton(icon, label, self.colors)
            button.clicked.connect(partial(self.switch_tab, index))
            self.nav_buttons.append(button)
            nav_layout.addWidget(button, 1)
        layout.addWidget(self.nav_frame)
        self.switch_tab(0)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        if hasattr(self, "header_frame"):
            self.header_frame.setStyleSheet(self.header_frame_style())
        if hasattr(self, "content_stack"):
            self.content_stack.setStyleSheet("QStackedWidget { background: transparent; border: none; }")
        if hasattr(self, "nav_frame"):
            self.nav_frame.setStyleSheet(self.footer_nav_style())
        for panel in getattr(self, "panels", []):
            panel.setStyleSheet(self.panel_style())
        for button in getattr(self, "nav_buttons", []):
            button.colors = self.colors
            button.refresh_style()
        for button in getattr(self, "styled_buttons", []):
            name = button.objectName()
            if name == "headerCloseButton":
                button.setStyleSheet(self.close_button_style())
            elif name == "primaryRoundButton":
                button.setStyleSheet(self.round_button_style(primary=True))
            elif name == "outlineRoundButton":
                button.setStyleSheet(self.round_button_style(primary=False))
            elif name == "primaryTimerButton":
                button.setStyleSheet(self.timer_button_style(primary=True))
            elif name == "secondaryTimerButton":
                button.setStyleSheet(self.timer_button_style(primary=False))
            elif name == "floatingAddButton":
                button.setStyleSheet(self.floating_add_button_style())
            else:
                button.setStyleSheet(self.button_style())
        for spin in getattr(self, "spinboxes", []):
            spin.setStyleSheet(self.input_style())
        if hasattr(self, "time_source"):
            self.time_source.setStyleSheet(f"color: {self.colors['muted']};")
        if hasattr(self, "alarm_list"):
            self.alarm_list.setStyleSheet(self.alarm_list_style())
        self.refresh_active_nav()
        self.update()

    def header_widget(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("clockHeader")
        frame.setStyleSheet(self.header_frame_style())
        header = QHBoxLayout(frame)
        header.setContentsMargins(0, 10, 14, 0)
        self.close_button = QPushButton("×")
        self.close_button.setObjectName("headerCloseButton")
        self.close_button.setFixedSize(32, 32)
        self.close_button.setStyleSheet(self.close_button_style())
        self.close_button.clicked.connect(self.close)
        self.styled_buttons.append(self.close_button)
        header.addStretch()
        header.addWidget(self.close_button)
        frame.setFixedHeight(48)
        self.header_frame = frame
        return frame

    def switch_tab(self, index: int) -> None:
        if not hasattr(self, "content_stack"):
            return
        index = max(0, min(index, self.content_stack.count() - 1))
        self.content_stack.setCurrentIndex(index)
        self.refresh_active_nav()

    def refresh_active_nav(self) -> None:
        if not hasattr(self, "content_stack"):
            return
        current = self.content_stack.currentIndex()
        for index, button in enumerate(getattr(self, "nav_buttons", [])):
            button.set_active(index == current)

    def clock_tab(self) -> QWidget:
        widget = self.panel_widget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(9)
        layout.setAlignment(Qt.AlignCenter)
        self.current_time = QLabel("")
        self.current_time.setAlignment(Qt.AlignCenter)
        self.current_time.setFont(app_font(48, QFont.Bold))
        self.current_date = QLabel("")
        self.current_date.setAlignment(Qt.AlignCenter)
        self.current_date.setFont(app_font(12, QFont.Bold))
        self.time_source = QLabel("네이버 시간 동기화 중")
        self.time_source.setAlignment(Qt.AlignCenter)
        self.time_source.setFont(app_font(11, QFont.Medium))
        self.time_source.setStyleSheet(f"color: {self.colors['muted']};")
        layout.addWidget(self.current_time)
        layout.addWidget(self.current_date)
        layout.addWidget(self.time_source)
        self.refresh_clock()
        return widget

    def stopwatch_tab(self) -> QWidget:
        widget = self.panel_widget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(28)
        layout.setAlignment(Qt.AlignCenter)
        self.stopwatch_label = QLabel(self.format_stopwatch(0.0))
        self.stopwatch_label.setAlignment(Qt.AlignCenter)
        self.stopwatch_label.setFont(app_font(46, QFont.Bold))
        controls = QHBoxLayout()
        controls.setSpacing(22)
        start = QPushButton("시작")
        reset = QPushButton("초기화")
        self.stopwatch_start_button = start
        start.clicked.connect(self.toggle_stopwatch)
        reset.clicked.connect(self.reset_stopwatch)
        start.setObjectName("primaryRoundButton")
        reset.setObjectName("outlineRoundButton")
        start.setFixedSize(78, 78)
        reset.setFixedSize(78, 78)
        start.setStyleSheet(self.round_button_style(primary=True))
        reset.setStyleSheet(self.round_button_style(primary=False))
        self.styled_buttons.append(start)
        self.styled_buttons.append(reset)
        controls.addStretch()
        controls.addWidget(start)
        controls.addWidget(reset)
        controls.addStretch()
        layout.addWidget(self.stopwatch_label)
        layout.addLayout(controls)
        return widget

    def timer_tab(self) -> QWidget:
        widget = self.panel_widget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(40, 0, 40, 0)
        layout.setSpacing(18)
        layout.setAlignment(Qt.AlignCenter)
        inputs = QHBoxLayout()
        inputs.setSpacing(14)
        self.timer_hours = QSpinBox()
        self.timer_minutes = QSpinBox()
        self.timer_seconds = QSpinBox()
        self.timer_hours.setRange(0, 99)
        self.timer_minutes.setRange(0, 59)
        self.timer_seconds.setRange(0, 59)
        for spin in (self.timer_hours, self.timer_minutes, self.timer_seconds):
            spin.setButtonSymbols(QSpinBox.UpDownArrows)
            spin.setFixedSize(92, 48)
            spin.setAlignment(Qt.AlignCenter)
            spin.setStyleSheet(self.input_style())
            spin.valueChanged.connect(lambda _value: self.refresh_timer_from_inputs())
            self.spinboxes.append(spin)
        for label_text, spin in (("HOURS", self.timer_hours), ("MINUTES", self.timer_minutes), ("SECONDS", self.timer_seconds)):
            column = QVBoxLayout()
            column.setSpacing(5)
            label = QLabel(label_text)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(7, QFont.Bold))
            label.setStyleSheet(f"color: {self.colors['muted']};")
            column.addWidget(label)
            column.addWidget(spin)
            inputs.addLayout(column)
        self.timer_label = QLabel(self.format_milliseconds(0))
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setFont(app_font(42, QFont.Bold))
        controls = QHBoxLayout()
        controls.setSpacing(16)
        start = QPushButton("시작")
        reset = QPushButton("취소")
        start.clicked.connect(self.start_timer)
        reset.clicked.connect(self.reset_timer)
        layout.addWidget(self.timer_label)
        layout.addLayout(inputs)
        start.setObjectName("primaryTimerButton")
        reset.setObjectName("secondaryTimerButton")
        for button, primary in ((reset, False), (start, True)):
            button.setStyleSheet(self.timer_button_style(primary=primary))
            button.setFixedHeight(48)
            self.styled_buttons.append(button)
            controls.addWidget(button)
        layout.addLayout(controls)
        return widget

    def alarm_tab(self) -> QWidget:
        widget = self.panel_widget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(46, 20, 46, 10)
        layout.setSpacing(12)
        self.alarm_list = QListWidget()
        self.alarm_list.setStyleSheet(self.alarm_list_style())
        self.alarm_new_button = QPushButton("+")
        self.alarm_new_button.setObjectName("floatingAddButton")
        self.alarm_new_button.setFixedSize(52, 52)
        self.alarm_new_button.setStyleSheet(self.floating_add_button_style())
        self.alarm_new_button.clicked.connect(self.show_alarm_editor)
        self.styled_buttons.append(self.alarm_new_button)
        layout.addWidget(self.alarm_list, 1)
        add_row = QHBoxLayout()
        add_row.addStretch()
        add_row.addWidget(self.alarm_new_button)
        layout.addLayout(add_row)
        self.refresh_alarms()
        return widget

    def panel_widget(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName("clockPanel")
        panel.setStyleSheet(self.panel_style())
        self.panels.append(panel)
        return panel
