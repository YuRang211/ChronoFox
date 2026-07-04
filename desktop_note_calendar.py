from __future__ import annotations

import calendar
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import holidays as holiday_lib
except ImportError:
    holiday_lib = None

try:
    from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
    from PySide6.QtWidgets import (
        QApplication,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMenu,
        QMessageBox,
        QSystemTrayIcon,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit(
        "PySide6가 설치되어 있지 않습니다.\n"
        "터미널에서 아래 명령을 먼저 실행해 주세요:\n\n"
        "python -m pip install PySide6"
    ) from exc

from app_config import create_backup_archive, load_config, load_data, save_config, save_data
from app_constants import (
    APP_ICON_PATH,
    APP_NAME,
    DEFAULT_CALENDAR_GEOMETRY,
    DEFAULT_FONT_FAMILY,
    LEGACY_STARTUP_PATH,
    STARTUP_PATH,
)
from app_i18n import translate
from app_integrations import export_ics
from app_models import MemoStore
from app_theme import prettify_holiday_name, resolve_theme
from app_ui import (
    app_font,
    clamp_window_position,
    clear_layout,
    geometry_string,
    load_app_font,
    parse_geometry,
    set_active_font_family,
)
from app_widgets import IconButton, RoundedWindow
from clock_window import ClockWindow
from detail_schedule_window import DetailScheduleWindow
from memo_window import StickyMemoWindow
from schedule_window import ScheduleWindow
from search_window import SearchWindow
from settings_window import SettingsWindow
from todo_window import RepeatWindow


class DayCell(QWidget):
    """달력의 날짜 한 칸을 직접 그리는 위젯입니다."""

    clicked = Signal(date)

    def __init__(self, colors: dict[str, str]) -> None:
        super().__init__()
        self.colors = colors
        self.day = date.today()
        self.lines: list[str] = []
        self.plan_bars: list[dict] = []
        self.holiday = ""
        self.state = "normal"
        self.hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)

    def set_data(self, day: date, lines: list[str], state: str, holiday: str = "", plan_bars: list[dict] | None = None) -> None:
        self.day = day
        self.lines = lines[:2]
        self.plan_bars = (plan_bars or [])[:3]
        self.holiday = holiday
        self.state = state
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.day)

    def enterEvent(self, event) -> None:
        self.hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        colors = self.colors
        bg = colors["cell"]
        fg = colors["text"]
        if self.state == "other":
            bg, fg = colors["other"], colors["other_text"]
        elif self.state == "today":
            bg, fg = colors["today_bg"], colors["today_text"]
        elif self.state == "selected":
            bg, fg = colors["selected_bg"], colors["selected_text"]
        elif self.state == "holiday":
            bg, fg = colors["cell"], colors["holiday"]

        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(bg))
        if self.hovered and self.state not in {"selected", "today"}:
            hover = QColor(colors.get("button_hover", colors["panel2"]))
            hover.setAlpha(68)
            painter.fillRect(self.rect(), hover)
        painter.setPen(QPen(QColor(colors["grid"]), 0.55))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self.state == "selected":
            painter.setPen(QPen(QColor(colors["selected_border"]), 2.0))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        elif self.state == "today":
            painter.setPen(QPen(QColor(colors["today_border"]), 1.6))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))

        date_color = fg
        if self.state != "other":
            if self.day.weekday() == 5:
                date_color = colors["saturday"]
            elif self.day.weekday() == 6:
                date_color = colors["sunday"]
            if self.state == "holiday":
                date_color = colors["holiday"]

        painter.setPen(QColor(date_color))
        painter.setFont(app_font(9, QFont.Bold))
        painter.drawText(10, 20, str(self.day.day))

        if self.holiday:
            holiday_color = colors["other_text"] if self.state == "other" else colors["holiday"]
            holiday_font = app_font(8)
            painter.setFont(holiday_font)
            painter.setPen(QColor(holiday_color))
            metrics = painter.fontMetrics()
            holiday_rect = QRect(34, 4, max(10, self.width() - 44), 18)
            painter.drawText(
                holiday_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                metrics.elidedText(self.holiday, Qt.ElideRight, holiday_rect.width()),
            )

        painter.setFont(app_font(9))
        metrics = painter.fontMetrics()
        base_y = 34
        for plan in self.plan_bars:
            y = base_y + int(plan.get("lane", 0)) * 18
            if y + 15 > self.height() - 18:
                continue
            color = QColor(plan.get("color", colors["accent"]))
            color.setAlpha(180)
            # 주 경계(일요일 시작/토요일 끝)에서는 셀 밖으로 삐져나가지 않게 가장자리에서 멈춘다.
            week_start = self.day.weekday() == 6
            week_end = self.day.weekday() == 5
            x = (2 if week_start else -2) if plan.get("from_prev") else 10
            right_margin = (2 if week_end else -2) if plan.get("to_next") else 10
            rect = QRect(x, y, max(8, self.width() - x - right_margin), 15)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 2, 2)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(app_font(8, QFont.Bold))
            text_rect = rect.adjusted(4, -1, -3, 0)
            title = plan.get("title", "") if plan.get("show_title") else ""
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(title, Qt.ElideRight, text_rect.width()))
            y += 18

        painter.setFont(app_font(9))
        metrics = painter.fontMetrics()
        used_lanes = [int(plan.get("lane", 0)) for plan in self.plan_bars]
        y = max(base_y + (max(used_lanes) + 1) * 18 + 8 if used_lanes else 48, 48)
        available = max(10, self.width() - 20)
        painter.setPen(QColor(colors["text"]))
        for line in self.lines:
            if y + metrics.height() > self.height() - 4:
                break
            painter.drawText(10, y, metrics.elidedText(line, Qt.ElideRight, available))
            y += 16

class FoxCalendarApp(RoundedWindow):
    """달력, 트레이 아이콘, 일정, 메모창을 관리하는 메인 앱입니다."""

    def __init__(self) -> None:
        self.config = load_config()
        self.data = load_data(self.config)
        self.colors = resolve_theme(self.config)
        super().__init__(self.colors)
        self.draw_window_border = False
        self.icon = QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.exists() else QIcon()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.icon)
        self.memo_store = MemoStore(Path(self.config["notes_dir"]))
        self.visible_month = date.today().replace(day=1)
        self.selected_day = date.today()
        self.day_cells: list[DayCell] = []
        self.memo_windows: dict[str, StickyMemoWindow] = {}
        self.schedule_windows: dict[str, ScheduleWindow] = {}
        self.settings_window: SettingsWindow | None = None
        self.search_window: SearchWindow | None = None
        self.clock_window: ClockWindow | None = None
        self.repeat_window: RepeatWindow | None = None
        self.detail_window: DetailScheduleWindow | None = None
        self.holiday_cache: dict[int, dict[date, str]] = {}
        self.force_quit = False
        width, height, x, y = parse_geometry(self.config.get("calendar_geometry", DEFAULT_CALENDAR_GEOMETRY), (980, 620, 180, 40))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(760, 480)
        self.setWindowOpacity(self.config.get("calendar_opacity", 56) / 100)
        self.build_ui()
        self.setup_tray()
        self.render_calendar()
        self.restore_open_memos()
        # 일정 알림은 시계창과 무관하게 메인 앱이 상주 검사한다 (UX14).
        self.reminder_timer = QTimer(self)
        self.reminder_timer.setInterval(30000)
        self.reminder_timer.timeout.connect(self.check_plan_reminders)
        self.reminder_timer.start()
        self.check_plan_reminders()

    def save(self) -> None:
        self.config["calendar_geometry"] = geometry_string(self)
        save_config(self.config)
        save_data(self.data)

    def tr(self, key: str, fallback: str = "") -> str:
        return translate(self.config.get("language", "ko"), key, fallback)

    def app_display_name(self) -> str:
        return self.tr("app.name", APP_NAME)

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def build_ui(self) -> None:
        """메인 달력의 헤더, 요일줄, 날짜칸을 구성합니다."""
        c = self.colors
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.day_cells = []
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(8)
        header.setColumnStretch(0, 1)
        header.setColumnStretch(1, 1)
        header.setColumnStretch(2, 1)
        prev_button = IconButton("prev", c)
        next_button = IconButton("next", c)
        menu_button = IconButton("menu", c)
        today_button = IconButton("today", c)
        self.header_buttons = []
        prev_button.clicked.connect(self.previous_month)
        next_button.clicked.connect(self.next_month)
        menu_button.clicked.connect(self.open_header_menu)
        today_button.clicked.connect(self.go_to_today)

        self.icon_buttons = [prev_button, next_button, menu_button, today_button]
        self.month_label = QLabel("")
        self.month_label.setAlignment(Qt.AlignCenter)
        self.month_label.setFont(app_font(14, QFont.Bold))

        self.search_input = QLineEdit()
        self.search_input.setObjectName("calendarSearchInput")
        self.search_input.setPlaceholderText(self.tr("calendar.search.placeholder", "일정 검색..."))
        self.search_input.setFixedWidth(220)
        self.search_input.setClearButtonEnabled(True)
        self.search_action = self.search_input.addAction(self.search_icon(), QLineEdit.LeadingPosition)
        self.search_input.returnPressed.connect(self.open_search_from_header)
        self.search_input.setStyleSheet(self.calendar_search_style())

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)
        right.addStretch()
        right.addWidget(menu_button)
        right.addWidget(today_button)
        separator = QFrame()
        separator.setObjectName("headerSeparator")
        separator.setFixedSize(1, 18)
        separator.setStyleSheet(f"background: {c['border']};")
        self.header_separator = separator
        right.addWidget(separator)
        right.addWidget(prev_button)
        right.addWidget(next_button)
        header.addWidget(self.search_input, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
        header.addWidget(self.month_label, 0, 1)
        header.addLayout(right, 0, 2)
        header_frame = QFrame()
        header_frame.setObjectName("calendarHeader")
        header_frame.setStyleSheet(self.calendar_header_style())
        header_frame_layout = QVBoxLayout(header_frame)
        header_frame_layout.setContentsMargins(18, 10, 18, 10)
        header_frame_layout.addLayout(header)
        self.header_frame = header_frame
        layout.addWidget(header_frame)

        self.grid = QGridLayout()
        self.grid.setSpacing(0)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid_frame = QFrame()
        self.grid_frame.setObjectName("calendarGridFrame")
        self.grid_frame.setStyleSheet(self.calendar_grid_style())
        grid_frame_layout = QVBoxLayout(self.grid_frame)
        grid_frame_layout.setContentsMargins(0, 0, 0, 0)
        grid_frame_layout.setSpacing(0)
        self.weekday_labels = []
        weekday_texts = [
            self.tr("calendar.weekday.sun", "일"),
            self.tr("calendar.weekday.mon", "월"),
            self.tr("calendar.weekday.tue", "화"),
            self.tr("calendar.weekday.wed", "수"),
            self.tr("calendar.weekday.thu", "목"),
            self.tr("calendar.weekday.fri", "금"),
            self.tr("calendar.weekday.sat", "토"),
        ]
        for col, text in enumerate(weekday_texts):
            label = QLabel(text)
            label.setProperty("weekday_col", col)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(9, QFont.Bold))
            label.setFixedHeight(34)
            weekday_color = c["text"]
            if col == 0:
                weekday_color = c["sunday"]
            elif col == 6:
                weekday_color = c["saturday"]
            label.setStyleSheet(
                f"background: {c['weekday']}; color: {weekday_color};"
                f"border: 0.5px solid {c['grid']};"
            )
            self.weekday_labels.append(label)
            self.grid.addWidget(label, 0, col)

        for row in range(6):
            for col in range(7):
                cell = DayCell(c)
                cell.clicked.connect(self.open_schedule_near)
                self.day_cells.append(cell)
                self.grid.addWidget(cell, row + 1, col)
        grid_frame_layout.addLayout(self.grid, 1)
        layout.addWidget(self.grid_frame, 1)

        footer_frame = QFrame()
        footer_frame.setObjectName("calendarFooter")
        footer_frame.setFixedHeight(25)
        footer_frame.setStyleSheet(self.calendar_footer_style())
        self.footer_frame = footer_frame
        layout.addWidget(footer_frame)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")

    def open_header_menu(self) -> None:
        c = self.colors
        menu = QMenu(self)
        menu.setStyleSheet(
            f"QMenu {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 7px; padding: 5px; }}"
            f"QMenu::item {{ padding: 7px 28px 7px 12px; border-radius: 5px; }}"
            f"QMenu::item:selected {{ background: {c['panel2']}; }}"
            f"QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 4px; }}"
        )
        detail_action = menu.addAction(self.tr("menu.details", "세부 일정"))
        clock_action = menu.addAction(self.tr("menu.clock", "시계"))
        repeat_action = menu.addAction(self.tr("menu.todo", "해야 할 일"))
        menu.addSeparator()
        memo_action = menu.addAction(self.tr("menu.new_memo", "새 메모"))
        recall_memos_action = menu.addAction(self.tr("menu.recall_memos", "숨은 메모 불러오기"))
        settings_action = menu.addAction(self.tr("menu.settings", "설정"))
        menu.addSeparator()
        hide_action = menu.addAction(self.tr("menu.hide", "숨기기"))

        detail_action.triggered.connect(self.open_detail_schedule)
        clock_action.triggered.connect(self.open_clock)
        repeat_action.triggered.connect(self.open_repeat)
        memo_action.triggered.connect(self.create_memo)
        recall_memos_action.triggered.connect(self.recall_hidden_memos)
        settings_action.triggered.connect(self.open_settings)
        hide_action.triggered.connect(self.close)

        sender = self.sender()
        if isinstance(sender, QWidget):
            menu.exec(sender.mapToGlobal(QPoint(0, sender.height() + 2)))

    def setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(self.app_display_name())

        menu = QMenu()
        show_action = QAction("", self)
        memo_action = QAction("", self)
        settings_action = QAction("", self)
        quit_action = QAction("", self)
        show_action.triggered.connect(self.show_calendar)
        memo_action.triggered.connect(self.create_memo)
        settings_action.triggered.connect(self.open_settings)
        quit_action.triggered.connect(self.quit_from_tray)

        self.tray_show_action = show_action
        self.tray_memo_action = memo_action
        self.tray_settings_action = settings_action
        self.tray_quit_action = quit_action
        self.refresh_tray_texts()

        menu.addAction(show_action)
        menu.addAction(memo_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.handle_tray_activated)
        self.tray.show()

    def refresh_tray_texts(self) -> None:
        if not hasattr(self, "tray"):
            return
        self.tray.setToolTip(self.app_display_name())
        self.tray_show_action.setText(self.tr("menu.open_app", "{name} 열기").format(name=self.app_display_name()))
        self.tray_memo_action.setText(self.tr("menu.new_memo", "새 메모"))
        self.tray_settings_action.setText(self.tr("menu.settings", "설정"))
        self.tray_quit_action.setText(self.tr("menu.quit", "종료"))

    def handle_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and self.isActiveWindow():
                self.hide()
            else:
                self.show_calendar()

    def show_calendar(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
        self.raise_memos_above_calendar()

    def raise_memos_above_calendar(self) -> None:
        """달력이 다시 활성화되어도 열린 메모가 달력 뒤로 숨지 않게 합니다."""
        for window in list(self.memo_windows.values()):
            if window.isVisible():
                window.raise_()

    def event(self, event) -> bool:
        if event.type() == QEvent.WindowActivate:
            self.raise_memos_above_calendar()
        return super().event(event)

    def quit_from_tray(self) -> None:
        self.force_quit = True
        self.persist_open_windows()
        self.save()
        QApplication.quit()

    def header_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c.get('button_hover', c['panel2'])}; border-radius: 6px; }}"
        )

    def calendar_header_style(self) -> str:
        c = self.colors
        return (
            f"QFrame#calendarHeader {{ background: {c.get('header', c['panel'])}; "
            f"border: 1px solid {c['border']}; border-bottom: none; "
            f"border-top-left-radius: {self.radius}px; border-top-right-radius: {self.radius}px; }}"
        )

    def calendar_grid_style(self) -> str:
        c = self.colors
        return (
            f"QFrame#calendarGridFrame {{ background: {c['cell']}; border: 1px solid {c['border']}; "
            "border-top: none; border-bottom: none; border-radius: 0px; }}"
        )

    def calendar_footer_style(self) -> str:
        c = self.colors
        return (
            f"QFrame#calendarFooter {{ background: {c.get('header', c['panel'])}; "
            f"border: 1px solid {c['border']}; border-top: none; "
            f"border-bottom-left-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; }}"
        )

    def calendar_search_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit#calendarSearchInput {{ background: {c.get('input_bg', c['panel2'])}; color: {c['text']}; "
            f"border: 1px solid {c.get('input_border', c['border'])}; border-radius: 6px; "
            "padding: 5px 10px; }}"
            f"QLineEdit#calendarSearchInput:focus {{ border-color: {c['accent']}; }}"
            f"QLineEdit#calendarSearchInput::placeholder {{ color: {c['muted']}; }}"
        )

    def search_icon(self) -> QIcon:
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(self.colors["muted"]), 1.6)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(3.2, 3.2, 7.2, 7.2))
        painter.drawLine(9.2, 9.2, 13.0, 13.0)
        painter.end()
        return QIcon(pixmap)

    def render_calendar(self) -> None:
        """현재 보이는 월의 날짜, 일정, 공휴일을 날짜칸에 반영합니다."""
        self.month_label.setText(self.month_title_text(self.visible_month))
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(self.visible_month.year, self.visible_month.month)
        days = [day for week in weeks for day in week]
        plan_bars_by_day = self.plan_bars_for_days(days)
        for index, cell in enumerate(self.day_cells):
            if index >= len(days):
                cell.hide()
                continue
            cell.show()
            day = days[index]
            lines: list[str] = []
            holiday = self.get_holiday(day)
            plan_bars = plan_bars_by_day.get(day, [])
            schedule = self.get_schedule(day).strip()
            if schedule:
                lines.extend(line.strip() for line in schedule.splitlines() if line.strip())
            state = "normal"
            if day.month != self.visible_month.month:
                state = "other"
            elif day == self.selected_day:
                state = "selected"
            elif day == date.today():
                state = "today"
            elif holiday:
                state = "holiday"
            cell.set_data(day, lines, state, holiday, plan_bars)

    def month_title_text(self, month: date) -> str:
        month_name = self.tr(f"calendar.month.{month.month}", str(month.month))
        return self.tr("calendar.month_title", "{year}년 {month}월").format(
            year=month.year,
            month=month_name,
        )

    def get_holiday(self, day: date) -> str:
        if not self.config.get("holiday_enabled", True):
            return ""
        return self.holidays_for_year(day.year).get(day, "")

    def holidays_for_year(self, year: int) -> dict[date, str]:
        """holidays 라이브러리로 한국 공휴일을 계산하고 연도별로 캐시합니다."""
        if year in self.holiday_cache:
            return self.holiday_cache[year]

        holidays_by_date: dict[date, str] = {}
        if holiday_lib is not None:
            try:
                kr_holidays = holiday_lib.country_holidays("KR", years=[year], language="ko", observed=True)
                holidays_by_date = {
                    holiday_day: prettify_holiday_name(str(name))
                    for holiday_day, name in kr_holidays.items()
                    if isinstance(holiday_day, date)
                }
            except Exception:
                holidays_by_date = {}

        self.holiday_cache[year] = holidays_by_date
        return holidays_by_date

    def get_schedule(self, day: date) -> str:
        return self.data.setdefault("schedules", {}).get(day.isoformat(), "")

    def plans_for_day(self, day: date) -> list[dict]:
        return [
            plan
            for plan in self.sorted_plans()
            if self.plan_start_date(plan) <= day <= self.plan_end_date(plan)
        ]

    def sorted_plans(self) -> list[dict]:
        return sorted(
            self.data.setdefault("plans", []),
            key=lambda plan: (self.plan_start_date(plan), self.plan_end_date(plan), plan.get("title", "")),
        )

    def plan_start_date(self, plan: dict) -> date:
        try:
            return date.fromisoformat(str(plan.get("start", ""))[:10])
        except ValueError:
            return date.today()

    def plan_end_date(self, plan: dict) -> date:
        try:
            end_day = date.fromisoformat(str(plan.get("end", plan.get("start", "")))[:10])
        except ValueError:
            end_day = self.plan_start_date(plan)
        return max(self.plan_start_date(plan), end_day)

    def plan_bars_for_day(self, day: date) -> list[dict]:
        return self.plan_bars_for_days([day]).get(day, [])

    def plan_bars_for_days(self, days: list[date]) -> dict[date, list[dict]]:
        colors = ["#3abf7a", "#e47d7d", "#7d8bd9", "#d9a441", "#5aa7d9"]
        target_days = set(days)
        lane_ends: list[date] = []
        lanes: dict[str, int] = {}
        plan_rows: list[tuple[int, dict, date, date, str]] = []
        for index, plan in enumerate(self.sorted_plans()):
            start_day = self.plan_start_date(plan)
            end_day = self.plan_end_date(plan)
            plan_id = str(plan.get("id", id(plan)))
            lane = next((idx for idx, lane_end in enumerate(lane_ends) if start_day > lane_end), None)
            if lane is None:
                lane = len(lane_ends)
                lane_ends.append(end_day)
            else:
                lane_ends[lane] = end_day
            lanes[plan_id] = lane
            plan_rows.append((index, plan, start_day, end_day, plan_id))

        bars_by_day: dict[date, list[dict]] = {day: [] for day in target_days}
        for index, plan, start_day, end_day, plan_id in plan_rows:
            title = plan.get("title", "")
            # 시간 일정은 칩에 시작 시각을 함께 보여준다 (예: "09:00 회의").
            if plan.get("kind") != "long":
                start_hhmm = str(plan.get("start", ""))[11:16]
                if start_hhmm:
                    title = f"{start_hhmm} {title}".strip()
            for day in target_days:
                if not (start_day <= day <= end_day):
                    continue
                bars_by_day[day].append(
                    {
                        "title": title,
                        "color": plan.get("color") or colors[index % len(colors)],
                        "from_prev": day > start_day,
                        "to_next": day < end_day,
                        # 여러 주에 걸친 바는 각 주의 첫 칸(일요일)에도 제목을 반복해 알아볼 수 있게 한다.
                        "show_title": day == start_day or (day > start_day and day.weekday() == 6),
                        "lane": lanes.get(plan_id, 0),
                    }
                )
        return bars_by_day

    def add_plan(self, plan: dict) -> None:
        self.data.setdefault("plans", []).append(plan)
        self.save()
        self.render_calendar()
        schedule = self.schedule_windows.get(str(plan.get("start", ""))[:10])
        if schedule and schedule.isVisible():
            schedule.apply_theme()
        self.refresh_detail_window()

    def update_plan(self, updated_plan: dict) -> None:
        plans = self.data.setdefault("plans", [])
        for index, plan in enumerate(plans):
            if plan.get("id") == updated_plan.get("id"):
                plans[index] = updated_plan
                break
        self.save()
        self.render_calendar()
        for window in list(self.schedule_windows.values()):
            if window.isVisible():
                window.apply_theme()
        self.refresh_detail_window()

    def delete_plan(self, plan_id: str) -> None:
        self.data.setdefault("plans", [])[:] = [
            plan for plan in self.data.setdefault("plans", []) if plan.get("id") != plan_id
        ]
        self.save()
        self.render_calendar()
        self.refresh_detail_window()

    def refresh_detail_window(self) -> None:
        if self.detail_window and self.detail_window.isVisible():
            self.detail_window.refresh_events()

    REMINDER_GRACE = timedelta(minutes=5)

    def check_plan_reminders(self) -> None:
        """알림이 설정된 시간 일정을 검사해 발화 시각 창(remind_at ~ +5분) 안이면 알린다."""
        now = datetime.now()
        changed = False
        for plan in self.data.setdefault("plans", []):
            try:
                minutes = int(plan.get("reminder_minutes", -1))
            except (TypeError, ValueError):
                continue
            if minutes < 0 or plan.get("kind") == "long":
                continue
            start_text = str(plan.get("start", ""))
            if plan.get("reminder_fired") == start_text:
                continue
            try:
                start_dt = datetime.fromisoformat(start_text)
            except ValueError:
                continue
            remind_at = start_dt - timedelta(minutes=minutes)
            # 앱을 껐다 켰을 때 한참 지난 알림이 몰아서 울리지 않도록 5분 창으로 제한한다.
            if remind_at <= now < remind_at + self.REMINDER_GRACE:
                plan["reminder_fired"] = start_text
                changed = True
                self.notify_plan_reminder(plan, start_dt, minutes)
        if changed:
            self.save()

    def notify_plan_reminder(self, plan: dict, start_dt: datetime, minutes: int) -> None:
        title = str(plan.get("title", "")).strip() or self.tr("detail.untitled", "(제목 없음)")
        if minutes <= 0:
            message = self.tr("reminder.message.now", "지금 시작: {title}").format(title=title)
        else:
            message = self.tr("reminder.message.before", "{minutes}분 후 시작: {title} ({time})").format(
                minutes=minutes, title=title, time=f"{start_dt:%H:%M}"
            )
        tray = getattr(self, "tray", None)
        if tray is not None and tray.isVisible():
            tray.showMessage(self.app_display_name(), message, QSystemTrayIcon.Information, 10000)
        QApplication.beep()

    def find_plan(self, plan_id: str) -> dict | None:
        for plan in self.data.setdefault("plans", []):
            if plan.get("id") == plan_id:
                return plan
        return None

    def plan_display_text(self, plan: dict) -> str:
        title = plan.get("title", "")
        start = str(plan.get("start", "")).replace("T", " ")[:16]
        end = str(plan.get("end", "")).replace("T", " ")[:16]
        if plan.get("kind") == "long":
            return f"{title} | {start[:10]} - {end[:10]}"
        return f"{title} | {start[11:16]} - {end[11:16]}"

    def period_label(self, period: str) -> str:
        for period_key, label_key, fallback in RepeatWindow.PERIODS:
            if period_key == period:
                return translate(self.config.get("language", "ko"), label_key, fallback)
        return period

    def recurring_current_key(self, period: str) -> str:
        today = date.today()
        if period == "daily":
            return today.isoformat()
        if period == "weekly":
            year, week, _weekday = today.isocalendar()
            return f"{year}-W{week:02}"
        if period == "monthly":
            return today.strftime("%Y-%m")
        return today.strftime("%Y")

    def recurring_tasks_for_today(self) -> list[tuple[str, dict]]:
        rows: list[tuple[str, dict]] = []
        for period, _label_key, _fallback in RepeatWindow.PERIODS:
            rows.extend((period, task) for task in self.data.setdefault("recurring_tasks", {}).setdefault(period, []))
        return rows

    def find_recurring_task(self, period: str, task_id: str) -> dict | None:
        for task in self.data.setdefault("recurring_tasks", {}).setdefault(period, []):
            if task.get("id") == task_id:
                return task
        return None

    def set_recurring_done(self, period: str, task: dict, checked: bool) -> None:
        current = self.recurring_current_key(period)
        counted = task.setdefault("counted_keys", [])
        if checked:
            if current not in counted:
                task["done_count"] = int(task.get("done_count", 0)) + 1
                counted.append(current)
            task["done"] = current
        else:
            if task.get("done") == current and current in counted:
                task["done_count"] = max(0, int(task.get("done_count", 0)) - 1)
                counted.remove(current)
            task["done"] = ""
        self.save()
        if self.repeat_window and self.repeat_window.isVisible():
            self.repeat_window.refresh_all()

    def set_schedule(self, day: date, text: str) -> None:
        schedules = self.data.setdefault("schedules", {})
        clean = text.rstrip()
        current = schedules.get(day.isoformat(), "")
        if current == clean:
            return
        if clean:
            schedules[day.isoformat()] = clean
        else:
            schedules.pop(day.isoformat(), None)
        self.save()
        self.render_calendar()

    def previous_month(self) -> None:
        year = self.visible_month.year
        month = self.visible_month.month - 1
        if month == 0:
            year -= 1
            month = 12
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def next_month(self) -> None:
        year = self.visible_month.year
        month = self.visible_month.month + 1
        if month == 13:
            year += 1
            month = 1
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def go_to_today(self) -> None:
        self.go_to_date(date.today())

    def go_to_date(self, day: date) -> None:
        self.select_date(day)
        self.show_calendar()

    def select_date(self, day: date) -> None:
        self.selected_day = day
        self.visible_month = day.replace(day=1)
        self.render_calendar()

    def open_schedule_near(self, day: date) -> None:
        self.selected_day = day
        self.render_calendar()
        width, height = 430, 360
        sender = self.sender()
        if isinstance(sender, QWidget):
            point = sender.mapToGlobal(QPoint(12, 28))
            screen = QApplication.screenAt(point) or QApplication.primaryScreen()
            x, y = clamp_window_position(width, height, point.x(), point.y(), screen.availableGeometry())
            geometry = f"{width}x{height}+{x}+{y}"
        else:
            geometry = None
        self.open_schedule(day, geometry)

    def open_schedule(self, day: date, geometry: str | None = None) -> None:
        key = day.isoformat()
        if key in self.schedule_windows and self.schedule_windows[key].isVisible():
            self.schedule_windows[key].raise_()
            self.schedule_windows[key].activateWindow()
            return
        if geometry is None:
            width, height = 430, 360
            anchor = self.geometry()
            screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
            x, y = clamp_window_position(width, height, anchor.x() + 32, anchor.y() + 64, screen.availableGeometry())
            geometry = f"{width}x{height}+{x}+{y}"
        window = ScheduleWindow(self, day, geometry)
        self.schedule_windows[key] = window
        window.show()

    def open_settings(self) -> None:
        if self.settings_window and self.settings_window.isVisible():
            self.settings_window.raise_()
            self.settings_window.activateWindow()
            return
        self.settings_window = SettingsWindow(self)
        self.settings_window.show()

    def open_search(self, query: str = "") -> None:
        if self.search_window and self.search_window.isVisible():
            self.search_window.raise_()
            self.search_window.activateWindow()
            if query:
                self.search_window.query.setText(query)
            return
        self.search_window = SearchWindow(self)
        if query:
            self.search_window.query.setText(query)
        self.search_window.show()

    def open_search_from_header(self) -> None:
        query = self.search_input.text().strip() if hasattr(self, "search_input") else ""
        self.open_search(query)

    def open_detail_schedule(self) -> None:
        if self.detail_window and self.detail_window.isVisible():
            self.detail_window.raise_()
            self.detail_window.activateWindow()
            return
        self.detail_window = DetailScheduleWindow(self)
        self.detail_window.show()

    def open_clock(self) -> None:
        if self.clock_window and self.clock_window.isVisible():
            self.clock_window.raise_()
            self.clock_window.activateWindow()
            return
        self.clock_window = ClockWindow(self)
        self.clock_window.show()

    def open_repeat(self) -> None:
        if self.repeat_window and self.repeat_window.isVisible():
            self.repeat_window.raise_()
            self.repeat_window.activateWindow()
            return
        self.repeat_window = RepeatWindow(self)
        self.repeat_window.show()

    def reopen_settings(self) -> None:
        if self.settings_window:
            self.settings_window.close()
        self.open_settings()

    def create_memo(self) -> None:
        memo_id = datetime.now().strftime("%Y%m%d%H%M%S%f")
        self.open_memo(memo_id)

    def open_memo(self, memo_id: str, geometry: str | None = None) -> None:
        if memo_id in self.memo_windows and self.memo_windows[memo_id].isVisible():
            self.memo_windows[memo_id].raise_()
            return
        window = StickyMemoWindow(self, memo_id, geometry)
        self.memo_windows[memo_id] = window
        if self.memo_has_content(memo_id):
            self.remember_open_memo(memo_id, geometry_string(window))
        window.show()
        window.raise_()

    def restore_open_memos(self) -> None:
        """복원 목록에 남아 있고 내용이 있는 메모창만 다시 엽니다."""
        for memo_id, geometry in list(self.config.get("open_memos", {}).items()):
            if self.memo_has_content(memo_id):
                self.open_memo(memo_id, geometry)
            else:
                self.forget_open_memo(memo_id)

    def memo_has_content(self, memo_id: str) -> bool:
        return self.memo_store.has_content(memo_id) or bool(self.config.setdefault("memo_titles", {}).get(memo_id, "").strip())

    def remember_open_memo(self, memo_id: str, geometry: str) -> None:
        self.config.setdefault("open_memos", {})[memo_id] = geometry
        self.save()

    def forget_open_memo(self, memo_id: str) -> None:
        self.config.setdefault("open_memos", {}).pop(memo_id, None)
        self.save()

    def persist_open_memos(self) -> None:
        """종료 직전에 열린 메모의 내용과 위치를 한 번 더 저장합니다."""
        for _memo_id, window in list(self.memo_windows.items()):
            if window.isVisible():
                window.save_now()
        self.save()

    def persist_open_windows(self) -> None:
        """백업, 내보내기, 종료 전에 열린 편집창의 대기 중인 저장을 모두 반영합니다."""
        for _memo_id, window in list(self.memo_windows.items()):
            if window.isVisible():
                window.save_now()
        for _day_text, window in list(self.schedule_windows.items()):
            if window.isVisible():
                window.save_now()
        self.save()

    def recall_hidden_memos(self) -> None:
        """복원 대상 메모를 달력 근처로 다시 모아 화면 밖 메모를 회수합니다."""
        active_ids = [
            memo_id
            for memo_id in self.config.get("open_memos", {})
            if self.memo_has_content(memo_id)
        ]
        if not active_ids:
            return

        anchor = self.geometry()
        screen = QApplication.screenAt(anchor.center()) or QApplication.primaryScreen()
        available = screen.availableGeometry()
        base_x, base_y = clamp_window_position(280, 260, anchor.x() + 24, anchor.y() + 54, available, margin=12)

        for index, memo_id in enumerate(active_ids):
            window = self.memo_windows.get(memo_id)
            if window is None or not window.isVisible():
                self.open_memo(memo_id, self.config["open_memos"].get(memo_id))
                window = self.memo_windows.get(memo_id)
            if window is None:
                continue

            offset = index * 28
            x, y = clamp_window_position(window.width(), window.height(), base_x + offset, base_y + offset, available, margin=12)
            window.move(x, y)
            window.show()
            window.raise_()
            window.activateWindow()
            self.remember_open_memo(memo_id, geometry_string(window))

    def set_calendar_opacity(self, value: int) -> None:
        value = max(20, min(100, int(value)))
        self.config["calendar_opacity"] = value
        self.setWindowOpacity(value / 100)
        self.save()

    def set_startup(self, enabled: bool, show_message: bool = True) -> None:
        if LEGACY_STARTUP_PATH.exists():
            LEGACY_STARTUP_PATH.unlink()
        if enabled:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            launcher = pythonw if pythonw.exists() else Path(sys.executable)
            STARTUP_PATH.parent.mkdir(parents=True, exist_ok=True)
            STARTUP_PATH.write_text(
                f'@echo off\nstart "" "{launcher}" "{Path(__file__).resolve()}"\n',
                encoding="utf-8",
            )
        elif STARTUP_PATH.exists():
            STARTUP_PATH.unlink()
        if show_message:
            QMessageBox.information(self, APP_NAME, self.tr("message.startup.changed", "자동 실행 설정을 변경했습니다."))

    def startup_enabled(self) -> bool:
        return STARTUP_PATH.exists() or LEGACY_STARTUP_PATH.exists()

    def create_backup(self, destination: Path) -> Path:
        self.persist_open_windows()
        return create_backup_archive(self.config, destination)

    def export_calendar_file(self, destination: Path) -> Path:
        self.persist_open_windows()
        return export_ics(self.data, destination)

    def apply_theme(self) -> FoxCalendarApp:
        new_colors = resolve_theme(self.config)
        self.colors.update(new_colors)
        self.refresh_theme_styles()
        self.render_calendar()
        for window in (
            self.clock_window,
            self.repeat_window,
            self.settings_window,
            self.search_window,
            self.detail_window,
        ):
            if window and window.isVisible() and hasattr(window, "apply_theme"):
                window.apply_theme()
        for window in list(self.schedule_windows.values()):
            if window and window.isVisible():
                window.apply_theme()
        self.apply_note_theme()
        self.update()
        return self

    def apply_note_theme(self) -> None:
        for window in list(self.memo_windows.values()):
            if window.isVisible():
                window.apply_note_theme()

    def apply_font_family(self, family: str) -> None:
        set_active_font_family(family or DEFAULT_FONT_FAMILY)
        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.setFont(app_font())
        self.refresh_font_styles()
        self.render_calendar()
        self.apply_note_theme()
        for window in (
            self.clock_window,
            self.repeat_window,
            self.search_window,
            self.detail_window,
        ):
            if window and window.isVisible() and hasattr(window, "apply_theme"):
                window.apply_theme()

    def apply_language(self, source=None) -> None:
        search_text = self.search_input.text() if hasattr(self, "search_input") else ""
        self.setWindowTitle(self.app_display_name())
        self.build_ui()
        if hasattr(self, "search_input"):
            self.search_input.setText(search_text)
        self.render_calendar()
        self.refresh_tray_texts()
        for window in (
            self.clock_window,
            self.repeat_window,
            self.settings_window,
            self.search_window,
            self.detail_window,
        ):
            if window and window is not source and window.isVisible() and hasattr(window, "apply_language"):
                window.apply_language()
        for window in list(self.schedule_windows.values()):
            if window and window is not source and window.isVisible() and hasattr(window, "apply_language"):
                window.apply_language()

    def refresh_font_styles(self) -> None:
        if hasattr(self, "month_label"):
            self.month_label.setFont(app_font(14, QFont.Bold))
        if hasattr(self, "search_input"):
            self.search_input.setFont(app_font(9))
        for label in getattr(self, "weekday_labels", []):
            label.setFont(app_font(9, QFont.Bold))
        for cell in self.day_cells:
            cell.update()

    def refresh_theme_styles(self) -> None:
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "month_label"):
            self.month_label.setStyleSheet(f"color: {c['text']};")
        if hasattr(self, "header_frame"):
            self.header_frame.setStyleSheet(self.calendar_header_style())
        if hasattr(self, "grid_frame"):
            self.grid_frame.setStyleSheet(self.calendar_grid_style())
        if hasattr(self, "footer_frame"):
            self.footer_frame.setStyleSheet(self.calendar_footer_style())
        if hasattr(self, "search_input"):
            self.search_input.setStyleSheet(self.calendar_search_style())
        if hasattr(self, "search_action"):
            self.search_action.setIcon(self.search_icon())
        if hasattr(self, "header_separator"):
            self.header_separator.setStyleSheet(f"background: {c['border']};")
        for button in getattr(self, "header_buttons", []):
            button.setStyleSheet(self.header_button_style())
        for button in getattr(self, "icon_buttons", []):
            button.refresh_style()
            button.update()
        for label in getattr(self, "weekday_labels", []):
            col = int(label.property("weekday_col") or -1)
            weekday_color = c["text"]
            if col == 0:
                weekday_color = c["sunday"]
            elif col == 6:
                weekday_color = c["saturday"]
            label.setStyleSheet(
                f"background: {c['weekday']}; color: {weekday_color};"
                f"border: 0.5px solid {c['grid']};"
            )
        for cell in self.day_cells:
            cell.update()

    def closeEvent(self, event) -> None:
        self.persist_open_windows()
        self.save()
        if self.force_quit:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    load_app_font(app, load_config())
    app.setQuitOnLastWindowClosed(False)
    window = FoxCalendarApp()
    app.main_window = window  # type: ignore[attr-defined]
    app.aboutToQuit.connect(window.persist_open_windows)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
