from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTime
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
        # QSS 배경이 실제로 칠해지도록 styled-background를 켠다 (UX15: 카드 배경 누락 수정).
        self.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 10, 14, 10)
        layout.setSpacing(2)
        self.setStyleSheet(
            f"AlarmRow {{ background: {c['panel2']}; border: none; border-radius: 14px; }}"
            f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; font-size: 11px; font-weight: 700; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )

        self.toggle = Switch(bool(self.alarm.get("enabled", True)), c)
        self.toggle.toggled.connect(partial(self.window.set_alarm_enabled, str(self.alarm.get("id", ""))))

        # 상단: 큰 시간 + 우측 수정/삭제/토글. 하단: 라벨과 상세가 전체 폭을 쓴다 (좁은 창 잘림 방지).
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(8)
        time_label = QLabel(self.time_text())
        time_label.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-size: 24px; font-weight: 800; }}")
        edit = QPushButton(self.window.tr("common.edit", "수정"))
        edit.setFixedHeight(24)
        edit.clicked.connect(partial(self.window.edit_alarm, str(self.alarm.get("id", ""))))
        delete = QPushButton(self.window.tr("common.delete", "삭제"))
        delete.setFixedHeight(24)
        delete.clicked.connect(partial(self.window.delete_alarm, str(self.alarm.get("id", ""))))
        top.addWidget(time_label)
        top.addStretch()
        top.addWidget(edit)
        top.addWidget(delete)
        top.addWidget(self.toggle)

        self.label = QLabel(self.label_text())
        self.label.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-size: 13px; }}")
        self.detail = QLabel(self.detail_text())
        self.detail.setToolTip(self.detail_text())
        self.detail.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; font-weight: 600; }}")

        layout.addLayout(top)
        layout.addWidget(self.label)
        layout.addWidget(self.detail)

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
