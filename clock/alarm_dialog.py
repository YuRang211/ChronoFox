from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QTime, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QComboBox, QDateEdit, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTimeEdit, QVBoxLayout

from app_ui import add_soft_shadow, app_font
from .alarm_dialog_styles import AlarmDialogStyleMixin

if TYPE_CHECKING:
    from .window import ClockWindow

class AlarmEditorDialog(AlarmDialogStyleMixin, QDialog):
    """Modal alarm editor styled after the Stitch add-alarm surface."""

    DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]

    def __init__(self, window: ClockWindow, alarm: dict | None = None) -> None:
        super().__init__(window)
        self.window = window
        self.colors = window.colors
        self.alarm = alarm or {}
        self.day_checks: list[QCheckBox] = []
        self.setWindowTitle("알람 수정" if alarm else "알람 추가")
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)
        self.build_ui()
        self.load_alarm()

    def build_ui(self) -> None:
        c = self.colors
        self.setStyleSheet(
            "QDialog { background: transparent; }"
            f"QLabel {{ color: {c['text']}; }}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(0)
        card = QFrame()
        card.setObjectName("alarmDialogCard")
        card.setStyleSheet(
            f"QFrame#alarmDialogCard {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 20px; }}"
        )
        add_soft_shadow(card, c, blur=34, alpha=34)
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(24, 22, 24, 24)
        root.setSpacing(17)

        header = QHBoxLayout()
        title = QLabel("알람 수정" if self.alarm else "알람 추가")
        title.setFont(app_font(22, QFont.Bold))
        close = QPushButton("×")
        close.setFixedSize(32, 32)
        close.setStyleSheet(self.ghost_button_style())
        close.clicked.connect(self.reject)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)

        time_row = QHBoxLayout()
        time_row.setSpacing(14)
        self.alarm_time = QTimeEdit()
        self.alarm_time.setDisplayFormat("HH:mm")
        self.alarm_time.setButtonSymbols(QTimeEdit.UpDownArrows)
        self.alarm_time.setFixedSize(142, 72)
        self.alarm_time.setAlignment(Qt.AlignCenter)
        self.alarm_time.setStyleSheet(self.time_box_style())
        time_row.addStretch()
        time_row.addWidget(self.alarm_time)
        time_row.addStretch()

        name_label = QLabel("알람 이름")
        name_label.setFont(app_font(10, QFont.Bold))
        name_label.setStyleSheet(f"color: {c['muted']};")
        self.alarm_title_input = QLineEdit()
        self.alarm_title_input.setPlaceholderText("알람 이름")
        self.alarm_title_input.setFixedHeight(46)
        self.alarm_title_input.setStyleSheet(self.line_input_style())

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.alarm_kind_combo = QComboBox()
        self.alarm_kind_combo.addItem("요일 반복", "repeat")
        self.alarm_kind_combo.addItem("특정 날짜", "date")
        self.alarm_kind_combo.setFixedHeight(44)
        self.alarm_kind_combo.setStyleSheet(self.combo_style())
        self.alarm_date = QDateEdit()
        self.alarm_date.setCalendarPopup(True)
        self.alarm_date.setDisplayFormat("yyyy-MM-dd")
        self.alarm_date.setDate(QDate.currentDate())
        self.alarm_date.setFixedHeight(44)
        self.alarm_date.setStyleSheet(self.date_input_style())
        self.alarm_kind_combo.currentIndexChanged.connect(self.refresh_kind_controls)
        mode_row.addWidget(self.alarm_kind_combo)
        mode_row.addWidget(self.alarm_date)

        days_row = QHBoxLayout()
        days_row.setSpacing(6)
        for label in self.DAY_LABELS:
            check = QCheckBox(label)
            check.setChecked(True)
            check.setStyleSheet(self.day_check_style())
            self.day_checks.append(check)
            days_row.addWidget(check)

        options = QFrame()
        options.setObjectName("alarmOptions")
        options.setStyleSheet(
            f"QFrame#alarmOptions {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 14px; }}"
        )
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(14, 12, 14, 12)
        options_layout.setSpacing(10)
        notify_row = QHBoxLayout()
        notify_label = QLabel("알림 방식")
        self.alarm_notify_mode = QComboBox()
        self.alarm_notify_mode.addItem("팝업", "popup")
        self.alarm_notify_mode.addItem("윈도우 알림", "windows")
        self.alarm_notify_mode.addItem("소리만", "sound")
        self.alarm_notify_mode.setFixedSize(126, 38)
        self.alarm_notify_mode.setStyleSheet(self.combo_style())
        notify_row.addWidget(notify_label)
        notify_row.addStretch()
        notify_row.addWidget(self.alarm_notify_mode)
        snooze_row = QHBoxLayout()
        snooze_label = QLabel("다시 울림")
        self.alarm_snooze_minutes = QSpinBox()
        self.alarm_snooze_minutes.setRange(1, 30)
        self.alarm_snooze_minutes.setValue(5)
        self.alarm_snooze_minutes.setSuffix(" 분")
        self.alarm_snooze_minutes.setButtonSymbols(QSpinBox.UpDownArrows)
        self.alarm_snooze_minutes.setFixedSize(92, 38)
        self.alarm_snooze_minutes.setStyleSheet(self.spin_style())
        snooze_row.addWidget(snooze_label)
        snooze_row.addStretch()
        snooze_row.addWidget(self.alarm_snooze_minutes)
        options_layout.addLayout(notify_row)
        options_layout.addLayout(snooze_row)

        actions = QHBoxLayout()
        cancel = QPushButton("취소")
        save = QPushButton("저장")
        cancel.setFixedHeight(44)
        save.setFixedHeight(44)
        cancel.setStyleSheet(self.secondary_button_style())
        save.setStyleSheet(self.primary_button_style())
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        actions.addStretch()
        actions.addWidget(cancel)
        actions.addWidget(save)

        root.addLayout(header)
        root.addLayout(time_row)
        root.addWidget(name_label)
        root.addWidget(self.alarm_title_input)
        root.addLayout(mode_row)
        root.addLayout(days_row)
        root.addWidget(options)
        root.addLayout(actions)

    def load_alarm(self) -> None:
        parsed = QTime.fromString(str(self.alarm.get("time", "07:00")), "HH:mm")
        self.alarm_time.setTime(parsed if parsed.isValid() else QTime.currentTime())
        self.alarm_title_input.setText(str(self.alarm.get("label", "")))
        kind_index = self.alarm_kind_combo.findData(self.alarm.get("kind", "repeat"))
        self.alarm_kind_combo.setCurrentIndex(max(0, kind_index))
        alarm_date = QDate.fromString(str(self.alarm.get("date", "")), "yyyy-MM-dd")
        self.alarm_date.setDate(alarm_date if alarm_date.isValid() else QDate.currentDate())
        repeat_days = set(self.alarm.get("repeat_days", [0, 1, 2, 3, 4, 5, 6]))
        for index, check in enumerate(self.day_checks):
            check.setChecked(index in repeat_days)
        self.alarm_snooze_minutes.setValue(max(1, min(30, int(self.alarm.get("snooze_minutes", 5)))))
        notify_index = self.alarm_notify_mode.findData(self.alarm.get("notify_mode", "popup"))
        self.alarm_notify_mode.setCurrentIndex(max(0, notify_index))
        self.refresh_kind_controls()

    def payload(self) -> dict:
        kind = self.alarm_kind_combo.currentData()
        repeat_days = [index for index, check in enumerate(self.day_checks) if check.isChecked()]
        if not repeat_days:
            repeat_days = [datetime.now().weekday()]
        return {
            "time": self.alarm_time.time().toString("HH:mm"),
            "label": self.alarm_title_input.text().strip() or "알람",
            "enabled": True,
            "last_triggered": "",
            "kind": kind,
            "date": self.alarm_date.date().toString("yyyy-MM-dd") if kind == "date" else "",
            "notify_mode": self.alarm_notify_mode.currentData(),
            "repeat_days": repeat_days,
            "snooze_minutes": self.alarm_snooze_minutes.value(),
            "snoozed_until": "",
        }

    def refresh_kind_controls(self) -> None:
        is_date = self.alarm_kind_combo.currentData() == "date"
        self.alarm_date.setVisible(is_date)
        for check in self.day_checks:
            check.setVisible(not is_date)
