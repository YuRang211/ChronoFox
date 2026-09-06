"""Detail-schedule 창의 알람과 시계 도구 섹션 믹스인입니다.

알람 CRUD와 타이머 상태는 공용 믹스인을 재사용합니다. 이 섹션의 타이머는 표시만
갱신하며 섹션 전환과 창 종료 때 반드시 중지해야 합니다.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chronofox.clock.alarms import ClockAlarmMixin
from chronofox.clock.styles import ClockStyleMixin
from chronofox.clock.timer import AppTimerStateMixin, ClockTimerMixin
from chronofox.ui.app_ui import app_font

# 하단 보조 영역의 세 서브탭. 라벨 키는 ClockWindow의 기존 clock.tab.* 키를 그대로 재사용한다
# (locale 신규 추가 없음 — parity 부담 0).
AUX_TAB_ITEMS: list[tuple[str, str, str]] = [
    ("clock", "clock.tab.time", "시간"),
    ("stopwatch", "clock.tab.stopwatch", "스톱워치"),
    ("timer", "clock.tab.timer", "타이머"),
]

# 상태 tick은 앱 스케줄러가 소유하며 이 타이머는 계산된 값을 화면에만 반영한다.
# 잡아도(스톱워치 ms 자리가 5회/초로 갱신) 체감 차이가 거의 없고, 허브가 열려 있는 동안의
# 오버헤드를 줄인다.
ALARMS_DISPLAY_TICK_MS = 200


class AlarmsSectionMixin(ClockAlarmMixin, ClockTimerMixin, ClockStyleMixin, AppTimerStateMixin):
    """알람 목록(추가/수정/삭제) + 하단 시계·스톱워치·타이머 보조 영역을 담당합니다."""

    def show_alarms_view(self) -> None:
        """호환 위임: 기존 호출부가 그대로 동작하도록 show_section("alarms")를 부른다."""
        self.show_section("alarms")

    # top bar ---------------------------------------------------------------
    def build_alarms_top_bar(self) -> QHBoxLayout:
        """알람 화면 상단 바(제목 + 추가 + 닫기)를 구성합니다."""
        c = self.colors
        self.view_buttons = {}
        bar = QHBoxLayout()
        bar.setSpacing(12)

        title = QLabel(self.tr("detail.nav.alarms", "알람"))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")

        add_button = QPushButton(self.tr("alarm.title.add", "알람 추가"))
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.setFixedHeight(32)
        add_button.clicked.connect(self.show_alarm_editor)
        add_button.setStyleSheet(
            f"QPushButton {{ background: {c['pill']}; color: {c['pill_text']}; border: none; "
            "border-radius: 9px; padding: 0 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )

        close_button = self.icon_only_button("close", self.close)

        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(add_button)
        bar.addWidget(close_button)
        return bar

    # main view ---------------------------------------------------------------
    def build_alarms_view(self) -> QWidget:
        """알람 목록 + 하단 보조 영역(시계/스톱워치/타이머)을 구성합니다.

        위젯 속성 이름(`self.alarm_list`/`self.next_alarm_label`)은 `ClockAlarmMixin`이
        상정하는 이름과 똑같이 맞춰, 상속받은 `refresh_alarms()`/`refresh_next_alarm_label()`
        을 재정의 없이 그대로 쓴다."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.alarm_list = QListWidget()
        self.alarm_list.setStyleSheet(self.alarm_list_style())
        layout.addWidget(self.alarm_list, 1)

        layout.addWidget(self.build_alarms_aux_panel())

        # refresh_alarms()(ClockAlarmMixin 상속)는 self.alarm_list/self.next_alarm_label이
        # 이미 만들어져 있어야 하므로 두 위젯을 모두 구성한 뒤에 호출한다.
        self.refresh_alarms()
        self.consume_alarms_target()
        self._start_alarms_display_timer()
        return container

    def consume_alarms_target(self) -> None:
        """`show_section("alarms", target)`로 넘어온 대상을 처리합니다(H-D8).

        target이 `"aux:clock"`/`"aux:stopwatch"`/`"aux:timer"`면 하단 보조 영역의 해당
        서브탭으로 전환한다(R4-3b: `window_manager.open_clock_tab(index)`가 예전
        `ClockWindow.NAV_ITEMS` 탭 인덱스를 이 어휘로 매핑해 넘긴다). 그 밖의 값은 기존대로
        알람 id로 해석해 목록에서 선택·스크롤한다."""
        target = self.pending_target
        if not target:
            return
        target = str(target)
        if target.startswith("aux:"):
            self.switch_alarms_aux_tab(target.removeprefix("aux:"))
            return
        if not hasattr(self, "alarm_list"):
            return
        for row in range(self.alarm_list.count()):
            item = self.alarm_list.item(row)
            widget = self.alarm_list.itemWidget(item)
            if widget is not None and str(getattr(widget, "alarm", {}).get("id", "")) == target:
                self.alarm_list.setCurrentRow(row)
                self.alarm_list.scrollToItem(item)
                break

    # 하단 보조 영역: 시계/스톱워치/타이머 -------------------------------------
    def build_alarms_aux_panel(self) -> QFrame:
        """하단 보조 영역(시계/스톱워치/타이머 서브탭) 컨테이너를 구성합니다."""
        c = self.colors
        frame = QFrame()
        frame.setObjectName("alarmsAuxPanel")
        frame.setStyleSheet(
            f"QFrame#alarmsAuxPanel {{ background: {c['panel']}; border: 1px solid {c['border']}; "
            "border-radius: 14px; }}"
        )
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(16, 14, 16, 16)
        outer.setSpacing(10)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.alarms_aux_buttons: dict[str, QPushButton] = {}
        for key, label_key, fallback in AUX_TAB_ITEMS:
            button = QPushButton(self.tr(label_key, fallback))
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(28)
            button.clicked.connect(lambda _checked=False, k=key: self.switch_alarms_aux_tab(k))
            self.alarms_aux_buttons[key] = button
            nav_row.addWidget(button)
        outer.addLayout(nav_row)

        self.alarms_aux_stack = QStackedWidget()
        self.alarms_aux_stack.addWidget(self.build_alarms_clock_panel())
        self.alarms_aux_stack.addWidget(self.build_alarms_stopwatch_panel())
        self.alarms_aux_stack.addWidget(self.build_alarms_timer_panel())
        outer.addWidget(self.alarms_aux_stack)

        self.switch_alarms_aux_tab(getattr(self, "_alarms_aux_tab", "clock"))
        return frame

    def switch_alarms_aux_tab(self, key: str) -> None:
        """하단 보조 영역의 시계/스톱워치/타이머 서브탭을 전환합니다."""
        names = [name for name, _label_key, _fallback in AUX_TAB_ITEMS]
        index = names.index(key) if key in names else 0
        self._alarms_aux_tab = names[index]
        if hasattr(self, "alarms_aux_stack"):
            self.alarms_aux_stack.setCurrentIndex(index)
        for name, button in getattr(self, "alarms_aux_buttons", {}).items():
            button.setStyleSheet(self.alarms_aux_tab_style(name == self._alarms_aux_tab))

    def alarms_aux_tab_style(self, active: bool) -> str:
        """하단 보조 영역 서브탭 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        if active:
            return (
                f"QPushButton {{ background: {c['accent']}; color: #ffffff; border: none; "
                "border-radius: 8px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 8px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

    def build_alarms_clock_panel(self) -> QWidget:
        """하단 보조 영역의 시계 서브탭(현재 시각 + 다음 알람)을 구성합니다."""
        c = self.colors
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)
        self.alarms_clock_time = QLabel("")
        self.alarms_clock_time.setAlignment(Qt.AlignCenter)
        self.alarms_clock_time.setFont(app_font(26, QFont.Bold))
        self.alarms_clock_date = QLabel("")
        self.alarms_clock_date.setAlignment(Qt.AlignCenter)
        self.alarms_clock_date.setFont(app_font(10, QFont.Bold))
        self.alarms_clock_date.setStyleSheet(f"color: {c['muted']};")
        # next_alarm_label: ClockAlarmMixin.refresh_next_alarm_label()이 hasattr로 찾는
        # 바로 그 이름 — refresh_alarms() 호출 한 번으로 이 라벨도 함께 갱신된다.
        self.next_alarm_label = QLabel("")
        self.next_alarm_label.setAlignment(Qt.AlignCenter)
        self.next_alarm_label.setFont(app_font(9, QFont.Medium))
        self.next_alarm_label.setStyleSheet(f"color: {c['accent']};")
        layout.addWidget(self.alarms_clock_time)
        layout.addWidget(self.alarms_clock_date)
        layout.addWidget(self.next_alarm_label)
        self._refresh_alarms_clock_display()
        return widget

    def build_alarms_stopwatch_panel(self) -> QWidget:
        """하단 보조 영역의 스톱워치 서브탭을 구성합니다."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 4)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignCenter)
        self.stopwatch_label = QLabel(self.format_stopwatch(self.current_stopwatch_elapsed()))
        self.stopwatch_label.setAlignment(Qt.AlignCenter)
        self.stopwatch_label.setFont(app_font(24, QFont.Bold))

        controls = QHBoxLayout()
        controls.setSpacing(12)
        start_label = (
            self.tr("clock.action.stop", "중지") if self.stopwatch_running else self.tr("clock.action.start", "시작")
        )
        start = QPushButton(start_label)
        reset = QPushButton(self.tr("clock.action.reset", "초기화"))
        self.stopwatch_start_button = start
        start.setCursor(Qt.PointingHandCursor)
        reset.setCursor(Qt.PointingHandCursor)
        start.setFixedSize(58, 58)
        reset.setFixedSize(58, 58)
        start.clicked.connect(self.toggle_stopwatch)
        reset.clicked.connect(self.reset_stopwatch)
        start.setStyleSheet(self.round_button_style(primary=True))
        reset.setStyleSheet(self.round_button_style(primary=False))
        controls.addStretch()
        controls.addWidget(start)
        controls.addWidget(reset)
        controls.addStretch()

        layout.addWidget(self.stopwatch_label)
        layout.addLayout(controls)
        return widget

    def build_alarms_timer_panel(self) -> QWidget:
        """하단 보조 영역의 타이머 서브탭을 구성합니다."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 6, 0, 4)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignCenter)

        inputs = QHBoxLayout()
        inputs.setSpacing(8)
        self.timer_hours = QSpinBox()
        self.timer_minutes = QSpinBox()
        self.timer_seconds = QSpinBox()
        self.timer_hours.setRange(0, 99)
        self.timer_minutes.setRange(0, 59)
        self.timer_seconds.setRange(0, 59)
        for spin in (self.timer_hours, self.timer_minutes, self.timer_seconds):
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            spin.setFixedSize(56, 40)
            spin.setAlignment(Qt.AlignCenter)
            spin.setStyleSheet(self.input_style())
            spin.valueChanged.connect(lambda _value: self.refresh_timer_from_inputs())
            inputs.addWidget(spin)

        self.timer_label = QLabel(self.format_milliseconds(self.timer_remaining_ms))
        self.timer_label.setAlignment(Qt.AlignCenter)
        self.timer_label.setFont(app_font(22, QFont.Bold))

        controls = QHBoxLayout()
        controls.setSpacing(10)
        reset = QPushButton(self.tr("clock.action.cancel", "취소"))
        start = QPushButton(self.tr("clock.action.start", "시작"))
        start.clicked.connect(self.start_timer)
        reset.clicked.connect(self.reset_timer)
        for button in (reset, start):
            button.setFixedHeight(36)
            button.setCursor(Qt.PointingHandCursor)
        reset.setStyleSheet(self.timer_button_style(primary=False))
        start.setStyleSheet(self.timer_button_style(primary=True))
        controls.addWidget(reset)
        controls.addWidget(start)

        layout.addWidget(self.timer_label)
        layout.addLayout(inputs)
        layout.addLayout(controls)
        return widget

    # 표시 갱신 타이머
    def _start_alarms_display_timer(self) -> None:
        """알람 섹션이 화면에 보이는 동안만 도는 표시 갱신 타이머를 시작합니다."""
        timer = getattr(self, "_alarms_display_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setInterval(ALARMS_DISPLAY_TICK_MS)
            timer.timeout.connect(self._on_alarms_display_tick)
            self._alarms_display_timer = timer
        self._on_alarms_display_tick()
        timer.start()

    def stop_alarms_display_timer(self) -> None:
        """표시 갱신 타이머를 멈춥니다. 섹션을 벗어날 때(build_ui 재빌드)와 창을 닫을 때
        (closeEvent) 반드시 호출해야 한다 — 그렇지 않으면 이미 지워진 위젯을 계속
        갱신하려는 죽은 타이머가 남는다."""
        timer = getattr(self, "_alarms_display_timer", None)
        if timer is not None:
            timer.stop()

    def _on_alarms_display_tick(self) -> None:
        """시계/스톱워치/타이머 표시만 갱신합니다. 상태(`self.timer_running` 등)는 항상
        `FoxCalendarApp`이 갖고 있는 값을 읽기만 할 뿐, 여기서 새로 만들지 않는다(H-D9)."""
        self._refresh_alarms_clock_display()
        if hasattr(self, "stopwatch_label") and self.stopwatch_running:
            self.stopwatch_label.setText(self.format_stopwatch(self.current_stopwatch_elapsed()))
        if hasattr(self, "timer_label"):
            if self.timer_running:
                self.timer_remaining_ms = self.current_timer_remaining_ms()
            self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def _refresh_alarms_clock_display(self) -> None:
        """하단 보조 영역의 현재 시각 표시를 다시 그립니다(분/초가 바뀔 때만 실제로 갱신)."""
        if not hasattr(self, "alarms_clock_time"):
            return
        now = self.current_clock_datetime()
        stamp = now.strftime("%H:%M:%S")
        if getattr(self, "_alarms_last_clock_stamp", "") == stamp:
            return
        self._alarms_last_clock_stamp = stamp
        self.alarms_clock_time.setText(stamp)
        self.alarms_clock_date.setText(now.strftime("%Y.%m.%d"))
