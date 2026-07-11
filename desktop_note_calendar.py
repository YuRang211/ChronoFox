"""ChronoFox 데스크톱 앱의 진입점. 바탕화면 캘린더 메인 창 FoxCalendarApp을 정의하고
서비스(PlanService/TrayController/WindowManager/AppStore)를 조립해 실행한다."""

from __future__ import annotations

import calendar
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import holidays as holiday_lib
except ImportError:
    holiday_lib = None

try:
    from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QTimer, Signal
    from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
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

from app_config import RecoveryNotice, consume_recovery_notices, create_backup_archive, load_config, load_data, save_config, save_data
from app_constants import (
    APP_ICON_PATH,
    APP_NAME,
    DEFAULT_CALENDAR_GEOMETRY,
    DEFAULT_FONT_FAMILY,
    LEGACY_STARTUP_PATH,
    STARTUP_PATH,
)
from app_domain import PlanService
from app_i18n import TrMixin
from app_integrations import export_ics
from app_logging import setup_logging
from app_models import MemoStore
from app_scheduler import NotificationScheduler
from app_store import AppStore
from app_theme import prettify_holiday_name, resolve_theme
from app_ui import (
    app_font,
    clear_layout,
    geometry_string,
    load_app_font,
    parse_geometry,
    set_active_font_family,
)
from app_widgets import IconButton, RoundedWindow
from clock.alarms import ClockAlarmMixin
from clock_window import ClockWindow
from detail_schedule_window import DetailScheduleWindow
from schedule_window import ScheduleWindow
from todo_window import RepeatWindow
from tray_controller import TrayController
from window_manager import WindowManager

if TYPE_CHECKING:
    from memo_window import StickyMemoWindow
    from search_window import SearchWindow
    from settings_window import SettingsWindow


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
        """달력 날짜 셀에 표시할 날짜/일정 요약/상태/공휴일/계획 막대 데이터를 채웁니다."""
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

def _format_notices(notices: list[RecoveryNotice], tr) -> str:
    """복구 알림 목록을 사용자에게 보여줄 한 개의 메시지 문자열로 합칩니다."""
    messages = []
    for notice in notices:
        if notice.kind == "corrupt_reset":
            template = tr("recovery.corrupt_reset", "저장 파일이 손상되어 초기화했습니다. 원본은 다음 위치에 보관했습니다:\n{quarantine}")
            messages.append(template.format(path=notice.path, quarantine=notice.quarantine))
        elif notice.kind == "newer_schema":
            template = tr(
                "recovery.newer_schema",
                "더 새로운 버전의 ChronoFox가 만든 데이터입니다. 안전을 위해 이 세션의 변경은 저장되지 않을 수 있습니다: {path}",
            )
            messages.append(template.format(path=notice.path, quarantine=notice.quarantine))
    return "\n\n".join(messages)


class FoxCalendarApp(TrMixin, ClockAlarmMixin, RoundedWindow):
    """달력, 트레이 아이콘, 일정, 메모창을 관리하는 메인 앱입니다."""

    def __init__(self) -> None:
        config = load_config()
        data = load_data(config)
        self.store = AppStore(config, data, save_config, save_data)
        self.colors = resolve_theme(self.store)
        super().__init__(self.colors)
        self.draw_window_border = False
        self.icon = QIcon(str(APP_ICON_PATH)) if APP_ICON_PATH.exists() else QIcon()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self.icon)
        self.memo_store = MemoStore(Path(self.store.get("notes_dir")))
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

        # S4(M6/D9): plan/schedule 변경은 이제 store.notify()로 알려진다 — 달력은
        # 수동 fanout 대신 구독으로 스스로 다시 그린다.
        self.store.subscribe("plans", self.render_calendar)
        self.store.subscribe("schedules", self.render_calendar)

        # 백그라운드 알람/타이머/스톱워치를 위한 변수 설정
        self.app = self
        self.active_alert_alarm = None
        self._alert_queue: list[tuple[dict, str]] = []
        self._alert_active = False
        self.alert_player = None
        self.alert_audio = None
        self.stopwatch_running = False
        self.stopwatch_start_time = None
        self.stopwatch_elapsed_before_pause = 0.0
        self.timer_running = False
        self.timer_start_time = None
        self.timer_total_duration = 0.0
        self.timer_remaining_before_pause_ms = 0
        self.timer_remaining_ms = 0

        width, height, x, y = parse_geometry(self.store.get("calendar_geometry", DEFAULT_CALENDAR_GEOMETRY), (980, 620, 180, 40))
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(760, 480)
        self.setWindowOpacity(self.store.get("calendar_opacity", 56) / 100)
        self.build_ui()
        self.setup_tray()
        self.render_calendar()
        self.restore_open_memos()

        # F2: 알람(1s due-based)/리마인더(30s)/todo 날짜 롤오버를 단일 스케줄러로 통합.
        # 코어(NotificationScheduler)는 Qt 비의존이며, scheduler_timer는 얇은 QTimer 어댑터다.
        self.scheduler = NotificationScheduler(now_fn=self.current_clock_datetime, alarms_fn=self.alarms_for_scheduler)
        self.scheduler.on_alarm_due.append(self.on_scheduler_alarm_due)
        self.scheduler.on_alarms_missed.append(self.on_scheduler_alarms_missed)
        self.scheduler.on_reminder_scan.append(self.check_plan_reminders)
        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.setInterval(1000)
        self.scheduler_timer.timeout.connect(self.on_scheduler_tick)
        self.scheduler_timer.start()
        # 일정 알림은 시계창과 무관하게 메인 앱이 상주 검사한다 (UX14). 앱 시작 직후
        # 첫 30초를 기다리지 않도록 즉시 한 번 검사한다.
        self.check_plan_reminders()

        notices = consume_recovery_notices()
        if notices:
            QMessageBox.warning(self, self.tr("recovery.title", "데이터 복구 안내"), _format_notices(notices, self.tr))

    @property
    def config(self) -> dict:
        """app.store를 거치지 않는 레거시 코드 호환용 config dict 접근자입니다."""
        return self.store._config

    @property
    def data(self) -> dict:
        """app.store를 거치지 않는 레거시 코드 호환용 data dict 접근자입니다."""
        return self.store._data

    # S4(M5/D8): 트레이·창 오케스트레이션·plan 도메인 로직은 서비스 객체로 위임한다.
    # 지연 생성 property로 두어 FoxCalendarApp.__new__(...)로 __init__을 건너뛴
    # 테스트 픽스처(예: tests/test_recurring_periods.py)에서도 안전하게 접근된다.
    @property
    def tray_controller(self) -> TrayController:
        """지연 초기화된 TrayController 인스턴스를 반환합니다."""
        controller = self.__dict__.get("_tray_controller")
        if controller is None:
            controller = TrayController(self)
            self.__dict__["_tray_controller"] = controller
        return controller

    @property
    def window_manager(self) -> WindowManager:
        """지연 초기화된 WindowManager 인스턴스를 반환합니다."""
        manager = self.__dict__.get("_window_manager")
        if manager is None:
            manager = WindowManager(self)
            self.__dict__["_window_manager"] = manager
        return manager

    @property
    def plan_service(self) -> PlanService:
        """지연 초기화된 PlanService 인스턴스를 반환합니다."""
        service = self.__dict__.get("_plan_service")
        if service is None:
            service = PlanService(self)
            self.__dict__["_plan_service"] = service
        return service

    def save(self) -> None:
        # S4(M6): geometry는 silent set — 창을 옮길 때마다 구독자가 깨면 안 된다.
        """현재 config/data를 디스크에 저장합니다."""
        self.store.set("calendar_geometry", geometry_string(self), notify_topic=None)
        self.store.save()

    def app_display_name(self) -> str:
        """현재 언어에 맞는 앱 표시 이름을 반환합니다."""
        return self.tr("app.name", APP_NAME)

    def dialog_colors(self) -> dict[str, str]:
        """다이얼로그에서 사용할 현재 테마 색상 dict를 반환합니다."""
        return resolve_theme(self.store)

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
        prev_button.setToolTip(self.tr("calendar.tooltip.prev", "이전 달"))
        next_button.setToolTip(self.tr("calendar.tooltip.next", "다음 달"))
        menu_button.setToolTip(self.tr("calendar.tooltip.menu", "메뉴"))
        today_button.setToolTip(self.tr("calendar.tooltip.today", "오늘로 이동"))
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
        """캘린더 헤더의 메뉴를 엽니다."""
        menu = QMenu(self)
        menu.setAttribute(Qt.WA_TranslucentBackground, True)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setStyleSheet(self.tray_menu_style())
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

    # S4(M5/D8): 트레이 로직은 TrayController가 담당한다. app은 위임만 한다
    # (clock/alarms.py의 getattr(self.app, "tray", None) 등 기존 호출부는
    # TrayController.setup_tray()가 self.tray를 app 위에 그대로 만들어 유지된다).
    def setup_tray(self) -> None:
        """시스템 트레이 아이콘과 메뉴를 초기화합니다."""
        self.tray_controller.setup_tray()

    def tray_menu_style(self) -> str:
        """트레이 메뉴 QSS 스타일 문자열을 만듭니다."""
        return self.tray_controller.tray_menu_style()

    def update_tray_menu(self) -> None:
        """트레이 메뉴 항목을 현재 상태로 갱신합니다."""
        self.tray_controller.update_tray_menu()

    def refresh_tray_texts(self) -> None:
        """언어가 바뀐 뒤 트레이 메뉴 텍스트를 다시 그립니다."""
        self.tray_controller.refresh_tray_texts()

    def handle_tray_activated(self, reason) -> None:
        """트레이 아이콘 클릭/더블클릭 이벤트를 처리합니다."""
        self.tray_controller.handle_tray_activated(reason)

    def show_calendar(self) -> None:
        """메인 캘린더 창을 화면에 보여줍니다."""
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
        """Qt 이벤트를 가로채, 창이 다시 활성화될 때 메모 창들을 캘린더 위로 올립니다."""
        if event.type() == QEvent.WindowActivate:
            self.raise_memos_above_calendar()
        return super().event(event)

    def quit_from_tray(self) -> None:
        """트레이 메뉴에서 앱을 종료합니다."""
        self.tray_controller.quit_from_tray()

    def header_button_style(self) -> str:
        """캘린더 헤더 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ color: {c['text']}; background: transparent; border: none; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c.get('button_hover', c['panel2'])}; border-radius: 6px; }}"
        )

    def calendar_header_style(self) -> str:
        """캘린더 헤더 영역 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QFrame#calendarHeader {{ background: {c.get('header', c['panel'])}; "
            f"border: 1px solid {c['border']}; border-bottom: none; "
            f"border-top-left-radius: {self.radius}px; border-top-right-radius: {self.radius}px; }}"
        )

    def calendar_grid_style(self) -> str:
        """캘린더 날짜 그리드 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QFrame#calendarGridFrame {{ background: {c['cell']}; border: 1px solid {c['border']}; "
            "border-top: none; border-bottom: none; border-radius: 0px; }}"
        )

    def calendar_footer_style(self) -> str:
        """캘린더 하단 영역 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QFrame#calendarFooter {{ background: {c.get('header', c['panel'])}; "
            f"border: 1px solid {c['border']}; border-top: none; "
            f"border-bottom-left-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; }}"
        )

    def calendar_search_style(self) -> str:
        """캘린더 검색창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit#calendarSearchInput {{ background: {c.get('input_bg', c['panel2'])}; color: {c['text']}; "
            f"border: 1px solid {c.get('input_border', c['border'])}; border-radius: 6px; "
            "padding: 5px 10px; }}"
            f"QLineEdit#calendarSearchInput:focus {{ border-color: {c['accent']}; }}"
            f"QLineEdit#calendarSearchInput::placeholder {{ color: {c['muted']}; }}"
        )

    def search_icon(self) -> QIcon:
        """검색 아이콘을 그립니다."""
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
        """현재 언어에 맞는 '연 월' 제목 문자열을 반환합니다."""
        month_name = self.tr(f"calendar.month.{month.month}", str(month.month))
        return self.tr("calendar.month_title", "{year}년 {month}월").format(
            year=month.year,
            month=month_name,
        )

    def get_holiday(self, day: date) -> str:
        """특정 날짜의 공휴일 이름을 반환합니다(없으면 빈 문자열)."""
        if not self.store.get("holiday_enabled", True):
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
                logging.getLogger(__name__).exception("holiday lookup failed (year=%s)", year)
                holidays_by_date = {}

        self.holiday_cache[year] = holidays_by_date
        return holidays_by_date

    # S4(M5/D8): plan/schedule 도메인 로직은 PlanService가 담당한다. app은 위임만 한다.
    def get_schedule(self, day: date) -> str:
        """특정 날짜의 일정 리스트를 반환합니다."""
        return self.plan_service.get_schedule(day)

    def plans_for_day(self, day: date) -> list[dict]:
        """특정 날짜에 걸쳐 있는 계획 목록을 반환합니다."""
        return self.plan_service.plans_for_day(day)

    def sorted_plans(self) -> list[dict]:
        """계획 목록을 시작일 기준으로 정렬해 반환합니다."""
        return self.plan_service.sorted_plans()

    def plan_start_date(self, plan: dict) -> date:
        """계획의 시작 날짜를 반환합니다."""
        return self.plan_service.plan_start_date(plan)

    def plan_end_date(self, plan: dict) -> date:
        """계획의 종료 날짜를 반환합니다."""
        return self.plan_service.plan_end_date(plan)

    def plan_bars_for_day(self, day: date) -> list[dict]:
        """특정 날짜에 그릴 계획 막대(bar) 정보를 계산합니다."""
        return self.plan_service.plan_bars_for_day(day)

    def plan_bars_for_days(self, days: list[date]) -> dict[date, list[dict]]:
        """여러 날짜에 걸쳐 그릴 계획 막대(bar) 정보를 계산합니다."""
        return self.plan_service.plan_bars_for_days(days)

    def add_plan(self, plan: dict) -> None:
        """새 계획을 추가하고 저장합니다."""
        self.plan_service.add_plan(plan)

    def update_plan(self, updated_plan: dict) -> None:
        """기존 계획 내용을 수정하고 저장합니다."""
        self.plan_service.update_plan(updated_plan)

    def delete_plan(self, plan_id: str) -> None:
        """계획을 삭제하고 저장합니다."""
        self.plan_service.delete_plan(plan_id)

    def on_scheduler_tick(self) -> None:
        """scheduler_timer(1s)의 QTimer 어댑터. 알람 due 스캔은 scheduler.tick()이,
        카운트다운 타이머(monotonic 의미론, D10)는 그대로 여기서 검사한다."""
        self.scheduler.tick()
        self.check_background_timer()

    def check_background_timer(self) -> None:
        """백그라운드 상태에서도 알람/리마인더를 확인하도록 주기적으로 호출됩니다."""
        if self.timer_running and self.timer_start_time is not None:
            import time
            from math import ceil
            elapsed_ms = int((time.monotonic() - self.timer_start_time) * 1000)
            self.timer_remaining_ms = max(0, int(ceil(self.timer_total_duration - elapsed_ms)))
            if self.timer_remaining_ms == 0:
                self.timer_running = False
                self.timer_start_time = None
                self.timer_remaining_before_pause_ms = 0
                self.show_alert(self.tr("timer.finished", "타이머가 끝났습니다."))

    def current_stopwatch_elapsed(self) -> float:
        """현재 스톱워치 경과 시간을 반환합니다."""
        import time
        elapsed = self.stopwatch_elapsed_before_pause
        if self.stopwatch_running and self.stopwatch_start_time is not None:
            elapsed += time.monotonic() - self.stopwatch_start_time
        return elapsed

    def current_timer_remaining_ms(self) -> int:
        """현재 타이머 남은 시간(ms)을 반환합니다."""
        import time
        from math import ceil
        if not self.timer_running or self.timer_start_time is None:
            return max(0, int(self.timer_remaining_before_pause_ms or self.timer_remaining_ms))
        elapsed_ms = int((time.monotonic() - self.timer_start_time) * 1000)
        return max(0, int(ceil(self.timer_total_duration - elapsed_ms)))

    def format_stopwatch_tray(self, elapsed: float) -> str:
        """트레이 툴팁에 표시할 스톱워치 문자열을 만듭니다."""
        total_sec = max(0, int(elapsed))
        hours = total_sec // 3600
        minutes = (total_sec % 3600) // 60
        seconds = total_sec % 60
        if hours:
            return f"{hours:02}:{minutes:02}:{seconds:02}"
        return f"{minutes:02}:{seconds:02}"

    def format_timer_tray(self, total_ms: int) -> str:
        """트레이 툴팁에 표시할 타이머 문자열을 만듭니다."""
        total_ms = max(0, int(total_ms))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) // 1000
        if hours:
            return f"{hours:02}:{minutes:02}:{seconds:02}"
        return f"{minutes:02}:{seconds:02}"

    def open_clock_tab(self, index: int) -> None:
        """시계 창을 특정 탭이 선택된 상태로 엽니다."""
        self.open_clock()
        if self.clock_window:
            self.clock_window.switch_tab(index)
            self.clock_window.show()
            self.clock_window.raise_()
            self.clock_window.activateWindow()

    REMINDER_GRACE = timedelta(minutes=5)

    def check_plan_reminders(self) -> None:
        """알림이 설정된 시간 일정을 검사해 발화 시각 창(remind_at ~ +5분) 안이면 알린다."""
        now = datetime.now()
        changed = False
        for plan in self.store.plans():
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
        """계획 리마인더를 사용자에게 알립니다."""
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
        """id로 계획을 찾아 반환합니다."""
        return self.plan_service.find_plan(plan_id)

    def plan_display_text(self, plan: dict) -> str:
        """계획을 화면에 보여줄 문자열로 변환합니다."""
        return self.plan_service.plan_display_text(plan)

    def period_label(self, period: str) -> str:
        """반복 주기(daily/weekly/monthly/yearly)를 화면용 라벨로 변환합니다."""
        return self.plan_service.period_label(period)

    def recurring_current_key(self, period: str) -> str:
        """현재 반복 주기에 해당하는 날짜 키를 반환합니다."""
        return self.plan_service.recurring_current_key(period)

    def recurring_tasks_for_today(self) -> list[tuple[str, dict]]:
        """오늘 기준으로 표시할 반복 작업 목록을 반환합니다."""
        return self.plan_service.recurring_tasks_for_today()

    def find_recurring_task(self, period: str, task_id: str) -> dict | None:
        """id로 반복 작업을 찾아 반환합니다."""
        return self.plan_service.find_recurring_task(period, task_id)

    def set_recurring_done(self, period: str, task: dict, checked: bool) -> None:
        """반복 작업의 완료 여부를 갱신합니다."""
        self.plan_service.set_recurring_done(period, task, checked)

    def set_schedule(self, day: date, text: str) -> None:
        """특정 날짜의 일정 리스트를 저장합니다."""
        self.plan_service.set_schedule(day, text)

    def previous_month(self) -> None:
        """달력을 이전 달로 이동합니다."""
        year = self.visible_month.year
        month = self.visible_month.month - 1
        if month == 0:
            year -= 1
            month = 12
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def next_month(self) -> None:
        """달력을 다음 달로 이동합니다."""
        year = self.visible_month.year
        month = self.visible_month.month + 1
        if month == 13:
            year += 1
            month = 1
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def go_to_today(self) -> None:
        """달력을 오늘 날짜로 이동합니다."""
        self.go_to_date(date.today())

    def go_to_date(self, day: date) -> None:
        """달력을 지정한 날짜로 이동합니다."""
        self.select_date(day)
        self.show_calendar()

    def select_date(self, day: date) -> None:
        """달력에서 특정 날짜를 선택합니다."""
        self.selected_day = day
        self.visible_month = day.replace(day=1)
        self.render_calendar()

    # S4(M5/D8): 창 열기/영속 로직은 WindowManager가 담당한다. app은 위임만 하며
    # 창 슬롯 속성(app.detail_window 등)은 그대로 app 위에서 관리된다 — 8개 창
    # 파일의 self.app.detail_window = None 같은 기존 참조가 무수정으로 동작한다.
    def open_schedule_near(self, day: date) -> None:
        """가장 가까운 일정 창을 찾아 엽니다."""
        self.window_manager.open_schedule_near(day)

    def open_schedule(self, day: date, geometry: str | None = None) -> None:
        """특정 날짜의 일정 창을 엽니다."""
        self.window_manager.open_schedule(day, geometry)

    def open_settings(self) -> None:
        """설정 창을 엽니다."""
        self.window_manager.open_settings()

    def open_search(self, query: str = "") -> None:
        """검색 창을 엽니다."""
        self.window_manager.open_search(query)

    def open_search_from_header(self) -> None:
        """헤더의 검색 버튼으로 검색 창을 엽니다."""
        query = self.search_input.text().strip() if hasattr(self, "search_input") else ""
        self.open_search(query)

    def open_detail_schedule(self) -> None:
        """세부 일정(월간/작업/보관함) 창을 엽니다."""
        self.window_manager.open_detail_schedule()

    def open_clock(self) -> None:
        """시계 창을 엽니다."""
        self.window_manager.open_clock()

    def open_repeat(self) -> None:
        """반복 작업(할 일) 창을 엽니다."""
        self.window_manager.open_repeat()

    def reopen_settings(self) -> None:
        """설정 창이 열려 있으면 다시 그려 갱신합니다."""
        self.window_manager.reopen_settings()

    def create_memo(self) -> None:
        """새 메모 창을 만들고 엽니다."""
        self.window_manager.create_memo()

    def open_memo(self, memo_id: str, geometry: str | None = None) -> None:
        """기존 메모 창을 엽니다."""
        self.window_manager.open_memo(memo_id, geometry)

    def restore_open_memos(self) -> None:
        """이전 세션에 열려 있던 메모 창들을 복원합니다."""
        self.window_manager.restore_open_memos()

    def memo_has_content(self, memo_id: str) -> bool:
        """메모 파일에 실제 내용이 있는지 확인합니다."""
        return self.memo_store.has_content(memo_id) or bool(self.store.get("memo_titles", {}).get(memo_id, "").strip())

    def remember_open_memo(self, memo_id: str, geometry: str) -> None:
        """열린 메모 창을 다음 실행 때 복원할 목록에 기록합니다."""
        self.window_manager.remember_open_memo(memo_id, geometry)

    def forget_open_memo(self, memo_id: str) -> None:
        """닫힌 메모 창을 복원 목록에서 제거합니다."""
        self.window_manager.forget_open_memo(memo_id)

    def persist_open_memos(self) -> None:
        """현재 열린 메모 창 목록을 저장합니다."""
        self.window_manager.persist_open_memos()

    def persist_open_windows(self) -> None:
        """열린 창들의 상태(위치/내용)를 저장합니다."""
        self.window_manager.persist_open_windows()

    def recall_hidden_memos(self) -> None:
        """숨겨졌던 메모 창들을 다시 불러옵니다."""
        self.window_manager.recall_hidden_memos()

    def set_calendar_opacity(self, value: int) -> None:
        """메인 캘린더 창의 투명도를 설정합니다."""
        value = max(20, min(100, int(value)))
        self.store.set("calendar_opacity", value)
        self.setWindowOpacity(value / 100)
        self.save()

    def set_startup(self, enabled: bool, show_message: bool = True) -> None:
        """Windows 시작 프로그램 등록 여부를 설정합니다."""
        if LEGACY_STARTUP_PATH.exists():
            LEGACY_STARTUP_PATH.unlink()
        if enabled:
            STARTUP_PATH.parent.mkdir(parents=True, exist_ok=True)
            if getattr(sys, "frozen", False):
                # PyInstaller로 빌드된 실행 파일(ChronoFox.exe)에서는 그 자체가
                # 완결된 프로그램이므로 별도 스크립트 인자 없이 exe만 실행한다.
                launcher = Path(sys.executable)
                STARTUP_PATH.write_text(
                    f'@echo off\nstart "" "{launcher}"\n',
                    encoding="utf-8",
                )
            else:
                pythonw = Path(sys.executable).with_name("pythonw.exe")
                launcher = pythonw if pythonw.exists() else Path(sys.executable)
                STARTUP_PATH.write_text(
                    f'@echo off\nstart "" "{launcher}" "{Path(__file__).resolve()}"\n',
                    encoding="utf-8",
                )
        elif STARTUP_PATH.exists():
            STARTUP_PATH.unlink()
        if show_message:
            QMessageBox.information(self, APP_NAME, self.tr("message.startup.changed", "자동 실행 설정을 변경했습니다."))

    def startup_enabled(self) -> bool:
        """Windows 시작 프로그램에 등록되어 있는지 반환합니다."""
        return STARTUP_PATH.exists() or LEGACY_STARTUP_PATH.exists()

    def create_backup(self, destination: Path) -> Path:
        """현재 설정/데이터/메모를 zip 백업으로 만듭니다."""
        self.persist_open_windows()
        return create_backup_archive(self.store, destination)

    def export_calendar_file(self, destination: Path) -> Path:
        """일정을 ICS 캘린더 파일로 내보냅니다."""
        self.persist_open_windows()
        return export_ics(self.data, destination)

    def apply_theme(self) -> FoxCalendarApp:
        """현재 테마 색상을 위젯 스타일에 다시 적용합니다."""
        new_colors = resolve_theme(self.store)
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
        """메모 창들에 현재 테마를 다시 적용합니다."""
        for window in list(self.memo_windows.values()):
            if window.isVisible():
                window.apply_note_theme()

    def apply_font_family(self, family: str) -> None:
        """선택한 폰트 패밀리를 앱 전역에 적용합니다."""
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
        """현재 언어 설정에 맞춰 화면 텍스트를 다시 그립니다."""
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
        """폰트가 바뀐 뒤 스타일시트를 다시 적용합니다."""
        if hasattr(self, "month_label"):
            self.month_label.setFont(app_font(14, QFont.Bold))
        if hasattr(self, "search_input"):
            self.search_input.setFont(app_font(9))
        for label in getattr(self, "weekday_labels", []):
            label.setFont(app_font(9, QFont.Bold))
        for cell in self.day_cells:
            cell.update()

    def refresh_theme_styles(self) -> None:
        """테마가 바뀐 뒤 스타일시트를 다시 적용합니다."""
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
    """앱을 초기화하고 이벤트 루프를 시작하는 진입 함수입니다."""
    setup_logging()
    logging.getLogger(__name__).info("ChronoFox starting")
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
