"""Detail-schedule 창의 저수준 그리기 위젯과 공유 상수/헬퍼.

EventBlock/TimeGrid/DayHeader/MiniCalendar는 모두 `window` 인자로 받은
DetailScheduleWindow(또는 그 믹스인들이 합쳐진 인스턴스)에 의존한다:
- `window.colors`(dict), `window.days`(list[date]), `window.day_index`(dict),
  `window.focused_day`(date), `window.lane_for(plan_id)`, `window.tr(...)`,
  `window.month_title(...)`, `window.weekday_initials()`, `window.edit_plan(...)`.

이 모듈이 소유한 GUTTER/HOUR_HEIGHT 등 상수와 stroke_icon/_hex_to_rgb/_parse_dt
헬퍼는 다른 detail_schedule 서브모듈에서도 재사용한다.
"""

from __future__ import annotations

import calendar as calendar_module
from datetime import date, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from chronofox.ui.app_ui import app_font, clear_layout

if TYPE_CHECKING:
    from .window import DetailScheduleWindow

GUTTER = 52
HOUR_HEIGHT = 46
START_HOUR = 0
END_HOUR = 24
SCROLLBAR_WIDTH = 10

WEEKDAY_KEYS = [
    ("calendar.weekday.mon", "월"),
    ("calendar.weekday.tue", "화"),
    ("calendar.weekday.wed", "수"),
    ("calendar.weekday.thu", "목"),
    ("calendar.weekday.fri", "금"),
    ("calendar.weekday.sat", "토"),
    ("calendar.weekday.sun", "일"),
]
WEEKDAY_KEYS_SUNDAY_FIRST = [
    ("calendar.weekday.sun", "일"),
    ("calendar.weekday.mon", "월"),
    ("calendar.weekday.tue", "화"),
    ("calendar.weekday.wed", "수"),
    ("calendar.weekday.thu", "목"),
    ("calendar.weekday.fri", "금"),
    ("calendar.weekday.sat", "토"),
]

ICON_PATHS: dict[str, str] = {
    "calendar": '<rect x="3" y="4" width="18" height="17" rx="2"/><path d="M3 9h18M8 2v4M16 2v4"/>',
    "tasks": '<circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/>',
    "focus": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/>',
    "analytics": '<path d="M5 20v-6M10 20v-11M15 20v-5M20 20v-13"/>',
    "archive": '<rect x="3" y="4" width="18" height="4" rx="1"/><path d="M5 8v12h14V8M10 12h4"/>',
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.2 9a2.8 2.8 0 015.6.3c0 1.9-2.8 2.5-2.8 2.5"/><path d="M12 17h.01"/>',
    "settings": '<circle cx="12" cy="12" r="3.2"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M19 5l-2 2M7 17l-2 2"/>',
    "logo": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "bell": '<path d="M6 9a6 6 0 1112 0c0 7 2 8 2 8H4s2-1 2-8"/><path d="M10 21a2 2 0 004 0"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/>',
    "chevron_left": '<path d="M15 6l-6 6 6 6"/>',
    "chevron_right": '<path d="M9 6l6 6-6 6"/>',
    "trend": '<polyline points="3 17 9 11 13 15 21 7"/><polyline points="16 7 21 7 21 12"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
}


def stroke_icon(name: str, color: str, size: int = 17, width: float = 1.8) -> QPixmap:
    """선(stroke) 스타일 아이콘 QPixmap을 그립니다."""
    inner = ICON_PATHS.get(name, "")
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">'
        f"{inner}</svg>"
    )
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    return pixmap


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = str(value or "").lstrip("#")
    if len(text) != 6:
        return (124, 108, 240)
    try:
        return tuple(int(text[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]
    except ValueError:
        return (124, 108, 240)


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


class EventBlock(QFrame):
    """시간 그리드 위에 올라가는 시간 일정 한 건입니다."""

    def __init__(self, window: DetailScheduleWindow, plan: dict, start_dt: datetime, end_dt: datetime) -> None:
        super().__init__(window.grid)
        c = window.colors
        self.window = window
        self.plan = plan
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.setCursor(Qt.PointingHandCursor)
        red, green, blue = _hex_to_rgb(plan.get("color", c["accent"]))
        accent = f"rgb({red},{green},{blue})"
        soft = f"rgba({red},{green},{blue},0.16)"
        self.setObjectName("eventBlock")
        self.setStyleSheet(
            f"QFrame#eventBlock {{ background: {soft}; border: none; border-left: 2px solid {accent}; "
            "border-radius: 5px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 6, 5)
        layout.setSpacing(1)
        time_label = QLabel(f"{start_dt:%H:%M} — {end_dt:%H:%M}")
        time_label.setFont(app_font(7))
        time_label.setStyleSheet(f"color: {accent}; background: transparent;")
        title_label = QLabel(plan.get("title", "") or window.tr("detail.untitled", "(제목 없음)"))
        title_label.setFont(app_font(8, QFont.Bold))
        title_label.setWordWrap(True)
        title_label.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        layout.addWidget(time_label)
        layout.addWidget(title_label)
        location = next((line.strip() for line in str(plan.get("description", "")).splitlines() if line.strip()), "")
        if location:
            loc_label = QLabel(location)
            loc_label.setFont(app_font(7))
            loc_label.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
            layout.addStretch()
            layout.addWidget(loc_label)
        else:
            layout.addStretch()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.window.edit_plan(self.plan, self.start_dt.date())
            event.accept()
            return
        super().mousePressEvent(event)


class TimeGrid(QWidget):
    """시/요일 격자선과 시간 라벨을 직접 그리는 본문 캔버스입니다."""

    def __init__(self, window: DetailScheduleWindow) -> None:
        super().__init__()
        self.window = window
        self.blocks: list[EventBlock] = []
        self.setMinimumHeight((END_HOUR - START_HOUR) * HOUR_HEIGHT)

    def column_width(self) -> float:
        """시간대 그리드에서 한 열(요일)의 너비를 계산합니다."""
        days = max(1, len(self.window.days))
        return max(1.0, (self.width() - GUTTER) / days)

    def clear_blocks(self) -> None:
        """그려진 일정 블록들을 모두 제거합니다."""
        for block in self.blocks:
            block.setParent(None)
            block.deleteLater()
        self.blocks = []

    def add_block(self, plan: dict, start_dt: datetime, end_dt: datetime) -> EventBlock:
        """시간대 그리드에 일정 블록을 추가합니다."""
        block = EventBlock(self.window, plan, start_dt, end_dt)
        self.blocks.append(block)
        block.show()
        return block

    def position_blocks(self) -> None:
        """겹치는 일정 블록들의 위치/폭을 계산해 배치합니다."""
        col_width = self.column_width()
        for block in self.blocks:
            day = block.start_dt.date()
            if day not in self.window.day_index:
                block.hide()
                continue
            col = self.window.day_index[day]
            lane, lane_count = self.window.lane_for(block.plan.get("id", ""))
            lane_count = max(1, lane_count)
            slot_width = (col_width - 6) / lane_count
            x = int(GUTTER + col * col_width + 3 + lane * slot_width)
            start_minutes = (block.start_dt.hour - START_HOUR) * 60 + block.start_dt.minute
            end_minutes = (block.end_dt.hour - START_HOUR) * 60 + block.end_dt.minute
            if block.end_dt.date() != day:
                end_minutes = (END_HOUR - START_HOUR) * 60
            y = int(start_minutes / 60 * HOUR_HEIGHT)
            height = max(22, int((end_minutes - start_minutes) / 60 * HOUR_HEIGHT) - 2)
            block.setGeometry(x, y, max(40, int(slot_width) - 3), height)
            block.show()

    def resizeEvent(self, event) -> None:
        self.position_blocks()
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        c = self.window.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        col_width = self.column_width()
        painter.setFont(app_font(8))
        for hour in range(START_HOUR, END_HOUR + 1):
            y = (hour - START_HOUR) * HOUR_HEIGHT
            painter.setPen(QPen(QColor(c["grid"]), 1))
            painter.drawLine(GUTTER, y, self.width(), y)
            if hour < END_HOUR:
                painter.setPen(QColor(c["faint"]))
                painter.drawText(6, y + 13, f"{hour:02}:00")
        for col in range(len(self.window.days) + 1):
            x = int(GUTTER + col * col_width)
            painter.setPen(QPen(QColor(c["grid"]), 1))
            painter.drawLine(x, 0, x, self.height())


class DayHeader(QWidget):
    """그리드 컬럼과 폭을 맞춰 요일/날짜를 그리는 상단 고정 헤더입니다."""

    def __init__(self, window: DetailScheduleWindow) -> None:
        super().__init__()
        self.window = window
        self.setFixedHeight(48)

    def paintEvent(self, _event) -> None:
        c = self.window.colors
        days = self.window.days
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        usable = max(1, self.width() - GUTTER - SCROLLBAR_WIDTH)
        col_width = usable / max(1, len(days))
        painter.setPen(QColor(c["faint"]))
        painter.setFont(app_font(7))
        painter.drawText(0, 28, GUTTER - 6, 14, Qt.AlignLeft | Qt.AlignVCenter, self.window.timezone_label())
        focused = self.window.focused_day
        today = date.today()
        for index, day in enumerate(days):
            x = GUTTER + index * col_width
            weekday_key, weekday_fallback = WEEKDAY_KEYS[day.weekday()]
            weekday_text = self.window.tr(weekday_key, weekday_fallback)
            weekend = day.weekday() >= 5
            label_color = QColor(c["fainter"] if weekend else c["muted2"])
            date_color = QColor(c["faint"] if weekend else c["text"])
            painter.setPen(label_color)
            painter.setFont(app_font(7, QFont.Bold))
            painter.drawText(int(x), 4, int(col_width), 14, Qt.AlignCenter, weekday_text.upper())
            painter.setPen(date_color)
            painter.setFont(app_font(15, QFont.Bold))
            painter.drawText(int(x), 18, int(col_width), 22, Qt.AlignCenter, str(day.day))
            if day == focused or (day == today and focused != today):
                painter.setBrush(QColor(c["accent"]))
                painter.setPen(Qt.NoPen)
                dot = 4
                painter.drawEllipse(int(x + col_width / 2 - dot / 2), 42, dot, dot)


class MiniCalendar(QWidget):
    """우측 패널의 작은 월 달력입니다."""

    def __init__(self, window: DetailScheduleWindow) -> None:
        super().__init__()
        self.window = window
        self.month_anchor = window.focused_day.replace(day=1)
        self.build()

    def build(self) -> None:
        """위젯을 구성합니다."""
        c = self.window.colors
        existing = self.layout()
        if existing is not None:
            clear_layout(existing)
            layout = existing
        else:
            layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel(self.window.month_title(self.month_anchor))
        title.setFont(app_font(10, QFont.Bold))
        title.setStyleSheet(f"color: {c['text_soft']};")
        prev_button = QPushButton()
        next_button = QPushButton()
        for button, icon in ((prev_button, "chevron_left"), (next_button, "chevron_right")):
            button.setIcon(QIcon(stroke_icon(icon, c["muted2"], 13, 2.0)))
            button.setFixedSize(18, 18)
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet("QPushButton { border: none; background: transparent; }")
        prev_button.clicked.connect(self.go_prev)
        next_button.clicked.connect(self.go_next)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(prev_button)
        header.addWidget(next_button)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(2)
        for col, initial in enumerate(self.window.weekday_initials()):
            label = QLabel(initial)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(7, QFont.Bold))
            label.setStyleSheet(f"color: {c['faint']};")
            grid.addWidget(label, 0, col)

        today = date.today()
        focused = self.window.focused_day
        weeks = calendar_module.Calendar(firstweekday=6).monthdatescalendar(self.month_anchor.year, self.month_anchor.month)
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                cell = QLabel(str(day.day))
                cell.setAlignment(Qt.AlignCenter)
                cell.setFixedHeight(22)
                cell.setFont(app_font(8, QFont.Bold if day == focused else QFont.Normal))
                if day == focused:
                    cell.setStyleSheet(
                        f"QLabel {{ background: {c['accent']}; color: #ffffff; border-radius: 11px; }}"
                    )
                elif day.month != self.month_anchor.month:
                    cell.setStyleSheet(f"color: {c['fainter']};")
                elif day == today:
                    cell.setStyleSheet(f"color: {c['accent']};")
                else:
                    cell.setStyleSheet(f"color: {c['muted']};")
                grid.addWidget(cell, row, col)
        layout.addLayout(grid)

    def go_prev(self) -> None:
        """이전 기간(일/주/월)으로 이동합니다."""
        month = self.month_anchor.month - 1 or 12
        year = self.month_anchor.year - (1 if self.month_anchor.month == 1 else 0)
        self.month_anchor = date(year, month, 1)
        self.build()

    def go_next(self) -> None:
        """다음 기간(일/주/월)으로 이동합니다."""
        month = self.month_anchor.month + 1
        year = self.month_anchor.year + (1 if month == 13 else 0)
        self.month_anchor = date(year, 1 if month == 13 else month, 1)
        self.build()

