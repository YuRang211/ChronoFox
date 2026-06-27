from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QTime
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app_widgets import Switch

if TYPE_CHECKING:
    from .window import ClockWindow

class AlarmRow(QWidget):
    """알람 한 줄을 켜고 끄거나 삭제합니다."""

    DAY_LABELS = [
        ("alarm.day.mon", "월"),
        ("alarm.day.tue", "화"),
        ("alarm.day.wed", "수"),
        ("alarm.day.thu", "목"),
        ("alarm.day.fri", "금"),
        ("alarm.day.sat", "토"),
        ("alarm.day.sun", "일"),
    ]
    NOTIFY_LABELS = {
        "popup": ("alarm.notify.popup", "팝업"),
        "windows": ("alarm.notify.windows", "윈도우 알림"),
        "sound": ("alarm.notify.sound", "소리만"),
    }

    def __init__(self, window: ClockWindow, alarm: dict) -> None:
        super().__init__()
        self.window = window
        self.alarm = alarm
        self.build_ui()

    def build_ui(self) -> None:
        c = self.window.colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)
        self.setStyleSheet(
            f"AlarmRow {{ background: {c['panel2']}; border: none; border-radius: 16px; }}"
            f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )

        self.toggle = Switch(bool(self.alarm.get("enabled", True)), c)
        self.toggle.toggled.connect(partial(self.window.set_alarm_enabled, str(self.alarm.get("id", ""))))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(4)
        time_label = QLabel(self.time_text())
        time_label.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-size: 24px; font-weight: 800; }}")
        self.label = QLabel(self.label_text())
        self.label.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-size: 13px; }}")
        self.detail = QLabel(self.detail_text())
        self.detail.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; font-weight: 600; }}")
        texts.addWidget(time_label)
        texts.addWidget(self.label)
        texts.addWidget(self.detail)

        edit = QPushButton(self.window.tr("common.edit", "수정"))
        edit.setFixedSize(36, 24)
        edit.clicked.connect(partial(self.window.edit_alarm, str(self.alarm.get("id", ""))))

        delete = QPushButton(self.window.tr("common.delete", "삭제"))
        delete.setFixedSize(36, 24)
        delete.clicked.connect(partial(self.window.delete_alarm, str(self.alarm.get("id", ""))))

        layout.addLayout(texts, 1)
        layout.addWidget(edit)
        layout.addWidget(delete)
        layout.addWidget(self.toggle)

    def time_text(self) -> str:
        value = str(self.alarm.get("time", "07:00"))
        parsed = QTime.fromString(value, "HH:mm")
        if not parsed.isValid():
            return value
        suffix = "AM" if parsed.hour() < 12 else "PM"
        hour = parsed.hour() % 12 or 12
        return f"{hour:02}:{parsed.minute():02} {suffix}"

    def label_text(self) -> str:
        value = str(self.alarm.get("label", "")).strip()
        if not value or value == "알람":
            return self.window.tr("alarm.default_label", "알람")
        return value

    def detail_text(self) -> str:
        if self.alarm.get("kind") == "date":
            repeat = self.window.tr("alarm.detail.once", "{date} 1회").format(
                date=self.alarm.get("date") or self.window.tr("alarm.date_missing", "날짜 없음"),
            )
        else:
            repeat_days = self.alarm.get("repeat_days", [0, 1, 2, 3, 4, 5, 6])
            if repeat_days == [0, 1, 2, 3, 4, 5, 6]:
                repeat = self.window.tr("alarm.repeat.every_day", "매일")
            else:
                repeat = " ".join(
                    self.window.tr(label_key, fallback)
                    for index, (label_key, fallback) in enumerate(self.DAY_LABELS)
                    if index in repeat_days
                )
        snooze = self.window.tr("alarm.detail.snooze", "다시 울림 {minutes}분").format(
            minutes=int(self.alarm.get("snooze_minutes", 5)),
        )
        notify_key, notify_fallback = self.NOTIFY_LABELS.get(self.alarm.get("notify_mode", "popup"), self.NOTIFY_LABELS["popup"])
        notify = self.window.tr(notify_key, notify_fallback)
        if self.alarm.get("snoozed_until"):
            return f"{repeat} · {snooze} · {notify} · {self.window.tr('alarm.detail.pending', '대기 중')}"
        return f"{repeat} · {snooze} · {notify}"
