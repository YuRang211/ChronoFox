from __future__ import annotations

import calendar
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import holidays as holiday_lib
except ImportError:
    holiday_lib = None

try:
    from PySide6.QtCore import QDate, QDateTime, QEvent, QPoint, QRect, QRectF, QSize, Qt, QTime, QTimer, Signal
    from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPen
    from PySide6.QtWidgets import (
        QApplication,
        QComboBox,
        QDateEdit,
        QDateTimeEdit,
        QCheckBox,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMenu,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizeGrip,
        QSlider,
        QSpinBox,
        QStackedWidget,
        QSystemTrayIcon,
        QTabWidget,
        QTextBrowser,
        QTextEdit,
        QTimeEdit,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:
    raise SystemExit(
        "PySide6가 설치되어 있지 않습니다.\n"
        "터미널에서 아래 명령을 먼저 실행해 주세요:\n\n"
        "python -m pip install PySide6"
    ) from exc

from app_config import load_config, load_data, save_config, save_data
from app_constants import APP_DIR, APP_ICON_PATH, APP_NAME, DEFAULT_FONT_FAMILY, DEFAULT_FONT_LABEL
from app_constants import STARTUP_PATH
from app_models import MemoStore
from app_theme import prettify_holiday_name, resolve_note_theme, resolve_theme
from app_ui import add_soft_shadow, app_font, clear_layout, geometry_string, load_app_font, parse_geometry
from app_ui import set_active_font_family, system_font_families
from app_widgets import IconButton, RoundedWindow
from clock_window import ClockWindow
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
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(54)

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
        painter.setPen(QPen(QColor(colors["grid"]), 0.45))
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        if self.state == "selected":
            painter.setPen(QPen(QColor(colors["selected_border"]), 1.7))
            painter.drawRect(self.rect().adjusted(1, 1, -2, -2))
        elif self.state == "today":
            painter.setPen(QPen(QColor(colors["today_border"]), 1.5))
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
        painter.setFont(app_font(9))
        painter.drawText(8, 18, str(self.day.day))

        if self.holiday:
            holiday_color = colors["other_text"] if self.state == "other" else colors["holiday"]
            holiday_font = app_font(8)
            painter.setFont(holiday_font)
            painter.setPen(QColor(holiday_color))
            metrics = painter.fontMetrics()
            holiday_rect = QRect(30, 4, max(10, self.width() - 38), 18)
            painter.drawText(
                holiday_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                metrics.elidedText(self.holiday, Qt.ElideRight, holiday_rect.width()),
            )

        painter.setFont(app_font(9))
        metrics = painter.fontMetrics()
        base_y = 26
        for plan in self.plan_bars:
            y = base_y + int(plan.get("lane", 0)) * 18
            if y + 13 > self.height() - 18:
                continue
            color = QColor(plan.get("color", colors["accent"]))
            x = -2 if plan.get("from_prev") else 7
            right_margin = -2 if plan.get("to_next") else 7
            rect = QRect(x, y, max(8, self.width() - x - right_margin), 13)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setPen(QColor("#ffffff"))
            painter.setFont(app_font(8, QFont.Bold))
            text_rect = rect.adjusted(4, -1, -3, 0)
            title = plan.get("title", "") if plan.get("show_title") else ""
            painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(title, Qt.ElideRight, text_rect.width()))
            y += 18

        painter.setFont(app_font(9))
        metrics = painter.fontMetrics()
        used_lanes = [int(plan.get("lane", 0)) for plan in self.plan_bars]
        y = max(base_y + (max(used_lanes) + 1) * 18 + 8 if used_lanes else 42, 42)
        available = max(10, self.width() - 14)
        painter.setPen(QColor(fg))
        for line in self.lines:
            if y + metrics.height() > self.height() - 4:
                break
            painter.drawText(8, y, metrics.elidedText(line, Qt.ElideRight, available))
            y += 16

class FoxCalendarApp(RoundedWindow):
    """달력, 트레이 아이콘, 일정, 메모창을 관리하는 메인 앱입니다."""

    def __init__(self) -> None:
        self.config = load_config()
        self.data = load_data(self.config)
        self.colors = resolve_theme(self.config)
        super().__init__(self.colors)
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
        self.holiday_cache: dict[int, dict[date, str]] = {}
        self.force_quit = False
        width, height, x, y = parse_geometry(self.config.get("calendar_geometry", "760x520+180+40"), (760, 520, 180, 40))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(520, 360)
        self.setWindowOpacity(self.config.get("calendar_opacity", 56) / 100)
        self.build_ui()
        self.setup_tray()
        self.render_calendar()
        self.restore_open_memos()

    def save(self) -> None:
        self.config["calendar_geometry"] = geometry_string(self)
        save_config(self.config)
        save_data(self.data)

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
        layout.setContentsMargins(8, 6, 8, 8)
        layout.setSpacing(6)

        self.day_cells = []
        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
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
        self.month_label.setFont(app_font(12, QFont.Bold))

        right = QHBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.addStretch()
        right.addWidget(menu_button)
        right.addWidget(today_button)
        right.addWidget(prev_button)
        right.addWidget(next_button)
        header.addWidget(self.month_label, 0, 1)
        header.addLayout(right, 0, 2)
        layout.addLayout(header)

        self.grid = QGridLayout()
        self.grid.setSpacing(0)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.weekday_labels = []
        for col, text in enumerate(["일", "월", "화", "수", "목", "금", "토"]):
            label = QLabel(text)
            label.setProperty("weekday_col", col)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(9, QFont.Bold))
            label.setFixedHeight(20)
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
        layout.addLayout(self.grid, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(QSizeGrip(self))
        layout.addLayout(bottom)
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
        search_action = menu.addAction("검색")
        clock_action = menu.addAction("시계")
        repeat_action = menu.addAction("해야 할 일")
        menu.addSeparator()
        memo_action = menu.addAction("새 메모")
        recall_memos_action = menu.addAction("숨은 메모 불러오기")
        settings_action = menu.addAction("설정")
        menu.addSeparator()
        hide_action = menu.addAction("숨기기")

        search_action.triggered.connect(self.open_search)
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
        self.tray.setToolTip(APP_NAME)

        menu = QMenu()
        show_action = QAction("Fox Calendar 열기", self)
        memo_action = QAction("새 메모", self)
        settings_action = QAction("설정", self)
        quit_action = QAction("종료", self)

        show_action.triggered.connect(self.show_calendar)
        memo_action.triggered.connect(self.create_memo)
        settings_action.triggered.connect(self.open_settings)
        quit_action.triggered.connect(self.quit_from_tray)

        menu.addAction(show_action)
        menu.addAction(memo_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.handle_tray_activated)
        self.tray.show()

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
        self.persist_open_memos()
        self.save()
        QApplication.quit()

    def header_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel2']}; border-radius: 5px; }}"
        )

    def render_calendar(self) -> None:
        """현재 보이는 월의 날짜, 일정, 공휴일을 날짜칸에 반영합니다."""
        self.month_label.setText(f"{self.visible_month.year}년 {self.visible_month.month}월")
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(self.visible_month.year, self.visible_month.month)
        days = [day for week in weeks for day in week]
        for index, cell in enumerate(self.day_cells):
            if index >= len(days):
                cell.hide()
                continue
            cell.show()
            day = days[index]
            lines: list[str] = []
            holiday = self.get_holiday(day)
            plan_bars = self.plan_bars_for_day(day)
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
        day_text = day.isoformat()
        return [
            plan
            for plan in self.sorted_plans()
            if self.plan_start_date(plan) <= day <= self.plan_end_date(plan) and day_text
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
        colors = ["#3abf7a", "#e47d7d", "#7d8bd9", "#d9a441", "#5aa7d9"]
        lane_ends: list[date] = []
        lanes: dict[str, int] = {}
        for plan in self.sorted_plans():
            start_day = self.plan_start_date(plan)
            end_day = self.plan_end_date(plan)
            lane = next((idx for idx, lane_end in enumerate(lane_ends) if start_day > lane_end), None)
            if lane is None:
                lane = len(lane_ends)
                lane_ends.append(end_day)
            else:
                lane_ends[lane] = end_day
            lanes[str(plan.get("id", id(plan)))] = lane

        bars: list[dict] = []
        for index, plan in enumerate(self.sorted_plans()):
            start_day = self.plan_start_date(plan)
            end_day = self.plan_end_date(plan)
            if not (start_day <= day <= end_day):
                continue
            bars.append(
                {
                    "title": plan.get("title", ""),
                    "color": plan.get("color") or colors[index % len(colors)],
                    "from_prev": day > start_day,
                    "to_next": day < end_day,
                    "show_title": day == start_day,
                    "lane": lanes.get(str(plan.get("id", id(plan))), 0),
                }
            )
        return bars

    def add_plan(self, plan: dict) -> None:
        self.data.setdefault("plans", []).append(plan)
        self.save()
        self.render_calendar()
        schedule = self.schedule_windows.get(str(plan.get("start", ""))[:10])
        if schedule and schedule.isVisible():
            schedule.apply_theme()

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

    def delete_plan(self, plan_id: str) -> None:
        self.data.setdefault("plans", [])[:] = [
            plan for plan in self.data.setdefault("plans", []) if plan.get("id") != plan_id
        ]
        self.save()
        self.render_calendar()

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
        return dict(RepeatWindow.PERIODS).get(period, period)

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
        for period, _label in RepeatWindow.PERIODS:
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
            screen = QApplication.primaryScreen().availableGeometry()
            x = min(max(screen.left(), point.x()), screen.right() - width)
            y = min(max(screen.top(), point.y()), screen.bottom() - height)
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
            available = screen.availableGeometry()
            x = min(max(available.left(), anchor.x() + 32), available.right() - width)
            y = min(max(available.top(), anchor.y() + 64), available.bottom() - height)
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

    def open_search(self) -> None:
        if self.search_window and self.search_window.isVisible():
            self.search_window.raise_()
            self.search_window.activateWindow()
            return
        self.search_window = SearchWindow(self)
        self.search_window.show()

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
        for memo_id, window in list(self.memo_windows.items()):
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
        base_x = min(max(available.left() + 12, anchor.x() + 24), available.right() - 280)
        base_y = min(max(available.top() + 12, anchor.y() + 54), available.bottom() - 260)

        for index, memo_id in enumerate(active_ids):
            window = self.memo_windows.get(memo_id)
            if window is None or not window.isVisible():
                self.open_memo(memo_id, self.config["open_memos"].get(memo_id))
                window = self.memo_windows.get(memo_id)
            if window is None:
                continue

            offset = index * 28
            x = min(base_x + offset, available.right() - window.width())
            y = min(base_y + offset, available.bottom() - window.height())
            window.move(max(available.left(), x), max(available.top(), y))
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
            QMessageBox.information(self, APP_NAME, "자동 실행 설정을 변경했습니다.")

    def apply_theme(self) -> "FoxCalendarApp":
        new_colors = resolve_theme(self.config)
        self.colors.update(new_colors)
        self.refresh_theme_styles()
        self.render_calendar()
        for window in (
            self.clock_window,
            self.repeat_window,
            self.settings_window,
            self.search_window,
        ):
            if window and window.isVisible() and hasattr(window, "apply_theme"):
                window.apply_theme()
        for window in list(self.schedule_windows.values()):
            if window and window.isVisible():
                window.apply_theme()
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
        ):
            if window and window.isVisible() and hasattr(window, "apply_theme"):
                window.apply_theme()

    def refresh_font_styles(self) -> None:
        if hasattr(self, "month_label"):
            self.month_label.setFont(app_font(12, QFont.Bold))
        for label in getattr(self, "weekday_labels", []):
            label.setFont(app_font(9, QFont.Bold))
        for cell in self.day_cells:
            cell.update()

    def refresh_theme_styles(self) -> None:
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "month_label"):
            self.month_label.setStyleSheet(f"color: {c['text']};")
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
        self.persist_open_memos()
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
    app.aboutToQuit.connect(window.persist_open_memos)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
