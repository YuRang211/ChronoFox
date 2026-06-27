from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from PySide6.QtCore import QDate, QPoint, Qt, QTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
)

from app_constants import APP_NAME
from app_design import chronofox_panel_colors
from app_i18n import translate
from app_ui import add_soft_shadow, app_font
from app_widgets import ArrowComboBox

from .alarm_dialog_styles import AlarmDialogStyleMixin

if TYPE_CHECKING:
    from .window import ClockWindow

class AlarmEditorDialog(AlarmDialogStyleMixin, QDialog):
    """Modal alarm editor styled after the Stitch add-alarm surface."""

    DAY_KEYS = [
        ("alarm.day.mon", "월"),
        ("alarm.day.tue", "화"),
        ("alarm.day.wed", "수"),
        ("alarm.day.thu", "목"),
        ("alarm.day.fri", "금"),
        ("alarm.day.sat", "토"),
        ("alarm.day.sun", "일"),
    ]

    def __init__(self, window: ClockWindow, alarm: dict | None = None) -> None:
        super().__init__(window)
        self.clock_window = window
        self.colors = chronofox_panel_colors(window.colors)
        self.alarm = alarm or {}
        self.day_checks: list[QCheckBox] = []
        self.drag_offset: QPoint | None = None
        self.setWindowTitle(self.tr("alarm.title.edit" if alarm else "alarm.title.add", "알람 수정" if alarm else "알람 추가"))
        self.setModal(True)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumWidth(420)
        self.build_ui()
        self.load_alarm()

    def tr(self, key: str, fallback: str = "", **format_values: str) -> str:
        text = translate(self.clock_window.app.config.get("language", "ko"), key, fallback)
        if not format_values:
            return text
        try:
            return text.format(**format_values)
        except (KeyError, IndexError, ValueError):
            return fallback or key

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
        title = QLabel(self.tr("alarm.title.edit" if self.alarm else "alarm.title.add", "알람 수정" if self.alarm else "알람 추가"))
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
        self.alarm_time.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.alarm_time.setFixedSize(142, 72)
        self.alarm_time.setAlignment(Qt.AlignCenter)
        self.alarm_time.setStyleSheet(self.time_box_style())
        time_row.addStretch()
        time_row.addWidget(self.alarm_time)
        time_row.addStretch()

        name_label = QLabel(self.tr("alarm.name.label", "알람 이름"))
        name_label.setFont(app_font(10, QFont.Bold))
        name_label.setStyleSheet(f"color: {c['muted']};")
        self.alarm_title_input = QLineEdit()
        self.alarm_title_input.setPlaceholderText(self.tr("alarm.name.placeholder", "알람 이름"))
        self.alarm_title_input.setFixedHeight(46)
        self.alarm_title_input.setStyleSheet(self.line_input_style())

        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.alarm_kind_combo = QComboBox()
        self.alarm_kind_combo.addItem(self.tr("alarm.kind.repeat", "요일 반복"), "repeat")
        self.alarm_kind_combo.addItem(self.tr("alarm.kind.date", "특정 날짜"), "date")
        self.alarm_kind_combo.setFixedHeight(44)
        self.alarm_kind_combo.setStyleSheet(self.combo_style())
        self.alarm_date = QDateEdit()
        self.alarm_date.setCalendarPopup(True)
        self.alarm_date.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.alarm_date.setDisplayFormat("yyyy-MM-dd")
        self.alarm_date.setDate(QDate.currentDate())
        self.alarm_date.setFixedHeight(44)
        self.alarm_date.setStyleSheet(self.date_input_style())
        self.alarm_kind_combo.currentIndexChanged.connect(self.refresh_kind_controls)
        mode_row.addWidget(self.alarm_kind_combo)
        mode_row.addWidget(self.alarm_date)

        days_row = QHBoxLayout()
        days_row.setSpacing(6)
        for key, fallback in self.DAY_KEYS:
            label = self.tr(key, fallback)
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
        notify_label = QLabel(self.tr("alarm.notify.label", "알림 방식"))
        self.alarm_notify_mode = QComboBox()
        self.alarm_notify_mode.addItem(self.tr("alarm.notify.popup", "팝업"), "popup")
        self.alarm_notify_mode.addItem(self.tr("alarm.notify.windows", "윈도우 알림"), "windows")
        self.alarm_notify_mode.addItem(self.tr("alarm.notify.sound", "소리만"), "sound")
        self.alarm_notify_mode.setFixedSize(126, 38)
        self.alarm_notify_mode.setStyleSheet(self.combo_style())
        notify_row.addWidget(notify_label)
        notify_row.addStretch()
        notify_row.addWidget(self.alarm_notify_mode)
        snooze_row = QHBoxLayout()
        snooze_label = QLabel(self.tr("alarm.snooze.label", "다시 울림"))
        self.alarm_snooze_minutes = QSpinBox()
        self.alarm_snooze_minutes.setRange(1, 30)
        self.alarm_snooze_minutes.setValue(5)
        self.alarm_snooze_minutes.setSuffix(self.tr("alarm.snooze.suffix", " 분"))
        self.alarm_snooze_minutes.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.alarm_snooze_minutes.setFixedSize(92, 38)
        self.alarm_snooze_minutes.setStyleSheet(self.spin_style())
        snooze_row.addWidget(snooze_label)
        snooze_row.addStretch()
        snooze_row.addWidget(self.alarm_snooze_minutes)
        sound_row = QHBoxLayout()
        sound_label = QLabel(self.tr("alarm.sound.label", "알림음"))
        self.alarm_sound_mode = ArrowComboBox(c)
        self.alarm_sound_mode.addItem(self.tr("alarm.sound.default", "기본 알림음"), "default")
        self.alarm_sound_mode.addItem(self.tr("alarm.sound.local", "로컬 파일"), "local")
        self.alarm_sound_mode.addItem(self.tr("alarm.sound.url", "외부 HTTPS 링크"), "url")
        self.alarm_sound_mode.setFixedSize(190, 38)
        self.alarm_sound_mode.setStyleSheet(self.combo_style())
        self.alarm_sound_mode.currentIndexChanged.connect(self.refresh_sound_controls)
        sound_row.addWidget(sound_label)
        sound_row.addStretch()
        sound_row.addWidget(self.alarm_sound_mode)

        self.alarm_sound_file = QPushButton(self.tr("alarm.sound.file_select", "파일 선택"))
        self.alarm_sound_file.setFixedHeight(38)
        self.alarm_sound_file.setStyleSheet(self.secondary_button_style())
        self.alarm_sound_file.clicked.connect(self.select_alarm_sound_file)

        self.alarm_sound_url = QLineEdit()
        self.alarm_sound_url.setPlaceholderText("https://example.com/audio")
        self.alarm_sound_url.setFixedHeight(38)
        self.alarm_sound_url.setStyleSheet(self.line_input_style())
        options_layout.addLayout(notify_row)
        options_layout.addLayout(snooze_row)
        options_layout.addLayout(sound_row)
        options_layout.addWidget(self.alarm_sound_file)
        options_layout.addWidget(self.alarm_sound_url)

        actions = QHBoxLayout()
        cancel = QPushButton(self.tr("common.cancel", "취소"))
        save = QPushButton(self.tr("common.save", "저장"))
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
        sound_mode = str(self.alarm.get("sound_mode", self.clock_window.app.config.get("alert_sound_mode", "default")))
        sound_mode = "url" if sound_mode == "youtube" else sound_mode
        if sound_mode not in {"default", "local", "url"}:
            sound_mode = "default"
        sound_index = self.alarm_sound_mode.findData(sound_mode)
        self.alarm_sound_mode.setCurrentIndex(max(0, sound_index))
        sound_path = str(self.alarm.get("sound_path", self.clock_window.app.config.get("alert_sound_path", "")))
        self.alarm_sound_file.setText(sound_path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or self.tr("alarm.sound.file_select", "파일 선택"))
        self.alarm_sound_file.setToolTip(sound_path)
        self.alarm_sound_url.setText(str(self.alarm.get("sound_url", self.clock_window.app.config.get("alert_sound_url", ""))).strip())
        self.refresh_kind_controls()
        self.refresh_sound_controls()

    def payload(self) -> dict:
        kind = self.alarm_kind_combo.currentData()
        repeat_days = [index for index, check in enumerate(self.day_checks) if check.isChecked()]
        if not repeat_days:
            repeat_days = [datetime.now().weekday()]
        return {
            "time": self.alarm_time.time().toString("HH:mm"),
            "label": self.alarm_title_input.text().strip() or self.tr("alarm.default_label", "알람"),
            "enabled": True,
            "last_triggered": "",
            "kind": kind,
            "date": self.alarm_date.date().toString("yyyy-MM-dd") if kind == "date" else "",
            "notify_mode": self.alarm_notify_mode.currentData(),
            "repeat_days": repeat_days,
            "snooze_minutes": self.alarm_snooze_minutes.value(),
            "snoozed_until": "",
            "sound_mode": self.alarm_sound_mode.currentData(),
            "sound_path": self.alarm_sound_file.toolTip() if self.alarm_sound_mode.currentData() == "local" else "",
            "sound_url": self.alarm_sound_url.text().strip() if self.alarm_sound_mode.currentData() == "url" else "",
        }

    def refresh_kind_controls(self) -> None:
        is_date = self.alarm_kind_combo.currentData() == "date"
        self.alarm_date.setVisible(is_date)
        for check in self.day_checks:
            check.setVisible(not is_date)

    def refresh_sound_controls(self) -> None:
        mode = self.alarm_sound_mode.currentData()
        self.alarm_sound_file.setVisible(mode == "local")
        self.alarm_sound_url.setVisible(mode == "url")

    def select_alarm_sound_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("alarm.sound.file_dialog_title", "알림음 선택"),
            "",
            self.tr("alarm.sound.file_filter", "Audio 파일 (*.mp3 *.wav *.m4a *.aac *.ogg);;모든 파일 (*.*)"),
        )
        if not path:
            return
        self.alarm_sound_file.setText(path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1])
        self.alarm_sound_file.setToolTip(path)
        sound_index = self.alarm_sound_mode.findData("local")
        self.alarm_sound_mode.setCurrentIndex(max(0, sound_index))

    def accept(self) -> None:
        parsed = urlparse(self.alarm_sound_url.text().strip())
        if self.alarm_sound_mode.currentData() == "url" and (parsed.scheme != "https" or not parsed.hostname):
            QMessageBox.warning(self, APP_NAME, self.tr("alarm.sound.url_warning", "https:// 로 시작하는 외부 링크를 입력해 주세요."))
            return
        super().accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and event.position().toPoint().y() <= 92:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.drag_offset = None
        super().mouseReleaseEvent(event)
