"""반복 주기에 맞춘 완료 기록 보기와 명시적 완료 취소 팝업."""

from __future__ import annotations

import calendar
from datetime import date, datetime

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.task_logic import recurrence_available_on
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_ui import app_font, clear_layout

from .widgets import WEEKDAY_KEYS


def _completed_day(record: dict) -> date | None:
    try:
        return date.fromisoformat(str(record.get("completed_at") or "")[:10])
    except ValueError:
        return None


def _calculate_streak(records: list[dict]) -> int:
    completed_days = set()
    for r in records:
        day = _completed_day(r)
        if day:
            completed_days.add(day)
    if not completed_days:
        return 0
    today = date.today()
    check = today if today in completed_days else today - date.resolution
    streak = 0
    while check in completed_days:
        streak += 1
        check -= date.resolution
    return streak


class TaskHistoryPopup(TrMixin, QWidget):
    """반복 주기에 맞춘 완료 기록 보기와 명시적 완료 취소 팝업."""

    def __init__(self, owner: QWidget, task: dict) -> None:
        super().__init__(owner, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.owner = owner
        self.app = owner.app
        self.colors = dict(owner.colors)
        self.task_id = str(task.get("id", ""))
        self.task_text = str(task.get("text", ""))
        self.period = (task.get("recurrence") or {}).get("period", "daily")
        self.records = self.app.task_service.completion_history(self.task_id)
        self.anchor = next((self._record_date(row) for row in self.records if self._record_date(row)), date.today())
        if self.period == "weekly":
            self.anchor = date(self.anchor.isocalendar().year, 7, 1)
        self.selected_range: tuple[date, date] | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("taskHistoryPopup")
        self.setWindowTitle(self.tr("todo.history.title", "완료 기록"))
        self.resize(400, 530)
        self.setMinimumSize(310, 380)

        c = self.colors
        is_dark = (
            self.app.store.get("theme") == "dark"
            or QColor(c.get("bg", "#ffffff")).lightness() < 128
        )

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(10, 10, 10, 10)
        outer_layout.setSpacing(0)

        self.card = QFrame()
        self.card.setObjectName("popupCard")
        outer_layout.addWidget(self.card)

        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 140 if is_dark else 65))
        self.card.setGraphicsEffect(shadow)

        card_bg = c["bg"] if is_dark else "#FFFFFF"
        card_border = c["border"] if is_dark else "#CBD5E1"
        self.setStyleSheet(
            f"QWidget#taskHistoryPopup {{ background: transparent; }}"
            f"QFrame#popupCard {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 16px; }}"
            f"QScrollArea, QScrollArea > QWidget > QWidget, QScrollArea QWidget#qt_scrollarea_viewport {{ background: {card_bg}; border: none; }}"
            f"QLabel {{ color: {c['text_soft']}; background: transparent; }}"
            f"QPushButton {{ color: {c['text_soft']}; background: {c['panel2']}; "
            f"border: 1px solid {c['border']}; border-radius: 8px; padding: 6px; font-weight: 500; }}"
            f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; color: {c['text']}; }}"
            f"QPushButton#historySlot {{ border-radius: 8px; }}"
            f"QPushButton#cancelCompletion {{ background: transparent; color: #ef4444; border: 1px solid #fca5a5; "
            f"border-radius: 6px; padding: 4px 10px; font-size: 11px; font-weight: 600; }}"
            f"QPushButton#cancelCompletion:hover {{ background: rgba(239, 68, 68, 0.1); border-color: #ef4444; }}"
        )
        root = QVBoxLayout(self.card)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)

        # Header: Title + Period Badge
        header_row = QHBoxLayout()
        heading = QLabel(self.tr("todo.history.title", "완료 기록"))
        heading.setFont(app_font(12, QFont.Bold))
        heading.setStyleSheet(f"color: {c['text']};")
        header_row.addWidget(heading)

        period_key_map = {
            "daily": ("todo.history.period_daily", "매일 반복"),
            "weekly": ("todo.history.period_weekly", "매주 반복"),
            "monthly": ("todo.history.period_monthly", "매월 반복"),
            "quarterly": ("todo.history.period_quarterly", "매 분기 반복"),
            "yearly": ("todo.history.period_yearly", "매년 반복"),
        }
        p_key, p_fallback = period_key_map.get(self.period, ("todo.history.period_daily", "매일 반복"))
        period_badge = QLabel(self.tr(p_key, p_fallback))
        period_badge.setFont(app_font(9, QFont.Bold))
        period_badge.setStyleSheet(
            f"background: {c['panel2']}; color: {c['accent']}; "
            f"border: 1px solid {c['border']}; border-radius: 9px; padding: 2px 8px;"
        )
        header_row.addWidget(period_badge)
        header_row.addStretch()
        root.addLayout(header_row)

        # Task Text
        title = QLabel(self.task_text)
        title.setWordWrap(True)
        title.setFont(app_font(10))
        title.setStyleSheet(f"color: {c['text_soft']};")
        root.addWidget(title)

        # Stats Card (Streak & Total)
        self.stats_card = QLabel()
        self.stats_card.setTextFormat(Qt.RichText)
        self.stats_card.setFont(app_font(9, QFont.DemiBold))
        self.stats_card.setStyleSheet(
            f"background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px; "
            f"padding: 6px 10px; color: {c['text']};"
        )
        root.addWidget(self.stats_card)

        # Navigation Bar
        nav = QHBoxLayout()
        nav.setSpacing(6)
        previous = QPushButton("‹")
        previous.setAccessibleName(self.tr("todo.history.previous", "이전 기간"))
        previous.clicked.connect(lambda: self.move_period(-1))
        previous.setFixedSize(30, 28)
        previous.setCursor(Qt.PointingHandCursor)

        self.period_label = QLabel()
        self.period_label.setAlignment(Qt.AlignCenter)
        self.period_label.setFont(app_font(11, QFont.Bold))
        self.period_label.setStyleSheet(f"color: {c['text']};")

        following = QPushButton("›")
        following.setAccessibleName(self.tr("todo.history.next", "다음 기간"))
        following.clicked.connect(lambda: self.move_period(1))
        following.setFixedSize(30, 28)
        following.setCursor(Qt.PointingHandCursor)

        nav.addWidget(previous)
        nav.addWidget(self.period_label, 1)
        nav.addWidget(following)
        root.addLayout(nav)

        # Main Slot Grid Scroll Area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        body = QVBoxLayout(content)
        body.setContentsMargins(0, 0, 4, 0)
        self.slots = QGridLayout()
        self.slots.setSpacing(4)
        body.addLayout(self.slots)
        body.addStretch()
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        # Detail Scroll Area
        details_scroll = QScrollArea()
        details_scroll.setWidgetResizable(True)
        details_scroll.setFrameShape(QFrame.NoFrame)
        details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        details_scroll.setMinimumHeight(68)
        details_scroll.setMaximumHeight(110)
        details = QWidget()
        self.record_details = QVBoxLayout(details)
        self.record_details.setContentsMargins(6, 6, 6, 6)
        self.record_details.setSpacing(4)
        details.setStyleSheet(
            f"background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 8px;"
        )
        details_scroll.setWidget(details)
        root.addWidget(details_scroll)

        # Hint & Close
        hint = QLabel(self.tr("todo.history.neutral", "빈 칸은 완료 기록이 없다는 뜻입니다."))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {c['muted2']}; font-size: 10px;")
        root.addWidget(hint)

        close = QPushButton(self.tr("common.close", "닫기"))
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close)
        close.setStyleSheet(
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; "
            f"border: 1px solid {c['border']}; border-radius: 8px; padding: 7px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
        )
        root.addWidget(close)

        self.refresh()

    def show_at(self, anchor: QWidget) -> None:
        """앵커 근처에서 화면 경계를 넘지 않게 표시합니다."""
        screen = anchor.screen()
        area = screen.availableGeometry()
        self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
        point = anchor.mapToGlobal(QPoint(0, anchor.height()))
        self.move(max(area.left(), min(point.x() - 10, area.right() - self.width() + 1)),
                  max(area.top(), min(point.y() - 6, area.bottom() - self.height() + 1)))
        self.show()

    def move_period(self, direction: int) -> None:
        if self.period == "daily":
            serial = self.anchor.year * 12 + self.anchor.month - 1 + direction
            year, month = divmod(serial, 12)
            if not 1 <= year <= 9999:
                return
            self.anchor = date(year, month + 1, 1)
        else:
            year = self.anchor.year + direction * (10 if self.period == "yearly" else 1)
            if not 1 <= year <= 9999:
                return
            self.anchor = date(year, 1, 1)
        self.selected_range = None
        self.refresh()

    def refresh(self) -> None:
        self.records = self.app.task_service.completion_history(self.task_id)
        self._update_stats_card()
        clear_layout(self.slots)
        if self.period == "daily":
            self._daily_slots()
        elif self.period == "weekly":
            self._weekly_slots()
        elif self.period in {"monthly", "quarterly"}:
            self._month_slots()
        else:
            self._year_slots()
        if self.selected_range is not None:
            self.select_range(*self.selected_range)
        else:
            clear_layout(self.record_details)
            text = self.tr("todo.history.select", "표시된 기간을 선택하면 완료 날짜와 시간을 볼 수 있습니다.")
            if not self.records:
                text = self.tr("todo.history.empty", "저장된 완료 기록이 없습니다.")
            label = QLabel(text)
            label.setWordWrap(True)
            label.setStyleSheet("color: " + self.colors["muted"] + "; font-size: 11px;")
            self.record_details.addWidget(label)

    def _update_stats_card(self) -> None:
        total_count = len(self.records)
        c_total = self.tr("todo.history.total", "총 {count}회 완료", count=total_count)
        if self.period == "daily":
            streak = _calculate_streak(self.records)
            if streak > 0:
                s_text = self.tr("todo.history.streak", "{count}일 연속 달성", count=streak)
                self.stats_card.setText(
                    f"<span style='color: {self.colors['accent']}; font-weight: 700;'>● {s_text}</span>"
                    f"&nbsp;&nbsp;·&nbsp;&nbsp;<span>{c_total}</span>"
                )
                return
        self.stats_card.setText(f"<span>● {c_total}</span>")

    def _record_date(self, record: dict) -> date | None:
        if self.period == "daily":
            return _completed_day(record)
        return recurrence_available_on(record) or _completed_day(record)

    def _matching(self, start: date, end: date) -> list[dict]:
        return [record for record in self.records if (day := self._record_date(record)) is not None and start <= day <= end]

    def _slot(self, text: str, start: date, end: date, row: int, col: int = 0) -> None:
        records = self._matching(start, end)
        button = QPushButton(f"{text}  ✓" if records else text)
        button.setObjectName("historySlot")
        button.setProperty("recordCount", len(records))
        button.setCursor(Qt.PointingHandCursor)
        button.setAccessibleName(self.tr("todo.history.slot", "{period}: 완료 기록 {count}개", period=text, count=len(records)))
        c = self.colors
        if records:
            button.setStyleSheet(
                f"background: {c['today_bg']}; color: {c['accent']}; "
                f"border: 1.5px solid {c['accent']}; font-weight: bold; border-radius: 8px;"
            )
        else:
            button.setStyleSheet(
                f"background: {c['panel2']}; color: {c['text_soft']}; "
                f"border: 1px solid {c['border']}; border-radius: 8px; font-weight: 500;"
            )
        if self.period == "daily":
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            button.setFont(app_font(9))
            button.setStyleSheet(button.styleSheet() + "padding: 5px 0; min-height: 28px;")
        elif self.period == "weekly":
            button.setFont(app_font(8))
            button.setStyleSheet(button.styleSheet() + "padding: 4px 6px; min-height: 26px;")
        elif self.period in {"monthly", "quarterly"}:
            button.setFont(app_font(9, QFont.DemiBold))
            button.setStyleSheet(button.styleSheet() + "padding: 8px 4px; min-height: 36px;")
        elif self.period == "yearly":
            button.setFont(app_font(9))
            button.setStyleSheet(button.styleSheet() + "padding: 6px 4px; min-height: 30px;")

        button.clicked.connect(lambda _checked=False, first=start, last=end: self.select_range(first, last))
        self.slots.addWidget(button, row, col)

    def _daily_slots(self) -> None:
        year, month = self.anchor.year, self.anchor.month
        self.period_label.setText(f"{year}-{month:02d}")
        first_weekday = self.app.store.get("calendar_first_weekday", 0)
        first_weekday = first_weekday if first_weekday in (0, 6) else 0
        c = self.colors
        for col in range(7):
            weekday_idx = (col + first_weekday) % 7
            key, fallback = WEEKDAY_KEYS[weekday_idx]
            label = QLabel(self.tr(key, fallback))
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(9, QFont.Bold))
            if weekday_idx == 6:  # Sunday
                label.setStyleSheet(f"color: {c.get('danger', '#ef4444')}; padding-bottom: 2px;")
            elif weekday_idx == 5:  # Saturday
                label.setStyleSheet(f"color: {c.get('saturday', '#3b82f6')}; padding-bottom: 2px;")
            else:
                label.setStyleSheet(f"color: {c['muted']}; padding-bottom: 2px;")
            self.slots.addWidget(label, 0, col)

        for row, days in enumerate(calendar.Calendar(first_weekday).monthdayscalendar(year, month), 1):
            for col, number in enumerate(days):
                if number:
                    day = date(year, month, number)
                    self._slot(str(number), day, day, row, col)

    def _weekly_slots(self) -> None:
        year = self.anchor.year
        self.period_label.setText(str(year))
        final_week = date(year, 12, 28).isocalendar().week
        # 2-column card deck layout for 52/53 weeks
        for week in range(1, final_week + 1):
            start = date.fromisocalendar(year, week, 1)
            end = date.fromordinal(min(start.toordinal() + 6, date.max.toordinal()))
            text = f"{week}주 ({start:%m.%d}~{end:%m.%d})"
            row = (week - 1) // 2
            col = (week - 1) % 2
            self._slot(text, start, end, row, col)

    def _month_slots(self) -> None:
        year = self.anchor.year
        self.period_label.setText(str(year))
        quarterly = self.period == "quarterly"
        for index in range(4 if quarterly else 12):
            month = index * 3 + 1 if quarterly else index + 1
            end_month = month + 2 if quarterly else month
            first = date(year, month, 1)
            last = date(year, end_month, calendar.monthrange(year, end_month)[1])
            text = (self.tr("todo.history.quarter", "{n}분기", n=index + 1) if quarterly
                    else self.tr("todo.history.month", "{n}월", n=month))
            columns = 2 if quarterly else 3
            self._slot(text, first, last, index // columns, index % columns)

    def _year_slots(self) -> None:
        first = max(1, self.anchor.year // 10 * 10)
        last = min(9999, first + 9)
        self.period_label.setText(f"{first} — {last}")
        c = self.colors

        # Decade Progress Card (Yearly B안)
        decade_years = set(range(first, last + 1))
        completed_years = {
            d.year for r in self.records if (d := self._record_date(r)) and d.year in decade_years
        }
        count_in_decade = len(completed_years)
        pct = int((count_in_decade / 10.0) * 100)

        progress_card = QFrame()
        progress_card.setObjectName("decadeProgressCard")
        progress_card.setStyleSheet(
            f"QFrame#decadeProgressCard {{ "
            f"background: {c['today_bg']}; "
            f"border: 1px solid {c['border']}; "
            f"border-radius: 10px; }}"
        )
        p_layout = QVBoxLayout(progress_card)
        p_layout.setContentsMargins(12, 10, 12, 10)
        p_layout.setSpacing(6)

        p_info_row = QHBoxLayout()
        p_info_row.setContentsMargins(0, 0, 0, 0)
        p_title = QLabel(self.tr("todo.history.decade_title", "{first} — {last} 달성률", first=first, last=last))
        p_title.setFont(app_font(9, QFont.Bold))
        p_title.setStyleSheet(f"color: {c['accent']};")
        p_info_row.addWidget(p_title)

        p_ratio = QLabel(f"{count_in_decade} / 10년 ({pct}%)")
        p_ratio.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        p_ratio.setFont(app_font(9, QFont.DemiBold))
        p_ratio.setStyleSheet(f"color: {c['text_soft']};")
        p_info_row.addWidget(p_ratio)

        p_layout.addLayout(p_info_row)

        p_bar = QProgressBar()
        p_bar.setTextVisible(False)
        p_bar.setFixedHeight(6)
        p_bar.setRange(0, 100)
        p_bar.setValue(pct)
        p_bar.setStyleSheet(
            f"QProgressBar {{ background: {c['panel2']}; border: none; border-radius: 3px; max-height: 6px; }}"
            f"QProgressBar::chunk {{ background: {c['accent']}; border-radius: 3px; }}"
        )
        p_layout.addWidget(p_bar)

        self.slots.addWidget(progress_card, 0, 0, 1, 5)

        # 10-Year Cubes (5 columns x 2 rows)
        today_year = date.today().year
        for idx, year in enumerate(range(first, last + 1)):
            row = 1 + idx // 5
            col = idx % 5
            self._year_cube_slot(year, today_year, row, col)

    def _year_cube_slot(self, year: int, today_year: int, row: int, col: int) -> None:
        start = date(year, 1, 1)
        end = date(year, 12, 31)
        records = self._matching(start, end)
        c = self.colors

        button = QPushButton()
        button.setObjectName("historySlot")
        button.setProperty("recordCount", len(records))
        button.setCursor(Qt.PointingHandCursor)
        button.setFont(app_font(10))
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        button.setAccessibleName(
            self.tr("todo.history.slot", "{period}: 완료 기록 {count}개", period=str(year), count=len(records))
        )

        if records:
            button.setText(f"{year}\n✓")
            button.setStyleSheet(
                f"QPushButton#historySlot {{ "
                f"background: {c['today_bg']}; color: {c['accent']}; "
                f"border: 1.5px solid {c['accent']}; border-radius: 10px; "
                f"padding: 6px 2px; min-height: 50px; font-weight: bold; }}"
                f"QPushButton#historySlot:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
            )
        elif year == today_year:
            this_year_label = self.tr("todo.history.this_year", "올해")
            button.setText(f"{year}\n{this_year_label}")
            button.setStyleSheet(
                f"QPushButton#historySlot {{ "
                f"background: {c['today_bg']}; color: {c['accent']}; "
                f"border: 2px solid {c['accent']}; border-radius: 10px; "
                f"padding: 6px 2px; min-height: 50px; font-weight: bold; }}"
                f"QPushButton#historySlot:hover {{ background: {c['hover']}; }}"
            )
        elif year > today_year:
            button.setText(f"{year}\n—")
            button.setStyleSheet(
                f"QPushButton#historySlot {{ "
                f"background: {c['panel2']}; color: {c['muted2']}; "
                f"border: 1px solid {c['border']}; border-radius: 10px; "
                f"padding: 6px 2px; min-height: 50px; font-weight: 500; }}"
                f"QPushButton#historySlot:hover {{ background: {c['hover']}; }}"
            )
        else:
            button.setText(f"{year}\n—")
            button.setStyleSheet(
                f"QPushButton#historySlot {{ "
                f"background: {c['panel2']}; color: {c['text_soft']}; "
                f"border: 1px solid {c['border']}; border-radius: 10px; "
                f"padding: 6px 2px; min-height: 50px; font-weight: 500; }}"
                f"QPushButton#historySlot:hover {{ background: {c['hover']}; border-color: {c['accent']}; }}"
            )

        button.clicked.connect(lambda _checked=False, first=start, last=end: self.select_range(first, last))
        self.slots.addWidget(button, row, col)

    def select_range(self, start: date, end: date) -> None:
        self.selected_range = (start, end)
        clear_layout(self.record_details)
        records = self._matching(start, end)
        if not records:
            label = QLabel(self.tr("todo.history.empty", "저장된 완료 기록이 없습니다."))
            label.setWordWrap(True)
            label.setStyleSheet("color: " + self.colors["muted"] + "; font-size: 11px;")
            self.record_details.addWidget(label)
            return

        for record in records:
            raw = str(record.get("completed_at") or "")
            try:
                stamp = datetime.fromisoformat(raw).isoformat(sep=" ", timespec="seconds")
            except ValueError:
                stamp = raw

            row_layout = QHBoxLayout()
            row_layout.setContentsMargins(2, 2, 2, 2)
            row_layout.setSpacing(6)

            label = QLabel(self.tr("todo.history.completed_at", "완료: {value}", value=stamp))
            label.setWordWrap(True)
            label.setFont(app_font(9, QFont.DemiBold))
            label.setStyleSheet(f"color: {self.colors['text']};")
            row_layout.addWidget(label, 1)

            cancel = QPushButton(self.tr("todo.history.cancel", "이 완료 기록 취소"))
            cancel.setObjectName("cancelCompletion")
            cancel.setCursor(Qt.PointingHandCursor)
            task_id = str(record.get("id", ""))
            cancel.clicked.connect(lambda _checked=False, record_id=task_id: self.cancel_record(record_id))
            row_layout.addWidget(cancel)

            row_widget = QWidget()
            row_widget.setLayout(row_layout)
            self.record_details.addWidget(row_widget)

    def cancel_record(self, task_id: str) -> None:
        self.app.task_service.set_complete(task_id, False)
        self.refresh()

    def closeEvent(self, event) -> None:
        if getattr(self.owner, "task_history_popup", None) is self:
            self.owner.task_history_popup = None
        super().closeEvent(event)
