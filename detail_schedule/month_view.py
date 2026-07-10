"""Detail-schedule 창의 월간(month) 뷰 빌더 믹스인.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어가 제공):
- `self.colors`(dict), `self.focused_day`(date)
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.plans_intersecting_day(day)` -> list[dict]
- `self.open_day(day)` (네비게이션, window.py 소유)
"""

from __future__ import annotations

import calendar as calendar_module
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app_ui import app_font

from .widgets import WEEKDAY_KEYS_SUNDAY_FIRST, _hex_to_rgb


class MonthViewMixin:
    """월간 그리드(달력 셀 + 칩) 구성을 담당합니다."""

    def build_month_view(self) -> QWidget:
        c = self.colors
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(0)
        for index, (key, fallback) in enumerate(WEEKDAY_KEYS_SUNDAY_FIRST):
            label = QLabel(self.tr(key, fallback))
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(8, QFont.Bold))
            weekend = index == 0 or index == 6
            label.setStyleSheet(f"color: {c['muted2'] if not weekend else c['faint']};")
            header.addWidget(label, 1)
        layout.addLayout(header)

        grid = QGridLayout()
        grid.setSpacing(6)
        weeks = calendar_module.Calendar(firstweekday=6).monthdatescalendar(self.focused_day.year, self.focused_day.month)
        for row, week in enumerate(weeks):
            grid.setRowStretch(row, 1)
            for col, day in enumerate(week):
                grid.addWidget(self.make_month_cell(day), row, col)
        for col in range(7):
            grid.setColumnStretch(col, 1)
        layout.addLayout(grid, 1)
        return container

    def make_month_cell(self, day: date) -> QFrame:
        c = self.colors
        is_other = day.month != self.focused_day.month
        is_today = day == date.today()
        is_selected = day == self.focused_day
        cell = QFrame()
        cell.setObjectName("monthCell")
        cell.setCursor(Qt.PointingHandCursor)
        cell.setMinimumHeight(72)
        border = c["accent"] if is_selected else c["grid"]
        bg = c["today_bg"] if is_today else (c["bg"] if is_other else c["panel"])
        cell.setStyleSheet(
            f"QFrame#monthCell {{ background: {bg}; border: 1px solid {border}; border-radius: 7px; }}"
        )
        layout = QVBoxLayout(cell)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(3)
        num = QLabel(str(day.day))
        num.setFont(app_font(9, QFont.Bold))
        if is_other:
            num_color = c["fainter"]
        elif is_today:
            num_color = c["accent"]
        elif day.weekday() >= 5:
            num_color = c["muted"]
        else:
            num_color = c["text"]
        num.setStyleSheet(f"color: {num_color}; background: transparent;")
        layout.addWidget(num)

        plans = self.plans_intersecting_day(day)
        for plan in plans[:3]:
            layout.addWidget(self.make_month_chip(plan))
        if len(plans) > 3:
            more = QLabel(self.tr("detail.month.more", "+{count}", count=len(plans) - 3))
            more.setFont(app_font(7, QFont.Bold))
            more.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
            layout.addWidget(more)
        layout.addStretch()
        cell.mousePressEvent = lambda _event, d=day: self.open_day(d)  # type: ignore[assignment]
        return cell

    def make_month_chip(self, plan: dict) -> QLabel:
        c = self.colors
        red, green, blue = _hex_to_rgb(plan.get("color", c["accent"]))
        chip = QLabel(plan.get("title", "") or self.tr("detail.untitled", "(제목 없음)"))
        chip.setFont(app_font(7, QFont.Bold))
        chip.setFixedHeight(16)
        chip.setStyleSheet(
            f"QLabel {{ background: rgba({red},{green},{blue},0.20); color: {c['text_soft']}; "
            f"border-left: 2px solid rgb({red},{green},{blue}); border-radius: 3px; padding: 0 5px; }}"
        )
        return chip
