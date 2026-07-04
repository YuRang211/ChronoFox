from __future__ import annotations

import calendar as calendar_module
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app_constants import APP_NAME, APP_NAME_EN
from app_i18n import translate
from app_theme import resolved_theme_mode
from app_ui import app_font, clear_layout, geometry_string, parse_geometry
from app_widgets import RoundedWindow
from schedule_window import PlanWindow
from todo_window import RepeatWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp


# Dark palette taken from the ChronoFox "Weekly Schedule View" design mockup.
DESIGN_DARK: dict[str, str] = {
    "bg": "#0a0a0c",
    "sidebar": "#0c0c0f",
    "panel": "#121215",
    "panel2": "#17171b",
    "hover": "#141418",
    "border": "#1b1b1f",
    "border_soft": "#161619",
    "grid": "#1c1c20",
    "text": "#ececef",
    "text_soft": "#dadade",
    "muted": "#7e7e86",
    "muted2": "#6a6a72",
    "faint": "#5a5a62",
    "fainter": "#3c3c44",
    "accent": "#60a5fa",
    "accent_hover": "#3b82f6",
    "card": "#121215",
    "card_border": "#1e1e22",
    "pill": "#ececef",
    "pill_text": "#16161c",
    "upgrade": "#dad6ec",
    "today_bg": "#131c2e",
}

# Light variant of the same design so the tab follows the app theme.
DESIGN_LIGHT: dict[str, str] = {
    "bg": "#ffffff",
    "sidebar": "#f6f6f8",
    "panel": "#ffffff",
    "panel2": "#ececef",
    "hover": "#f1f1f4",
    "border": "#e2e2e7",
    "border_soft": "#ececef",
    "grid": "#e9e9ee",
    "text": "#16161c",
    "text_soft": "#33333a",
    "muted": "#6a6a72",
    "muted2": "#8a8a92",
    "faint": "#a6a6ae",
    "fainter": "#c8c8d0",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "card": "#f7f7f9",
    "card_border": "#e6e6ea",
    "pill": "#16161c",
    "pill_text": "#ffffff",
    "upgrade": "#dad6ec",
    "today_bg": "#e8f1ff",
}

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


def design_palette(config: dict) -> dict[str, str]:
    mode = resolved_theme_mode(config)
    return dict(DESIGN_LIGHT if mode == "light" else DESIGN_DARK)


def stroke_icon(name: str, color: str, size: int = 17, width: float = 1.8) -> QPixmap:
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
        days = max(1, len(self.window.days))
        return max(1.0, (self.width() - GUTTER) / days)

    def clear_blocks(self) -> None:
        for block in self.blocks:
            block.setParent(None)
            block.deleteLater()
        self.blocks = []

    def add_block(self, plan: dict, start_dt: datetime, end_dt: datetime) -> EventBlock:
        block = EventBlock(self.window, plan, start_dt, end_dt)
        self.blocks.append(block)
        block.show()
        return block

    def position_blocks(self) -> None:
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
        month = self.month_anchor.month - 1 or 12
        year = self.month_anchor.year - (1 if self.month_anchor.month == 1 else 0)
        self.month_anchor = date(year, month, 1)
        self.build()

    def go_next(self) -> None:
        month = self.month_anchor.month + 1
        year = self.month_anchor.year + (1 if month == 13 else 0)
        self.month_anchor = date(year, 1 if month == 13 else month, 1)
        self.build()

    def sync_anchor(self) -> None:
        self.month_anchor = self.window.focused_day.replace(day=1)
        self.build()


class DetailScheduleWindow(RoundedWindow):
    """디자인 시안을 그대로 옮긴 세부 일정(일/주/월) 관리 창입니다."""

    # 활성 기능을 먼저, 아직 준비 중인(비활성) 항목을 뒤에 둔다.
    NAV_ITEMS = [
        ("calendar", "detail.nav.calendar", "달력", "calendar"),
        ("tasks", "detail.nav.tasks", "해야 할 일", "tasks"),
        ("archive", "detail.nav.archive", "보관", "archive"),
        ("focus", "detail.nav.focus", "집중", "focus"),
        ("analytics", "detail.nav.analytics", "분석", "analytics"),
    ]
    DISABLED_NAV = {"focus", "analytics"}

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(design_palette(app.config), radius=16)
        self.app = app
        self.draw_window_border = True
        self.view_mode = app.config.get("detail_view_mode", "week")
        if self.view_mode not in {"day", "week", "month"}:
            self.view_mode = "week"
        self.section = "calendar"
        self.task_filter = "all"
        self.focused_day = date.today()
        self.days: list[date] = []
        self.day_index: dict[date, int] = {}
        self.lanes: dict[str, tuple[int, int]] = {}
        self.plan_window: PlanWindow | None = None
        self.mini_calendar: MiniCalendar | None = None
        self.setWindowTitle(self.window_title_text())
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("detail_geometry", "1040x720+120+50"), (1040, 720, 120, 50))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(960, 620)
        self.build_ui()

    # i18n -----------------------------------------------------------------
    def tr(self, key: str, fallback: str = "", **format_values) -> str:
        text = translate(self.app.config.get("language", "ko"), key, fallback)
        if not format_values:
            return text
        try:
            return text.format(**format_values)
        except (KeyError, IndexError, ValueError):
            return fallback or key

    def window_title_text(self) -> str:
        return self.tr("detail.window.title", "{app} 세부 일정", app=self.tr("app.name", APP_NAME))

    def timezone_label(self) -> str:
        offset = datetime.now().astimezone().utcoffset() or timedelta()
        hours = int(offset.total_seconds() // 3600)
        return f"GMT{hours:+d}"

    def month_title(self, month: date) -> str:
        month_name = self.tr(f"calendar.month.{month.month}", str(month.month))
        return self.tr("calendar.month_title", "{year}년 {month}").format(year=month.year, month=month_name)

    def weekday_initials(self) -> list[str]:
        return [self.tr(key, fb)[0] for key, fb in WEEKDAY_KEYS_SUNDAY_FIRST]

    # range math -----------------------------------------------------------
    def compute_days(self) -> None:
        if self.view_mode == "day":
            self.days = [self.focused_day]
        elif self.view_mode == "month":
            first = self.focused_day.replace(day=1)
            count = calendar_module.monthrange(first.year, first.month)[1]
            self.days = [first + timedelta(days=offset) for offset in range(count)]
        else:
            monday = self.focused_day - timedelta(days=self.focused_day.weekday())
            self.days = [monday + timedelta(days=offset) for offset in range(7)]
        self.day_index = {day: index for index, day in enumerate(self.days)}

    def range_label(self) -> str:
        if self.view_mode == "month":
            return self.month_title(self.focused_day)
        if not self.days:
            return ""
        if self.view_mode == "day":
            day = self.days[0]
            return self.tr("detail.range.day", "{year}.{month:02}.{day:02}", year=day.year, month=day.month, day=day.day)
        start, end = self.days[0], self.days[-1]
        if start.month == end.month:
            return self.tr(
                "detail.range.week_same_month",
                "{year}.{month:02}.{start_day:02} - {end_day:02}",
                year=start.year, month=start.month, start_day=start.day, end_day=end.day,
            )
        return self.tr(
            "detail.range.week",
            "{start_month:02}.{start_day:02} - {end_month:02}.{end_day:02}",
            start_month=start.month, start_day=start.day, end_month=end.month, end_day=end.day,
        )

    # plan helpers ---------------------------------------------------------
    def timed_plans_for_day(self, day: date) -> list[tuple[dict, datetime, datetime]]:
        rows: list[tuple[dict, datetime, datetime]] = []
        for plan in self.app.data.setdefault("plans", []):
            if plan.get("kind") == "long":
                continue
            start_dt = _parse_dt(plan.get("start", ""))
            if start_dt is None or start_dt.date() != day:
                continue
            end_dt = _parse_dt(plan.get("end", "")) or (start_dt + timedelta(hours=1))
            if end_dt <= start_dt:
                end_dt = start_dt + timedelta(minutes=30)
            rows.append((plan, start_dt, end_dt))
        rows.sort(key=lambda row: row[1])
        return rows

    def all_day_plans_for_day(self, day: date) -> list[dict]:
        rows: list[dict] = []
        for plan in self.app.data.setdefault("plans", []):
            if plan.get("kind") != "long":
                continue
            start_dt = _parse_dt(plan.get("start", ""))
            end_dt = _parse_dt(plan.get("end", "")) or start_dt
            if start_dt is None or end_dt is None:
                continue
            if start_dt.date() <= day <= end_dt.date():
                rows.append(plan)
        return rows

    def plans_intersecting_day(self, day: date) -> list[dict]:
        rows: list[tuple[dict, datetime]] = []
        for plan in self.app.data.setdefault("plans", []):
            start_dt = _parse_dt(plan.get("start", ""))
            end_dt = _parse_dt(plan.get("end", "")) or start_dt
            if start_dt is None or end_dt is None:
                continue
            if start_dt.date() <= day <= end_dt.date():
                rows.append((plan, start_dt))
        rows.sort(key=lambda row: row[1])
        return [plan for plan, _ in rows]

    def compute_lanes(self) -> None:
        self.lanes = {}
        for day in self.days:
            events = self.timed_plans_for_day(day)
            cluster: list[tuple[dict, datetime, datetime]] = []
            cluster_end: datetime | None = None
            for plan, start_dt, end_dt in events:
                if cluster_end is not None and start_dt >= cluster_end:
                    self._assign_cluster_lanes(cluster)
                    cluster = []
                    cluster_end = None
                cluster.append((plan, start_dt, end_dt))
                cluster_end = end_dt if cluster_end is None else max(cluster_end, end_dt)
            self._assign_cluster_lanes(cluster)

    def _assign_cluster_lanes(self, cluster: list[tuple[dict, datetime, datetime]]) -> None:
        if not cluster:
            return
        lane_ends: list[datetime] = []
        assignments: dict[str, int] = {}
        for plan, start_dt, end_dt in cluster:
            placed = None
            for index, lane_end in enumerate(lane_ends):
                if start_dt >= lane_end:
                    lane_ends[index] = end_dt
                    placed = index
                    break
            if placed is None:
                placed = len(lane_ends)
                lane_ends.append(end_dt)
            assignments[str(plan.get("id", id(plan)))] = placed
        lane_count = len(lane_ends)
        for plan, _start_dt, _end_dt in cluster:
            key = str(plan.get("id", id(plan)))
            self.lanes[key] = (assignments[key], lane_count)

    def lane_for(self, plan_id) -> tuple[int, int]:
        return self.lanes.get(str(plan_id), (0, 1))

    def upcoming_plans(self, limit: int = 5) -> list[tuple[dict, datetime]]:
        now = datetime.now()
        rows: list[tuple[dict, datetime]] = []
        for plan in self.app.data.setdefault("plans", []):
            start_dt = _parse_dt(plan.get("start", ""))
            if start_dt is None or start_dt < now:
                continue
            rows.append((plan, start_dt))
        rows.sort(key=lambda row: row[1])
        return rows[:limit]

    def view_event_count(self) -> int:
        return sum(len(self.timed_plans_for_day(day)) for day in self.days)

    # build ----------------------------------------------------------------
    def build_ui(self) -> None:
        existing = self.layout()
        if existing is None:
            root = QHBoxLayout(self)
        else:
            clear_layout(existing)
            root = existing
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 이전 빌드의 위젯 참조를 비워 삭제된 위젯을 다시 건드리지 않도록 한다.
        for attr in ("grid", "day_header", "all_day_row", "all_day_layout", "empty_hint", "scroll_area", "tasks_box", "archive_box"):
            self.__dict__.pop(attr, None)
        self.mini_calendar = None
        self.compute_days()
        self.compute_lanes()

        root.addWidget(self.build_sidebar())
        root.addWidget(self.build_main(), 1)
        root.addWidget(self.build_side_panel())
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        self.refresh_events()
        if self.view_mode != "month" and hasattr(self, "scroll_area"):
            self.scroll_area.verticalScrollBar().setValue(int(7.5 * HOUR_HEIGHT))

    def build_sidebar(self) -> QFrame:
        c = self.colors
        frame = QFrame()
        frame.setObjectName("detailSidebar")
        frame.setFixedWidth(174)
        frame.setStyleSheet(
            f"QFrame#detailSidebar {{ background: {c['sidebar']}; border: none; border-right: 1px solid {c['border_soft']}; "
            f"border-top-left-radius: {self.radius}px; border-bottom-left-radius: {self.radius}px; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 20, 14, 18)
        layout.setSpacing(3)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"background: {c['accent']}; border-radius: 9px;")
        logo.setPixmap(stroke_icon("logo", "#ffffff", 18, 2.2))
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        name = QLabel(APP_NAME_EN)
        name.setFont(app_font(12, QFont.Bold))
        name.setStyleSheet(f"color: {c['text']};")
        suite = QLabel(self.tr("detail.suite", "PROFESSIONAL SUITE"))
        suite.setFont(app_font(6, QFont.Bold))
        suite.setStyleSheet(f"color: {c['muted2']}; letter-spacing: 1px;")
        brand_text.addWidget(name)
        brand_text.addWidget(suite)
        brand.addWidget(logo)
        brand.addLayout(brand_text)
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(18)

        actions = {
            "calendar": self.show_calendar_view,
            "tasks": self.show_tasks_view,
            "archive": self.show_archive_view,
            "focus": self.show_coming_soon,
            "analytics": self.show_coming_soon,
        }
        active_kind = self.section if self.section in {"calendar", "tasks", "archive"} else "calendar"
        for kind, label_key, fallback, icon in self.NAV_ITEMS:
            disabled = kind in self.DISABLED_NAV
            active = (kind == active_kind) and not disabled
            button = self.make_nav_button(self.tr(label_key, fallback), icon, active, disabled=disabled)
            handler = actions.get(kind)
            if handler is not None:
                button.clicked.connect(lambda _checked=False, fn=handler: fn())
            layout.addWidget(button)

        layout.addStretch()
        suggest = QPushButton(self.tr("detail.suggest", "건의하기"))
        suggest.setCursor(Qt.PointingHandCursor)
        suggest.setFixedHeight(34)
        suggest.clicked.connect(self.show_suggest)
        suggest.setStyleSheet(
            f"QPushButton {{ background: {c['upgrade']}; color: #1a1a22; border: none; border-radius: 9px; "
            "font-weight: 700; }}"
        )
        layout.addWidget(suggest)
        layout.addSpacing(8)
        for label_key, fallback, icon, handler in (
            ("detail.nav.help", "도움말", "help", None),
            ("detail.nav.settings", "설정", "settings", getattr(self.app, "open_settings", None)),
        ):
            button = self.make_nav_button(self.tr(label_key, fallback), icon, False)
            if handler is not None:
                button.clicked.connect(lambda _checked=False, fn=handler: fn())
            layout.addWidget(button)
        return frame

    def make_nav_button(self, label: str, icon: str, active: bool, disabled: bool = False) -> QPushButton:
        c = self.colors
        button = QPushButton(f"  {label}")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(36)
        if disabled:
            color = c["fainter"]
            button.setIcon(QIcon(stroke_icon(icon, color, 16)))
            button.setIconSize(QSize(16, 16))
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color}; border: none; border-radius: 9px; "
                "text-align: left; padding: 0 11px; font-size: 12px; font-weight: 500; }}"
            )
            return button
        color = c["text"] if active else c["muted"]
        button.setIcon(QIcon(stroke_icon(icon, color, 16)))
        button.setIconSize(QSize(16, 16))
        bg = c["panel2"] if active else "transparent"
        weight = "600" if active else "500"
        button.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {color}; border: none; border-radius: 9px; "
            f"text-align: left; padding: 0 11px; font-size: 12px; font-weight: {weight}; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['text']}; }}"
        )
        return button

    def build_main(self) -> QFrame:
        c = self.colors
        frame = QFrame()
        frame.setObjectName("detailMain")
        frame.setStyleSheet(f"QFrame#detailMain {{ background: {c['bg']}; border: none; }}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(14)
        layout.addLayout(self.build_top_bar())
        if self.section == "tasks":
            layout.addWidget(self.build_tasks_view(), 1)
        elif self.section == "archive":
            layout.addWidget(self.build_archive_view(), 1)
        elif self.view_mode == "month":
            layout.addWidget(self.build_month_view(), 1)
        else:
            layout.addWidget(self.build_time_view(), 1)
        return frame

    def build_time_view(self) -> QWidget:
        c = self.colors
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.all_day_row = QWidget()
        self.all_day_layout = QHBoxLayout(self.all_day_row)
        self.all_day_layout.setContentsMargins(0, 0, 0, 0)
        self.all_day_layout.setSpacing(6)
        layout.addWidget(self.all_day_row)

        self.day_header = DayHeader(self)
        layout.addWidget(self.day_header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(self.scroll_style())
        self.grid = TimeGrid(self)
        self.empty_hint = QLabel(self.tr("detail.empty", "이 기간에 시간 일정이 없습니다."), self.grid)
        self.empty_hint.setFont(app_font(10))
        self.empty_hint.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        self.empty_hint.move(GUTTER + 18, int(8 * HOUR_HEIGHT))
        self.empty_hint.adjustSize()
        self.empty_hint.hide()
        self.scroll_area.setWidget(self.grid)
        layout.addWidget(self.scroll_area, 1)
        return container

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

    def build_top_bar(self) -> QHBoxLayout:
        if self.section == "tasks":
            return self.build_tasks_top_bar()
        if self.section == "archive":
            return self.build_archive_top_bar()
        c = self.colors
        bar = QHBoxLayout()
        bar.setSpacing(12)

        search = QPushButton(f"   {self.tr('detail.search', '일정 검색...')}")
        search.setCursor(Qt.PointingHandCursor)
        search.setIcon(QIcon(stroke_icon("search", c["muted"], 15)))
        search.setIconSize(QSize(15, 15))
        search.setFixedHeight(30)
        search.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted2']}; border: none; "
            "text-align: left; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )
        search.clicked.connect(lambda: self.app.open_search())

        self.view_buttons: dict[str, QPushButton] = {}
        view_row = QHBoxLayout()
        view_row.setSpacing(14)
        for mode, label_key, fallback in (
            ("day", "detail.view.day", "일"),
            ("week", "detail.view.week", "주"),
            ("month", "detail.view.month", "월"),
        ):
            button = QPushButton(self.tr(label_key, fallback))
            button.setCursor(Qt.PointingHandCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _checked=False, selected=mode: self.set_view_mode(selected))
            button.setStyleSheet(self.view_button_style(mode == self.view_mode))
            self.view_buttons[mode] = button
            view_row.addWidget(button)

        add_button = QPushButton(self.tr("detail.add_event", "일정 추가"))
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.setFixedHeight(32)
        add_button.clicked.connect(self.add_plan)
        add_button.setStyleSheet(
            f"QPushButton {{ background: {c['pill']}; color: {c['pill_text']}; border: none; "
            "border-radius: 9px; padding: 0 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )

        prev_button = self.icon_only_button("chevron_left", self.go_previous)
        next_button = self.icon_only_button("chevron_right", self.go_next)
        today_button = QPushButton(self.tr("detail.today", "오늘"))
        today_button.setCursor(Qt.PointingHandCursor)
        today_button.setFixedHeight(28)
        today_button.clicked.connect(self.go_today)
        today_button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 0 10px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

        bell = QLabel()
        bell.setPixmap(stroke_icon("bell", c["muted"], 17))
        close_button = self.icon_only_button("close", self.close)

        bar.addWidget(search, 1)
        bar.addLayout(view_row)
        bar.addWidget(prev_button)
        bar.addWidget(today_button)
        bar.addWidget(next_button)
        bar.addWidget(add_button)
        bar.addWidget(bell)
        bar.addWidget(close_button)
        return bar

    def icon_only_button(self, icon: str, handler) -> QPushButton:
        c = self.colors
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setIcon(QIcon(stroke_icon(icon, c["muted"], 16, 2.0)))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(28, 28)
        button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 7px; }"
            f"QPushButton:hover {{ background: {c['panel2']}; }}"
        )
        button.clicked.connect(handler)
        return button

    # tasks section --------------------------------------------------------
    def task_controller(self) -> RepeatWindow:
        """할 일 데이터/편집 로직을 재사용하기 위한 공유 컨트롤러입니다."""
        controller = self.app.repeat_window
        if controller is None:
            controller = RepeatWindow(self.app)
            self.app.repeat_window = controller
        return controller

    def show_tasks_view(self) -> None:
        if self.section == "tasks":
            return
        self.section = "tasks"
        self.build_ui()

    def build_tasks_top_bar(self) -> QHBoxLayout:
        c = self.colors
        self.view_buttons = {}
        bar = QHBoxLayout()
        bar.setSpacing(12)

        title = QLabel(self.tr("detail.tasks.title", "해야 할 일"))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")

        self.task_filter_buttons: dict[str, QPushButton] = {}
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)
        for key, label_key, fallback in RepeatWindow.FILTERS:
            button = QPushButton(self.tr(label_key, fallback))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, mode=key: self.set_task_filter(mode))
            button.setStyleSheet(self.task_filter_style(key == self.task_filter))
            self.task_filter_buttons[key] = button
            filter_row.addWidget(button)

        add_button = QPushButton(self.tr("detail.tasks.add", "해야 할 일 추가"))
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.setFixedHeight(32)
        add_button.clicked.connect(self.add_task_item)
        add_button.setStyleSheet(
            f"QPushButton {{ background: {c['pill']}; color: {c['pill_text']}; border: none; "
            "border-radius: 9px; padding: 0 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )

        bell = QLabel()
        bell.setPixmap(stroke_icon("bell", c["muted"], 17))
        close_button = self.icon_only_button("close", self.close)

        bar.addWidget(title)
        bar.addSpacing(8)
        bar.addLayout(filter_row)
        bar.addStretch()
        bar.addWidget(add_button)
        bar.addWidget(bell)
        bar.addWidget(close_button)
        return bar

    def build_tasks_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(self.scroll_style())
        inner = QWidget()
        self.tasks_box = QVBoxLayout(inner)
        self.tasks_box.setContentsMargins(2, 2, 12, 2)
        self.tasks_box.setSpacing(8)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.refresh_tasks_view()
        return container

    def task_visible(self, controller: RepeatWindow, period: str, task: dict) -> bool:
        controller.normalize_task(task)
        mode = self.task_filter
        if mode == "today":
            return controller.is_today_task(period, task)
        if mode == "myday":
            return task.get("my_day") == date.today().isoformat()
        if mode == "important":
            return bool(task.get("important"))
        if mode == "completed":
            return controller.is_done(period, task)
        return True

    def refresh_tasks_view(self) -> None:
        if self.section != "tasks" or not hasattr(self, "tasks_box"):
            return
        clear_layout(self.tasks_box)
        controller = self.task_controller()
        rows = [(period, task) for period, task in controller.all_tasks() if self.task_visible(controller, period, task)]
        if not rows:
            key = "detail.tasks.empty" if self.task_filter == "all" else "detail.tasks.empty_filter"
            empty = QLabel(self.tr(key, "해야 할 일이 없습니다."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.colors['muted2']}; padding: 10px 4px;")
            self.tasks_box.addWidget(empty)
            self.tasks_box.addStretch()
            return
        for period, task in rows:
            self.tasks_box.addWidget(self.make_task_row(controller, period, task))
        self.tasks_box.addStretch()

    def make_task_row(self, controller: RepeatWindow, period: str, task: dict) -> QFrame:
        c = self.colors
        done = controller.is_done(period, task)
        row = QFrame()
        row.setObjectName("taskRow")
        row.setStyleSheet(
            f"QFrame#taskRow {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 9, 10, 9)
        layout.setSpacing(10)

        check = QCheckBox()
        check.setChecked(done)
        check.setCursor(Qt.PointingHandCursor)
        check.setStyleSheet(self.task_checkbox_style())
        check.toggled.connect(lambda checked, p=period, t=task: self.toggle_task_done(p, t, checked))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title = QLabel(task.get("text", "") or self.tr("detail.untitled", "(제목 없음)"))
        title.setFont(app_font(11, QFont.Bold))
        strike = "text-decoration: line-through;" if done else ""
        title.setStyleSheet(f"color: {c['muted2'] if done else c['text_soft']}; background: transparent; {strike}")
        list_name = str(task.get("list_name", RepeatWindow.DEFAULT_LIST_NAME)).strip() or RepeatWindow.DEFAULT_LIST_NAME
        meta_parts = [controller.display_list_name(list_name), controller.period_label(period), controller.elapsed_text(period, task)]
        if task.get("due"):
            meta_parts.append(controller.tr("todo.meta.due", "마감 {date}").format(date=task.get("due")))
        if task.get("my_day") == date.today().isoformat():
            meta_parts.append(controller.tr("todo.meta.myday", "나의 하루"))
        meta_parts.append(controller.tr("todo.meta.completed_count", "{count}회 완료").format(count=int(task.get("done_count", 0))))
        meta = QLabel(" · ".join(meta_parts))
        meta.setFont(app_font(8))
        meta.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title)
        texts.addWidget(meta)

        star = QPushButton("★" if task.get("important") else "☆")
        star.setFixedSize(28, 28)
        star.setCursor(Qt.PointingHandCursor)
        star.setStyleSheet(self.task_star_style(bool(task.get("important"))))
        star.clicked.connect(lambda _checked=False, t=task: self.toggle_task_important(t))

        my_day = QPushButton(self.tr("todo.action.today", "오늘"))
        my_day.setFixedHeight(28)
        my_day.setCursor(Qt.PointingHandCursor)
        my_day.setStyleSheet(self.task_edit_style())
        my_day.clicked.connect(lambda _checked=False, t=task: self.toggle_task_my_day(t))

        edit = QPushButton(self.tr("common.edit", "수정"))
        edit.setFixedHeight(28)
        edit.setCursor(Qt.PointingHandCursor)
        edit.setStyleSheet(self.task_edit_style())
        edit.clicked.connect(lambda _checked=False, p=period, t=task: self.edit_task_item(p, t))

        layout.addWidget(check)
        layout.addLayout(texts, 1)
        layout.addWidget(star)
        layout.addWidget(my_day)
        layout.addWidget(edit)
        return row

    def set_task_filter(self, mode: str) -> None:
        self.task_filter = mode
        for key, button in getattr(self, "task_filter_buttons", {}).items():
            button.setStyleSheet(self.task_filter_style(key == mode))
        self.refresh_tasks_view()

    def toggle_task_done(self, period: str, task: dict, checked: bool) -> None:
        self.task_controller().set_done(period, task, checked)
        self.refresh_tasks_view()

    def toggle_task_important(self, task: dict) -> None:
        self.task_controller().toggle_important(task)
        self.refresh_tasks_view()

    def toggle_task_my_day(self, task: dict) -> None:
        self.task_controller().toggle_my_day(task)
        self.refresh_tasks_view()

    def add_task_item(self) -> None:
        self.task_controller().open_add_task()

    def edit_task_item(self, period: str, task: dict) -> None:
        self.task_controller().open_edit_task(period, task)

    def task_filter_style(self, active: bool) -> str:
        c = self.colors
        if active:
            return (
                f"QPushButton {{ background: {c['accent']}; color: #ffffff; border: none; "
                "border-radius: 9px; padding: 5px 11px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 5px 11px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

    def task_checkbox_style(self) -> str:
        c = self.colors
        return (
            f"QCheckBox {{ spacing: 0; }}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {c['faint']}; border-radius: 6px; "
            f"background: {c['panel2']}; }}"
            f"QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}"
        )

    def task_star_style(self, active: bool) -> str:
        c = self.colors
        color = "#d9a441" if active else c["muted"]
        return (
            f"QPushButton {{ background: transparent; color: {color}; border: none; font-size: 17px; "
            "font-weight: 800; padding: 0; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )

    def task_edit_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 8px; font-size: 11px; font-weight: 700; padding: 0 9px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['text']}; }}"
        )

    # archive section ------------------------------------------------------
    def show_archive_view(self) -> None:
        if self.section == "archive":
            return
        self.section = "archive"
        self.build_ui()

    def saved_memos(self) -> list[tuple[str, str, str]]:
        """저장된 메모를 (id, 제목, 미리보기)로 최신순 반환합니다."""
        rows: list[tuple[str, str, str]] = []
        titles = self.app.config.setdefault("memo_titles", {})
        for memo_id in self.app.memo_store.memo_ids():
            content = self.app.memo_store.load(memo_id)
            title = str(titles.get(memo_id, "")).strip()
            preview = next((line.strip() for line in content.splitlines() if line.strip()), "")
            if not title and not preview:
                continue
            rows.append((memo_id, title, preview))
        rows.sort(key=lambda row: row[0], reverse=True)
        return rows

    def build_archive_top_bar(self) -> QHBoxLayout:
        c = self.colors
        self.view_buttons = {}
        bar = QHBoxLayout()
        bar.setSpacing(12)
        title = QLabel(self.tr("detail.archive.title", "보관"))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")
        self.archive_badge = QLabel("")
        self.archive_badge.setFont(app_font(7, QFont.Bold))
        self.archive_badge.setStyleSheet(
            f"QLabel {{ background: {c['panel2']}; color: {c['muted']}; border-radius: 5px; padding: 2px 7px; }}"
        )
        new_memo = QPushButton(self.tr("detail.archive.new", "새 메모"))
        new_memo.setCursor(Qt.PointingHandCursor)
        new_memo.setFixedHeight(32)
        new_memo.clicked.connect(self.create_archive_memo)
        new_memo.setStyleSheet(
            f"QPushButton {{ background: {c['pill']}; color: {c['pill_text']}; border: none; "
            "border-radius: 9px; padding: 0 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )
        bell = QLabel()
        bell.setPixmap(stroke_icon("bell", c["muted"], 17))
        close_button = self.icon_only_button("close", self.close)
        bar.addWidget(title)
        bar.addSpacing(6)
        bar.addWidget(self.archive_badge)
        bar.addStretch()
        bar.addWidget(new_memo)
        bar.addWidget(bell)
        bar.addWidget(close_button)
        return bar

    def build_archive_view(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(self.scroll_style())
        inner = QWidget()
        self.archive_box = QVBoxLayout(inner)
        self.archive_box.setContentsMargins(2, 2, 12, 2)
        self.archive_box.setSpacing(8)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.refresh_archive_view()
        return container

    def refresh_archive_view(self) -> None:
        if self.section != "archive" or not hasattr(self, "archive_box"):
            return
        clear_layout(self.archive_box)
        rows = self.saved_memos()
        if hasattr(self, "archive_badge"):
            self.archive_badge.setText(self.tr("detail.archive.count", "{count}개", count=len(rows)))
        if not rows:
            empty = QLabel(self.tr("detail.archive.empty", "저장된 메모가 없습니다."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.colors['muted2']}; padding: 10px 4px;")
            self.archive_box.addWidget(empty)
            self.archive_box.addStretch()
            return
        for memo_id, title, preview in rows:
            self.archive_box.addWidget(self.make_archive_row(memo_id, title, preview))
        self.archive_box.addStretch()

    def make_archive_row(self, memo_id: str, title: str, preview: str) -> QFrame:
        c = self.colors
        row = QFrame()
        row.setObjectName("archiveRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QFrame#archiveRow {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}"
            f"QFrame#archiveRow:hover {{ border: 1px solid {c['accent']}; }}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(13, 10, 12, 10)
        layout.setSpacing(10)
        icon = QLabel()
        icon.setPixmap(stroke_icon("archive", c["muted"], 16))
        icon.setFixedWidth(20)
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title_label = QLabel(title or self.tr("detail.archive.untitled", "제목 없는 메모"))
        title_label.setFont(app_font(11, QFont.Bold))
        title_label.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        preview_label = QLabel(preview or self.tr("detail.archive.no_preview", "내용 없음"))
        preview_label.setFont(app_font(8))
        preview_label.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title_label)
        texts.addWidget(preview_label)
        layout.addWidget(icon)
        layout.addLayout(texts, 1)
        row.mousePressEvent = lambda _event, mid=memo_id: self.open_archived_memo(mid)  # type: ignore[assignment]
        return row

    def open_archived_memo(self, memo_id: str) -> None:
        opener = getattr(self.app, "open_memo", None)
        if opener is not None:
            opener(memo_id)

    def create_archive_memo(self) -> None:
        creator = getattr(self.app, "create_memo", None)
        if creator is not None:
            creator()

    def show_coming_soon(self) -> None:
        QMessageBox.information(
            self,
            self.tr("app.name", APP_NAME),
            self.tr("detail.coming_soon", "준비 중인 기능입니다. 다음 단계에서 추가할 예정입니다."),
        )

    def show_suggest(self) -> None:
        QMessageBox.information(
            self,
            self.tr("app.name", APP_NAME),
            self.tr("detail.suggest.pending", "건의/피드백 기능은 다음 단계에서 추가할 예정입니다."),
        )

    def build_side_panel(self) -> QFrame:
        c = self.colors
        panel = QFrame()
        panel.setObjectName("detailSide")
        panel.setFixedWidth(240)
        panel.setStyleSheet(
            f"QFrame#detailSide {{ background: {c['bg']}; border: none; border-left: 1px solid {c['border_soft']}; "
            f"border-top-right-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; }}"
        )
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        glance = QLabel(self.tr("detail.quick_glance", "한눈에 보기"))
        glance.setFont(app_font(14, QFont.Bold))
        layout.addWidget(glance)

        self.mini_calendar = MiniCalendar(self)
        layout.addWidget(self.mini_calendar)

        upcoming_head = QHBoxLayout()
        upcoming_label = QLabel(self.tr("detail.upcoming", "다가오는 일정"))
        upcoming_label.setFont(app_font(7, QFont.Bold))
        upcoming_label.setStyleSheet(f"color: {c['muted2']}; letter-spacing: 1px;")
        self.upcoming_badge = QLabel("")
        self.upcoming_badge.setFont(app_font(7, QFont.Bold))
        self.upcoming_badge.setStyleSheet(
            f"QLabel {{ background: {c['panel2']}; color: {c['muted']}; border-radius: 5px; padding: 2px 7px; }}"
        )
        upcoming_head.addWidget(upcoming_label)
        upcoming_head.addStretch()
        upcoming_head.addWidget(self.upcoming_badge)
        layout.addLayout(upcoming_head)

        self.upcoming_box = QVBoxLayout()
        self.upcoming_box.setSpacing(13)
        layout.addLayout(self.upcoming_box)

        layout.addStretch()
        layout.addWidget(self.build_trend_card())
        return panel

    def build_trend_card(self) -> QFrame:
        c = self.colors
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['card_border']}; border-radius: 12px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(7)
        icon = QLabel()
        icon.setPixmap(stroke_icon("trend", c["accent"], 14, 2.0))
        title = QLabel(self.tr("detail.trend.label", "표시 중 일정"))
        title.setFont(app_font(7, QFont.Bold))
        title.setStyleSheet(f"color: {c['muted2']}; letter-spacing: 1px;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch()
        self.trend_value = QLabel("")
        self.trend_value.setFont(app_font(20, QFont.Bold))
        self.trend_value.setStyleSheet(f"color: {c['accent']};")
        self.trend_caption = QLabel(self.tr("detail.trend.caption", "현재 보기 기준 시간 일정 수입니다."))
        self.trend_caption.setWordWrap(True)
        self.trend_caption.setFont(app_font(8))
        self.trend_caption.setStyleSheet(f"color: {c['muted2']};")
        layout.addLayout(head)
        layout.addWidget(self.trend_value)
        layout.addWidget(self.trend_caption)
        return card

    # refresh --------------------------------------------------------------
    def refresh_events(self) -> None:
        self.compute_days()
        self.compute_lanes()
        if self.section == "tasks":
            self.refresh_tasks_view()
        if self.section == "archive":
            self.refresh_archive_view()
        if hasattr(self, "day_header"):
            self.day_header.update()
        if self.mini_calendar is not None:
            self.mini_calendar.sync_anchor()
        if hasattr(self, "all_day_layout"):
            self.refresh_all_day_row()
        if hasattr(self, "grid"):
            self.refresh_grid_blocks()
        self.refresh_upcoming()
        if hasattr(self, "trend_value"):
            count = self.view_event_count()
            self.trend_value.setText(self.tr("detail.trend.count", "{count}건", count=count))

    def refresh_grid_blocks(self) -> None:
        self.grid.clear_blocks()
        has_event = False
        for day in self.days:
            for plan, start_dt, end_dt in self.timed_plans_for_day(day):
                self.grid.add_block(plan, start_dt, end_dt)
                has_event = True
        self.grid.position_blocks()
        if hasattr(self, "empty_hint"):
            self.empty_hint.setVisible(not has_event)

    def refresh_all_day_row(self) -> None:
        clear_layout(self.all_day_layout)
        seen: set[str] = set()
        chips: list[dict] = []
        for day in self.days:
            for plan in self.all_day_plans_for_day(day):
                key = str(plan.get("id", ""))
                if key in seen:
                    continue
                seen.add(key)
                chips.append(plan)
        if not chips:
            self.all_day_row.setVisible(False)
            return
        self.all_day_row.setVisible(True)
        label = QLabel(self.tr("plan.all_day", "종일"))
        label.setFont(app_font(7, QFont.Bold))
        label.setStyleSheet(f"color: {self.colors['muted2']};")
        self.all_day_layout.addWidget(label)
        for plan in chips[:6]:
            self.all_day_layout.addWidget(self.make_all_day_chip(plan))
        self.all_day_layout.addStretch()

    def make_all_day_chip(self, plan: dict) -> QPushButton:
        c = self.colors
        red, green, blue = _hex_to_rgb(plan.get("color", c["accent"]))
        chip = QPushButton(plan.get("title", "") or self.tr("detail.untitled", "(제목 없음)"))
        chip.setCursor(Qt.PointingHandCursor)
        chip.setFixedHeight(24)
        chip.setStyleSheet(
            f"QPushButton {{ background: rgba({red},{green},{blue},0.18); color: {c['text']}; "
            f"border: none; border-left: 3px solid rgb({red},{green},{blue}); border-radius: 6px; "
            "padding: 2px 10px; font-weight: 600; }}"
        )
        start_day = (_parse_dt(plan.get("start", "")) or datetime.now()).date()
        chip.clicked.connect(lambda _checked=False, p=plan, d=start_day: self.edit_plan(p, d))
        return chip

    def refresh_upcoming(self) -> None:
        if not hasattr(self, "upcoming_box"):
            return
        clear_layout(self.upcoming_box)
        rows = self.upcoming_plans()
        if hasattr(self, "upcoming_badge"):
            self.upcoming_badge.setText(self.tr("detail.upcoming.count", "{count}건", count=len(rows)))
        if not rows:
            empty = QLabel(self.tr("detail.upcoming.empty", "예정된 일정이 없습니다."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.colors['muted2']};")
            self.upcoming_box.addWidget(empty)
            return
        for plan, start_dt in rows:
            self.upcoming_box.addWidget(self.make_upcoming_row(plan, start_dt))

    def make_upcoming_row(self, plan: dict, start_dt: datetime) -> QWidget:
        c = self.colors
        red, green, blue = _hex_to_rgb(plan.get("color", c["accent"]))
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: rgb({red},{green},{blue}); border-radius: 3px;")
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 4, 0, 0)
        wrapper.addWidget(dot)
        wrapper.addStretch()
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        title = QLabel(plan.get("title", "") or self.tr("detail.untitled", "(제목 없음)"))
        title.setFont(app_font(10, QFont.Bold))
        title.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        when = QLabel(self.upcoming_when_text(start_dt, plan.get("kind") == "long"))
        when.setFont(app_font(8))
        when.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title)
        texts.addWidget(when)
        layout.addLayout(wrapper)
        layout.addLayout(texts, 1)
        start_day = start_dt.date()
        row.mousePressEvent = lambda _event, p=plan, d=start_day: self.edit_plan(p, d)  # type: ignore[assignment]
        return row

    def upcoming_when_text(self, start_dt: datetime, all_day: bool) -> str:
        day = start_dt.date()
        today = date.today()
        if day == today:
            day_text = self.tr("detail.when.today", "오늘")
        elif day == today + timedelta(days=1):
            day_text = self.tr("detail.when.tomorrow", "내일")
        else:
            day_text = self.tr("detail.when.date", "{month:02}.{day:02}", month=day.month, day=day.day)
        if all_day:
            return day_text
        return self.tr("detail.when.format", "{day} · {time}", day=day_text, time=f"{start_dt:%H:%M}")

    # navigation -----------------------------------------------------------
    def set_view_mode(self, mode: str) -> None:
        if mode not in {"day", "week", "month"} or mode == self.view_mode:
            return
        self.view_mode = mode
        self.app.config["detail_view_mode"] = mode
        self.app.save()
        self.build_ui()

    def show_calendar_view(self) -> None:
        was_other = self.section != "calendar"
        self.section = "calendar"
        if was_other:
            if self.view_mode not in {"day", "week", "month"}:
                self.view_mode = "week"
            self.build_ui()
        else:
            self.set_view_mode("week")

    def go_previous(self) -> None:
        self.focused_day = self.shifted_focus(-1)
        self.refresh_after_focus_change()

    def go_next(self) -> None:
        self.focused_day = self.shifted_focus(1)
        self.refresh_after_focus_change()

    def shifted_focus(self, direction: int) -> date:
        if self.view_mode == "day":
            return self.focused_day + timedelta(days=direction)
        if self.view_mode == "month":
            month = self.focused_day.month - 1 + direction
            year = self.focused_day.year + month // 12
            return date(year, month % 12 + 1, 1)
        return self.focused_day + timedelta(days=7 * direction)

    def go_today(self) -> None:
        self.focused_day = date.today()
        self.refresh_after_focus_change()

    def refresh_after_focus_change(self) -> None:
        if self.view_mode == "month":
            self.build_ui()
        else:
            self.refresh_events()

    def open_day(self, day: date) -> None:
        self.focused_day = day
        self.view_mode = "day"
        self.app.config["detail_view_mode"] = "day"
        self.app.save()
        self.build_ui()

    # plan editing ---------------------------------------------------------
    def add_plan(self) -> None:
        target = date.today() if date.today() in self.day_index else (self.days[0] if self.days else date.today())
        self.open_plan_editor(target, None)

    def edit_plan(self, plan: dict, day: date) -> None:
        self.open_plan_editor(day, plan)

    def open_plan_editor(self, day: date, plan: dict | None) -> None:
        if self.plan_window and self.plan_window.isVisible():
            self.plan_window.close()
        self.plan_window = PlanWindow(self.app, day, plan)
        self.plan_window.show()
        self.plan_window.raise_()
        self.plan_window.activateWindow()

    # theme / language -----------------------------------------------------
    def apply_theme(self) -> None:
        self.colors = design_palette(self.app.config)
        self.build_ui()
        self.update()

    def apply_language(self) -> None:
        self.setWindowTitle(self.window_title_text())
        self.build_ui()
        self.update()

    # styles ---------------------------------------------------------------
    def view_button_style(self, active: bool) -> str:
        c = self.colors
        if active:
            return (
                f"QPushButton {{ background: transparent; color: {c['text']}; border: none; "
                f"border-bottom: 2px solid {c['accent']}; padding: 0 0 4px; font-size: 13px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background: transparent; color: {c['muted2']}; border: none; "
            "padding: 0 0 4px; font-size: 13px; font-weight: 500; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

    def scroll_style(self) -> str:
        c = self.colors
        return (
            f"QScrollArea {{ background: {c['bg']}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {c['bg']}; }}"
            f"QScrollBar:vertical {{ background: {c['bg']}; width: {SCROLLBAR_WIDTH}px; margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 30px; border-radius: 4px; margin: 1px 2px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {c['muted2']}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

    def closeEvent(self, event) -> None:
        self.app.config["detail_geometry"] = geometry_string(self)
        self.app.config["detail_view_mode"] = self.view_mode
        self.app.save()
        self.app.detail_window = None
        super().closeEvent(event)
