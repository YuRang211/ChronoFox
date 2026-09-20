"""허브의 알람 관리와 독립 시계 도구 진입을 구성합니다."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chronofox.clock.alarms import ClockAlarmMixin
from chronofox.clock.styles import ClockStyleMixin
from chronofox.ui.app_ui import app_font


class AlarmsSectionMixin(ClockAlarmMixin, ClockStyleMixin):
    """알람 목록·편집과 다음 알람 요약을 담당합니다."""

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
        """알람 목록과 다음 알람 요약, 시간 도구 바로가기를 구성합니다.

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

        self.next_alarm_label = QLabel("")
        layout.addWidget(self.next_alarm_label)
        self.clock_tools_link = QPushButton(self.tr("clock.tools.open", "타이머·스톱워치 열기"))
        self.clock_tools_link.setStyleSheet(self.button_style())
        self.clock_tools_link.setMinimumHeight(32)
        self.clock_tools_link.setCursor(Qt.PointingHandCursor)
        self.clock_tools_link.clicked.connect(lambda: self.app.open_clock())
        layout.addWidget(self.clock_tools_link, alignment=Qt.AlignLeft)

        # refresh_alarms()(ClockAlarmMixin 상속)는 self.alarm_list/self.next_alarm_label이
        # 이미 만들어져 있어야 하므로 두 위젯을 모두 구성한 뒤에 호출한다.
        self.refresh_alarms()
        self.consume_alarms_target()
        return container

    def consume_alarms_target(self) -> None:
        """알람 id를 선택하거나 이전 aux 딥링크를 독립 시간 도구로 연결합니다."""
        target = self.pending_target
        if not target:
            return
        target = str(target)
        if target.startswith("aux:"):
            self.app.open_clock_tab({"clock": 0, "stopwatch": 1, "timer": 2}.get(target.removeprefix("aux:"), 2))
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
