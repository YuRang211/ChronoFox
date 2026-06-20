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

    DAY_LABELS = ["월", "화", "수", "목", "금", "토", "일"]
    NOTIFY_LABELS = {"popup": "팝업", "windows": "윈도우 알림", "sound": "소리만"}

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
        label = QLabel(str(self.alarm.get("label", "알람")))
        label.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-size: 13px; }}")
        detail = QLabel(self.detail_text())
        detail.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; font-weight: 600; }}")
        texts.addWidget(time_label)
        texts.addWidget(label)
        texts.addWidget(detail)

        edit = QPushButton("수정")
        edit.setFixedSize(36, 24)
        edit.clicked.connect(partial(self.window.edit_alarm, str(self.alarm.get("id", ""))))

        delete = QPushButton("삭제")
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

    def detail_text(self) -> str:
        if self.alarm.get("kind") == "date":
            repeat = f"{self.alarm.get('date') or '날짜 없음'} 1회"
        else:
            repeat_days = self.alarm.get("repeat_days", [0, 1, 2, 3, 4, 5, 6])
            if repeat_days == [0, 1, 2, 3, 4, 5, 6]:
                repeat = "매일"
            else:
                repeat = " ".join(self.DAY_LABELS[index] for index in repeat_days if 0 <= index < len(self.DAY_LABELS))
        snooze = f"다시 울림 {int(self.alarm.get('snooze_minutes', 5))}분"
        notify = self.NOTIFY_LABELS.get(self.alarm.get("notify_mode", "popup"), "팝업")
        if self.alarm.get("snoozed_until"):
            return f"{repeat} · {snooze} · {notify} · 대기 중"
        return f"{repeat} · {snooze} · {notify}"
