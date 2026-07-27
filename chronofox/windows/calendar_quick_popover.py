"""달력 날짜 셀 옆에서 일정과 메모를 바로 저장하는 비모달 팝오버."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from chronofox.core.quick_input_parser import Draft, Kind, parse
from chronofox.ui.app_theme import PLAN_COLOR_CHOICES
from chronofox.ui.app_ui import app_font

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp


class _PopoverLineEdit(QLineEdit):
    escape_pressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


class CalendarQuickPopover(QFrame):
    """선택 날짜 문맥을 유지하는 260px 인라인 Quick Input."""

    WIDTH = 260
    HEIGHT = 126

    def __init__(self, app: FoxCalendarApp, parent: QWidget) -> None:
        super().__init__(parent)
        self.app = app
        self.day = date.today()
        self.anchor: QWidget | None = None
        self._draft: Draft | None = None
        self.setObjectName("calendarQuickPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedSize(self.WIDTH, self.HEIGHT)
        self.hide()
        self._build_ui()
        self.apply_theme()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 9)
        layout.setSpacing(6)

        self.input = _PopoverLineEdit()
        self.input.setObjectName("calendarQuickInput")
        self.input.setPlaceholderText(
            self.app.tr("calendar.quick.placeholder", "예: 오후 3시 회의 또는 메모")
        )
        self.input.setFont(app_font(10))
        self.input.textChanged.connect(self._refresh_preview)
        self.input.returnPressed.connect(self.save)
        self.input.escape_pressed.connect(self.hide)
        self.input.editingFinished.connect(self._schedule_focus_check)
        layout.addWidget(self.input)

        self.preview = QLabel()
        self.preview.setObjectName("calendarQuickPreview")
        self.preview.setFont(app_font(8))
        layout.addWidget(self.preview)

        self.error = QLabel()
        self.error.setObjectName("calendarQuickError")
        self.error.setFont(app_font(8, QFont.Bold))
        self.error.hide()
        layout.addWidget(self.error)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch()
        self.detail_button = QPushButton(
            self.app.tr("calendar.quick.details", "상세 일정에서 열기")
        )
        self.detail_button.setObjectName("calendarQuickDetails")
        self.detail_button.clicked.connect(self.open_details)
        row.addWidget(self.detail_button)
        layout.addLayout(row)

    def apply_theme(self) -> None:
        c = self.app.dialog_colors()
        self.setStyleSheet(
            f"QFrame#calendarQuickPopover {{ background: {c['panel']}; "
            f"border: 1px solid {c['border']}; border-radius: 9px; }}"
            f"QLineEdit#calendarQuickInput {{ background: {c['input_bg']}; color: {c['text']}; "
            f"border: 1px solid {c['input_border']}; border-radius: 6px; padding: 6px 8px; }}"
            f"QLineEdit#calendarQuickInput:focus {{ border-color: {c['accent']}; }}"
            f"QLabel#calendarQuickPreview {{ color: {c['muted']}; border: none; }}"
            f"QLabel#calendarQuickError {{ color: {c['holiday']}; border: none; }}"
            f"QPushButton#calendarQuickDetails {{ color: {c['accent']}; background: transparent; "
            "border: none; padding: 3px 0; font-weight: 600; }}"
        )

    def open_for(self, day: date, anchor: QWidget, text: str | None = "") -> None:
        self.day = day
        self.anchor = anchor
        self.error.hide()
        if text is not None:
            self.input.setText(text)
        self._refresh_preview()
        self.reposition()
        self.show()
        self.raise_()
        self.input.setFocus(Qt.PopupFocusReason)
        self.input.selectAll()

    def reposition(self) -> None:
        anchor = self.anchor
        parent = self.parentWidget()
        if anchor is None or parent is None:
            return
        below = anchor.mapTo(parent, QPoint(0, anchor.height() + 4))
        above_y = anchor.mapTo(parent, QPoint(0, 0)).y() - self.height() - 4
        x = below.x()
        y = below.y()
        if x + self.width() > parent.width() - 8:
            x = parent.width() - self.width() - 8
        if y + self.height() > parent.height() - 8:
            y = above_y
        self.move(max(8, x), max(8, y))

    def _parse_now(self) -> datetime:
        # 날짜 셀 문맥에서는 입력 시각이 이미 지났더라도 다음 날로 넘기지 않는다.
        return datetime.combine(self.day, time.min)

    def _refresh_preview(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            self._draft = None
            self.preview.setText(
                self.app.tr("calendar.quick.hint", "Enter로 저장 · Esc로 취소")
            )
            return
        self._draft = parse(raw, self._parse_now())
        if self._draft.kind in (Kind.PLAN, Kind.ALARM) and self._draft.start is not None:
            self.preview.setText(
                self.app.tr(
                    "calendar.quick.preview.plan",
                    "{date} {time} 일정",
                    date=f"{self._draft.start:%m.%d}",
                    time=f"{self._draft.start:%H:%M}",
                )
            )
        else:
            self.preview.setText(
                self.app.tr(
                    "calendar.quick.preview.note",
                    "{date} 메모",
                    date=f"{self.day:%m.%d}",
                )
            )

    def save(self) -> None:
        raw = self.input.text().strip()
        if not raw:
            self._show_error(
                self.app.tr("calendar.quick.error.empty", "내용을 입력해 주세요.")
            )
            return
        try:
            draft = self._draft or parse(raw, self._parse_now())
            title = draft.title.strip() or raw
            if draft.kind in (Kind.PLAN, Kind.ALARM) and draft.start is not None:
                self._save_plan(draft, title)
            else:
                existing = self.app.get_schedule(self.day)
                merged = f"{existing}\n{title}" if existing.strip() else title
                self.app.set_schedule(self.day, merged)
        except Exception:
            self._show_error(
                self.app.tr("calendar.quick.error.save", "저장하지 못했습니다. 다시 시도해 주세요.")
            )
            return
        self.hide()

    def _save_plan(self, draft: Draft, title: str) -> None:
        start = draft.start
        assert start is not None
        end = draft.end or start + timedelta(hours=1)
        self.app.add_plan(
            {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "kind": "day",
                "title": title,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "description": "",
                "color": PLAN_COLOR_CHOICES[0],
                "reminder_minutes": -1,
                "reminder_fired": "",
            }
        )

    def _show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()
        self.input.setFocus()

    def open_details(self) -> None:
        self.hide()
        self.app.open_schedule(self.day)

    def _schedule_focus_check(self) -> None:
        QTimer.singleShot(0, self._close_if_focus_left)

    def _close_if_focus_left(self) -> None:
        try:
            if not self.isVisible():
                return
            focused = QApplication.focusWidget()
            if focused is None or (focused is not self and not self.isAncestorOf(focused)):
                self.hide()
        except RuntimeError:
            return
