"""ChronoFox 데스크톱 앱의 진입점. 바탕화면 캘린더 메인 창 FoxCalendarApp을 정의하고
서비스(PlanService/TrayController/WindowManager/AppStore)를 조립해 실행한다."""

from __future__ import annotations

import calendar
import logging
import sys
import time
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

from chronofox.clock import ClockWindow
from chronofox.clock.alarms import ClockAlarmMixin
from chronofox.core import clock_domain
from chronofox.core.app_config import (
    RecoveryNotice,
    consume_recovery_notices,
    create_backup_archive,
    load_config,
    load_data,
    save_config,
    save_data,
)
from chronofox.core.app_constants import (
    APP_ICON_PATH,
    APP_NAME,
    DEFAULT_CALENDAR_GEOMETRY,
    DEFAULT_FONT_FAMILY,
    LEGACY_STARTUP_PATH,
    REPO_ROOT,
    STARTUP_PATH,
)
from chronofox.core.app_crash import install_crash_handler
from chronofox.core.app_domain import PlanService
from chronofox.core.app_hotkey import DEFAULT_QUICK_HOTKEY
from chronofox.core.app_integrations import export_ics
from chronofox.core.app_logging import setup_logging
from chronofox.core.app_models import MemoStore
from chronofox.core.app_scheduler import NotificationScheduler
from chronofox.core.app_store import AppStore
from chronofox.detail_schedule import DetailScheduleWindow
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_styles import (
    calendar_agenda_entries,
    calendar_bar_summary,
    calendar_cell_style,
    calendar_dot_summary,
    calendar_geometry_for_style,
    calendar_layout_preset,
    calendar_text_summary,
    calendar_week_dates,
    desktop_calendar_dates,
    desktop_calendar_week_numbers,
    desktop_cell_text_flow,
    normalized_calendar_style,
)
from chronofox.ui.app_theme import prettify_holiday_name, resolve_theme
from chronofox.ui.app_ui import (
    app_font,
    clear_layout,
    geometry_string,
    load_app_font,
    parse_geometry,
    set_active_font_family,
)
from chronofox.ui.app_widgets import IconButton, RoundedContentFrame, RoundedWindow
from chronofox.windows.global_hotkey import GlobalHotkeyController
from chronofox.windows.schedule_window import ScheduleWindow
from chronofox.windows.todo_window import RepeatWindow
from chronofox.windows.tray_controller import TrayController
from chronofox.windows.window_manager import WindowManager

if TYPE_CHECKING:
    from chronofox.windows.memo_window import StickyMemoWindow
    from chronofox.windows.quick_input_window import QuickInputWindow
    from chronofox.windows.search_window import SearchWindow
    from chronofox.windows.settings_window import SettingsWindow


class DayCell(QWidget):
    """달력의 날짜 한 칸을 직접 그리는 위젯입니다."""

    clicked = Signal(date)
    double_clicked = Signal(date)

    def __init__(self, colors: dict[str, str]) -> None:
        super().__init__()
        self.colors = colors
        # calendar_cell_style()이 계산한 구조 토큰만 소비하고 프리셋 이름으로 분기하지 않는다.
        self.style: dict = {}
        self.day = date.today()
        self.lines: list[str] = []
        self.line_overflow = 0
        self.plan_bars: list[dict] = []
        self.plan_bars_full: list[dict] = []
        self.holiday = ""
        self.state = "normal"
        self.hovered = False
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(86)

    def set_data(
        self,
        day: date,
        lines: list[str],
        state: str,
        holiday: str = "",
        plan_bars: list[dict] | None = None,
        line_overflow: int = 0,
    ) -> None:
        """달력 날짜 셀에 표시할 날짜/일정 요약/상태/공휴일/계획 막대 데이터를 채웁니다."""
        self.day = day
        self.lines = lines[:3]
        self.line_overflow = max(0, int(line_overflow))
        bars = plan_bars or []
        # R16 C3: 미니멀(dot) 모드의 "+N" 넘침 표시는 잘라내기 전 전체 목록 기준이어야
        # 하므로 원본을 별도로 보관한다. bar 모드는 기존과 동일하게 [:3]으로 표시한다.
        self.plan_bars_full = bars
        self.plan_bars = bars[:3]
        self.holiday = holiday
        self.state = state
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.day)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self.day)
        super().mouseDoubleClickEvent(event)

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
        style = self.style
        # build_ui가 style dict를 연결하기 전에도 안전하게 그릴 방어 기본값이다.
        today_style = style.get("today_style", "outline")
        tile = style.get("cell_tile", False)
        tile_radius = style.get("tile_radius", 10)
        tile_margin = style.get("tile_margin", 3)

        bg = style.get("normal_bg", colors["cell"])
        fg = colors["text"]
        if self.state == "other":
            bg, fg = colors["other"], colors["other_text"]
        elif self.state == "today":
            if today_style == "tile":
                bg, fg = colors["accent"], "#ffffff"
            elif today_style == "circle":
                fg = colors["today_text"]
            else:
                bg, fg = colors["today_bg"], colors["today_text"]
        elif self.state == "selected":
            bg, fg = colors["selected_bg"], colors["selected_text"]
        elif self.state == "holiday":
            bg, fg = bg, colors["holiday"]

        painter = QPainter(self)
        rect = self.rect()
        if tile:
            paint_rect = rect.adjusted(tile_margin, tile_margin, -tile_margin, -tile_margin)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(bg))
            painter.drawRoundedRect(paint_rect, tile_radius, tile_radius)
        else:
            paint_rect = rect
            # R16b B3: cell_fill=False(시트 프리셋)면 normal 계열 상태의 배경을 칠하지
            # 않는다 — 창 배경(과 투명도 슬라이더)이 그대로 비쳐 "벽지 위 시트" 룩이 된다.
            # today/selected는 가독을 위해 계속 칠한다. 기본값(True)은 기존 렌더와 동일.
            if style.get("cell_fill", True) or self.state in {"today", "selected"}:
                painter.fillRect(rect, QColor(bg))

        if self.hovered and self.state not in {"selected", "today"}:
            hover = QColor(colors.get("button_hover", colors["panel2"]))
            hover.setAlpha(68)
            if tile:
                painter.setPen(Qt.NoPen)
                painter.setBrush(hover)
                painter.drawRoundedRect(paint_rect, tile_radius, tile_radius)
            else:
                painter.fillRect(rect, hover)

        if style.get("draw_grid", True):
            grid_color = QColor(colors["grid"])
            grid_color.setAlpha(int(style.get("grid_alpha", 255)))
            painter.setPen(QPen(grid_color, 0.55))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect.adjusted(0, 0, -1, -1))

        painter.setBrush(Qt.NoBrush)
        if self.state == "selected":
            painter.setPen(QPen(QColor(colors["selected_border"]), 2.0))
            if tile:
                painter.drawRoundedRect(paint_rect.adjusted(1, 1, -1, -1), tile_radius, tile_radius)
            else:
                painter.drawRect(rect.adjusted(1, 1, -2, -2))
        elif self.state == "today" and today_style == "outline":
            painter.setPen(QPen(QColor(colors["today_border"]), 2.0))
            painter.drawRect(rect.adjusted(1, 1, -2, -2))

        date_color = fg
        if self.state != "other":
            if self.day.weekday() == 5:
                date_color = colors["saturday"]
            elif self.day.weekday() == 6:
                date_color = colors["sunday"]
            if self.state == "holiday":
                date_color = colors["holiday"]
        if self.state == "today" and today_style in {"tile", "circle"}:
            date_color = "#ffffff"

        num_font = app_font(9, QFont.Bold)
        painter.setFont(num_font)
        if self.state == "today" and today_style == "circle":
            metrics_num = painter.fontMetrics()
            digits = str(self.day.day)
            text_width = metrics_num.horizontalAdvance(digits)
            diameter = max(text_width + 10, 18)
            cx = 10 + text_width / 2
            cy = 20 - metrics_num.ascent() / 2
            circle_rect = QRectF(cx - diameter / 2, cy - diameter / 2, diameter, diameter)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(colors["accent"]))
            painter.drawEllipse(circle_rect)
            painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor(date_color))
        if style.get("date_alignment") == "right":
            painter.drawText(QRect(8, 4, max(10, self.width() - 16), 18), Qt.AlignRight | Qt.AlignVCenter, str(self.day.day))
        else:
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

        chip_mode = style.get("chip_mode", "bar")
        base_y = 34
        if chip_mode == "dot":
            painter.setFont(app_font(9))
            metrics = painter.fontMetrics()
            y = self._paint_plan_dots(painter, colors, style, base_y)
            # _paint_plan_dots는 "+N" 배지를 위해 폰트를 7pt로 바꿔둘 수 있으므로,
            # 아래 일정 텍스트가 그 폰트를 물려받지 않도록 되돌린다.
            painter.setFont(app_font(9))
        elif chip_mode == "bar":
            painter.setFont(app_font(9))
            metrics = painter.fontMetrics()
            # AUDIT-D2: capacity는 셀 높이가 실제로 그릴 수 있는 줄 수다(고정 [:3] 대신 —
            # 예전에는 lane 값이 큰 막대가 셀 밖으로 넘치면 아무 표시 없이 사라졌다).
            # calendar_bar_summary가 lane이 낮은 막대부터 capacity개를 고르고, 선택된
            # 막대는 원래 lane이 아니라 순번(rank)으로 그려 항상 셀에 맞도록 한다.
            shown_bars, remaining = self.bar_mode_summary(base_y)
            for rank, plan in enumerate(shown_bars):
                y = base_y + rank * 18
                color = QColor(plan.get("color", colors["accent"]))
                color.setAlpha(180)
                # 주 경계(일요일 시작/토요일 끝)에서는 셀 밖으로 삐져나가지 않게 가장자리에서 멈춘다.
                week_start = self.day.weekday() == 6
                week_end = self.day.weekday() == 5
                x = (2 if week_start else -2) if plan.get("from_prev") else 10
                right_margin = (2 if week_end else -2) if plan.get("to_next") else 10
                rect_bar = QRect(x, y, max(8, self.width() - x - right_margin), 15)
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect_bar, 2, 2)
                painter.setPen(QColor("#ffffff"))
                painter.setFont(app_font(8, QFont.Bold))
                text_rect = rect_bar.adjusted(4, -1, -3, 0)
                title = plan.get("title", "") if plan.get("show_title") else ""
                painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, metrics.elidedText(title, Qt.ElideRight, text_rect.width()))

            if remaining > 0:
                # 미니멀(dot) 모드의 "+N" 배지와 같은 스타일(7pt bold, muted 색)로 통일한다.
                painter.setPen(QColor(colors["muted"]))
                painter.setFont(app_font(7, QFont.Bold))
                badge_y = base_y + len(shown_bars) * 18
                badge_rect = QRect(self.width() - 28, badge_y, 24, 14)
                painter.drawText(badge_rect, Qt.AlignRight | Qt.AlignVCenter, f"+{remaining}")

            # "+N" 배지가 7pt bold 폰트를 남겨둘 수 있으므로, 아래 일정 텍스트가 그 폰트를
            # 물려받지 않도록 되돌린다(R16 dot 모드에서 발견된 것과 같은 버그 클래스).
            painter.setFont(app_font(9))
            metrics = painter.fontMetrics()
            y = max(base_y + len(shown_bars) * 18 + 8, 48)
        else:
            painter.setFont(app_font(8))
            metrics = painter.fontMetrics()
            long_bars = self.plan_bars_full[:1]
            bar_height = 10
            plan = long_bars[0] if long_bars else None
            # CAL1: 막대 제목과 평문 줄이 같은 베이스라인 규약을 쓰도록 수직 흐름을
            # desktop_cell_text_flow()가 한 곳에서 계산한다(예전에는 rect 상단 기준과
            # 베이스라인 기준이 섞여 서로 겹쳤다).
            title_baseline, y = desktop_cell_text_flow(
                base_y,
                bar_height=bar_height,
                ascent=metrics.ascent(),
                line_height=metrics.height(),
                has_bar=plan is not None,
                has_title=bool(plan and plan.get("show_title")),
            )
            if plan is not None:
                color = QColor(plan.get("color", colors["accent"]))
                color.setAlpha(180)
                x = -2 if plan.get("from_prev") else 10
                right_margin = -2 if plan.get("to_next") else 10
                rect_bar = QRect(x, base_y, max(8, self.width() - x - right_margin), bar_height)
                painter.setPen(Qt.NoPen)
                painter.setBrush(color)
                painter.drawRoundedRect(rect_bar, 2, 2)
                if plan.get("show_title"):
                    painter.setPen(QColor(colors["text"]))
                    title_width = max(8, self.width() - 20)
                    painter.drawText(
                        10,
                        title_baseline,
                        metrics.elidedText(str(plan.get("title", "")), Qt.ElideRight, title_width),
                    )

        available = max(10, self.width() - 20)
        painter.setPen(QColor(colors["text"]))
        for line in self.lines:
            if y + metrics.height() > self.height() - 4:
                break
            painter.drawText(10, y, metrics.elidedText(line, Qt.ElideRight, available))
            y += 16
        if self.line_overflow > 0:
            painter.setPen(QColor(colors["muted"]))
            painter.setFont(app_font(7, QFont.Bold))
            painter.drawText(
                QRect(self.width() - 34, self.height() - 18, 28, 14),
                Qt.AlignRight | Qt.AlignVCenter,
                f"+{self.line_overflow}",
            )

    def bar_mode_summary(self, base_y: int = 34) -> tuple[list[dict], int]:
        """bar 모드(card 스타일)에서 실제로 그릴 막대와 넘침 개수를 계산합니다.

        paintEvent와 셀 재검수(회귀 테스트)가 같은 capacity 계산을 공유하도록 별도
        메서드로 뽑아뒀다 — 셀 높이(self.height())가 실제로 그릴 수 있는 줄 수를
        결정하고, calendar_bar_summary()가 lane이 낮은 막대부터 그만큼만 고른다.
        """
        max_rows = max(0, (self.height() - 33 - base_y) // 18 + 1)
        return calendar_bar_summary(self.plan_bars_full, max_rows)

    def _paint_plan_dots(self, painter: QPainter, colors: dict[str, str], style: dict, base_y: int) -> int:
        """R16 C3: 미니멀 달력 모양의 dot chip 행을 그리고, 그 아래 일정 텍스트가 시작할
        y좌표를 반환합니다. 넘침 개수는 잘라내기 전 전체 목록(plan_bars_full) 기준이다."""
        bars = self.plan_bars_full
        if not bars:
            return 48
        max_dots = style.get("max_dots", 4)
        shown, remaining = calendar_dot_summary(bars, max_dots)
        radius = 4.0
        gap = 4.0
        dot_y = float(base_y)
        x = 12.0
        right_edge = self.width() - 10
        painter.setPen(Qt.NoPen)
        drawn = 0
        for plan in shown:
            if x + radius * 2 > right_edge:
                break
            color = QColor(plan.get("color", colors["accent"]))
            painter.setBrush(color)
            painter.drawEllipse(QRectF(x, dot_y, radius * 2, radius * 2))
            x += radius * 2 + gap
            drawn += 1
        if remaining > 0:
            painter.setPen(QColor(colors["muted"]))
            painter.setFont(app_font(7, QFont.Bold))
            label_rect = QRect(int(x), int(dot_y) - 2, max(16, self.width() - int(x) - 6), int(radius * 2) + 6)
            painter.drawText(label_rect, Qt.AlignVCenter | Qt.AlignLeft, f"+{remaining}")
        painter.setBrush(Qt.NoBrush)
        return int(dot_y + radius * 2 + 10) if (drawn or remaining) else 48

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
        elif notice.kind == "task_migration_failed":
            # todo-v3 T2: 마이그레이션 실패는 사용자에게 반드시 알려야 한다 — 안내가 없으면
            # "할 일이 전부 사라졌다"로 오해한다. 데이터는 그대로이고 할 일만 잠긴 상태다.
            template = tr(
                "recovery.task_migration_failed",
                "해야 할 일 데이터를 새 형식으로 옮기지 못했습니다. 기존 데이터는 그대로 있고 "
                "백업도 만들어 두었습니다. 이번 실행에서는 할 일을 수정할 수 없으며, 다음 실행에서 "
                "다시 시도합니다.",
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
        # P-D1: drag_locked() 훅이 참조하는 핀 모드 상태 플래그. set_pin_mode가 갱신한다.
        self._pin_mode = False
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
        self.quick_input_window: QuickInputWindow | None = None
        self.calendar_quick_popover = None
        self.holiday_cache: dict[int, dict[date, str]] = {}
        self.force_quit = False
        # RESTORE1: 백업 복원 성공 직후 True로 설정된다. 디스크에는 이미 복원본이 쓰여
        # 있으므로, 종료/창 이동 시점의 메모리 상태 기반 flush(persist_open_windows 등)가
        # 그 위에 덮어써 복원을 무효화하지 않도록 막는 가드다.
        self.skip_exit_flush = False

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

        initial_style = normalized_calendar_style(self.store)
        initial_geometry = calendar_geometry_for_style(self.store, initial_style, DEFAULT_CALENDAR_GEOMETRY)
        width, height, x, y = parse_geometry(initial_geometry, (980, 620, 180, 40))
        self.setGeometry(x, y, width, height)
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

        # P-D3: 핀 모드는 창을 재생성(setWindowFlag)하므로, main()의 window.show()보다
        # 먼저 여기서 적용해 둔다 — set_pin_mode 내부의 show()가 이미 핀 적용된 상태로
        # 창을 보여주므로 일반 창 -> 핀 전환의 깜빡임이 없다.
        if self.store.get("pin_mode", False):
            self.set_pin_mode(True)

        # Q3/U1: 트레이(풍선 고지 대상)가 이미 준비된 뒤에 등록을 시도한다.
        self.global_hotkey.attach()

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

    @property
    def global_hotkey(self) -> GlobalHotkeyController:
        """지연 초기화된 GlobalHotkeyController 인스턴스를 반환합니다(Q3/U1)."""
        controller = self.__dict__.get("_global_hotkey")
        if controller is None:
            controller = GlobalHotkeyController(self)
            self.__dict__["_global_hotkey"] = controller
        return controller

    def save(self) -> None:
        # S4(M6): geometry는 silent set — 창을 옮길 때마다 구독자가 깨면 안 된다.
        """현재 config/data를 디스크에 저장합니다."""
        current_geometry = geometry_string(self)
        style = normalized_calendar_style(self.store)
        geometries = self.store.get("calendar_geometries", {})
        geometries = dict(geometries) if isinstance(geometries, dict) else {}
        geometries[style] = current_geometry
        self.store.set("calendar_geometries", geometries, notify_topic=None)
        self.store.set("calendar_geometry", current_geometry, notify_topic=None)
        self.store.save()

    # PIN-MODE-v2 (P-D1/P-D3) --------------------------------------------
    def drag_locked(self) -> bool:
        """RoundedWindow 훅 override(P-D1) — 핀 모드 중에는 메인 창의 드래그 이동/
        리사이즈를 막는다. 다른 창(RoundedWindow 서브클래스)은 이 훅을 override하지
        않으므로 기본 False로 기존 동작을 유지한다."""
        return self._pin_mode

    def set_pin_mode(self, enabled: bool) -> None:
        """핀 모드 토글(P-D1/P-D3): ① drag_locked()가 반환할 상태 갱신 ②
        WindowStaysOnBottomHint 플래그 적용(+show — 플래그 변경은 Qt가 네이티브 창을
        재생성하므로 재호출 필요) ③ store에 저장. setWindowFlag는 재생성 중 지오메트리를
        유실할 수 있어(S5) 호출 전 값을 기억했다가 재적용한다. 잠금 중에는 리사이즈
        핸들도 숨긴다(드래그 가드와 시각적으로 일관되게)."""
        self._pin_mode = enabled
        geometry = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnBottomHint, enabled)
        self.setGeometry(geometry)
        if hasattr(self, "resize_handle"):
            self.resize_handle.setVisible(not enabled)
        self.show()
        self.store.set("pin_mode", enabled)
        self.save()

    # Quick Input(0.9) Q3 — 전역 단축키 설정 API (U1) ----------------------
    def set_quick_hotkey_enabled(self, enabled: bool) -> None:
        """전역 단축키 활성/비활성 스위치 콜백 — store 저장 후 재등록한다."""
        self.store.set("quick_hotkey_enabled", enabled)
        self.save()
        self.global_hotkey.reregister()

    def reset_quick_hotkey(self) -> None:
        """조합을 기본값(Ctrl+Alt+Space)으로 되돌리고 재등록한다."""
        self.store.set("quick_hotkey", DEFAULT_QUICK_HOTKEY)
        self.save()
        self.global_hotkey.reregister()

    def app_display_name(self) -> str:
        """현재 언어에 맞는 앱 표시 이름을 반환합니다."""
        return self.tr("app.name", APP_NAME)

    def dialog_colors(self) -> dict[str, str]:
        """다이얼로그에서 사용할 현재 테마 색상 dict를 반환합니다."""
        return resolve_theme(self.store)

    def build_ui(self) -> None:
        """선택된 전체 디자인 프리셋으로 메인 달력을 다시 구성합니다."""
        c = self.colors
        preset = calendar_layout_preset(self.store, c)
        self.layout_preset = preset
        self.setMinimumSize(*preset["minimum_size"])
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.day_cells = []
        root_names = {
            "desktop": "calendarDesktopRoot",
            "minimal": "calendarWeekFocusRoot",
            "card": "calendarAgendaRoot",
        }
        root = RoundedContentFrame(self.radius)
        root.setObjectName(root_names[preset["key"]])
        root.setAttribute(Qt.WA_StyledBackground, True)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        self.calendar_root = root

        body = QFrame()
        body.setObjectName("calendarBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        calendar_column = QFrame()
        calendar_column.setObjectName("calendarColumn")
        column_layout = QVBoxLayout(calendar_column)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.setSpacing(0)

        header = QGridLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(preset["header_spacing"])
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
        if preset["search_width"]:
            self.search_input.setFixedWidth(preset["search_width"])
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
        if preset["header_mode"] == "desktop":
            self.month_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.addWidget(self.month_label, 0, 0)
            header.addWidget(self.search_input, 0, 1, Qt.AlignRight | Qt.AlignVCenter)
            header.addLayout(right, 0, 2)
        elif preset["header_mode"] == "agenda":
            self.month_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.addWidget(self.month_label, 0, 0)
            header.addLayout(right, 0, 2)
        else:
            header.addWidget(self.search_input, 0, 0, Qt.AlignLeft | Qt.AlignVCenter)
            header.addWidget(self.month_label, 0, 1)
            header.addLayout(right, 0, 2)
        header_frame = QFrame()
        header_frame.setObjectName("calendarHeader")
        header_frame.setStyleSheet(self.calendar_header_style())
        header_frame.setFixedHeight(preset["header_height"])
        header_frame_layout = QVBoxLayout(header_frame)
        header_frame_layout.setContentsMargins(*preset["header_margin"])
        header_frame_layout.addLayout(header)
        self.header_frame = header_frame
        column_layout.addWidget(header_frame)

        self.grid = QGridLayout()
        self.grid.setSpacing(preset["grid_spacing"])
        grid_margin = preset["grid_margin"]
        self.grid.setContentsMargins(grid_margin, grid_margin, grid_margin, grid_margin)
        self.grid_frame = QFrame()
        self.grid_frame.setObjectName("calendarGridFrame")
        self.grid_frame.setStyleSheet(self.calendar_grid_style())
        grid_frame_layout = QVBoxLayout(self.grid_frame)
        grid_frame_layout.setContentsMargins(0, 0, 0, 0)
        grid_frame_layout.setSpacing(0)
        self.weekday_labels = []
        weekday_items = [
            (6, self.tr("calendar.weekday.sun", "일")),
            (0, self.tr("calendar.weekday.mon", "월")),
            (1, self.tr("calendar.weekday.tue", "화")),
            (2, self.tr("calendar.weekday.wed", "수")),
            (3, self.tr("calendar.weekday.thu", "목")),
            (4, self.tr("calendar.weekday.fri", "금")),
            (5, self.tr("calendar.weekday.sat", "토")),
        ]
        if preset["first_weekday"] == 0:
            weekday_items = weekday_items[1:] + weekday_items[:1]
        column_offset = 1 if preset["show_week_numbers"] else 0
        self.week_number_labels: list[QLabel] = []
        if preset["show_week_numbers"]:
            week_heading = QLabel(self.tr("calendar.week_number.short", "주"))
            week_heading.setObjectName("calendarWeekNumberHeading")
            week_heading.setAlignment(Qt.AlignCenter)
            week_heading.setFixedWidth(34)
            week_heading.setFixedHeight(preset["weekday_height"])
            self.grid.addWidget(week_heading, 0, 0)
        for col, (weekday_index, text) in enumerate(weekday_items):
            label = QLabel(text)
            label.setProperty("weekday_index", weekday_index)
            label.setAlignment(Qt.AlignCenter)
            label.setFont(app_font(9, QFont.Bold))
            label.setFixedHeight(preset["weekday_height"])
            label.setStyleSheet(self.weekday_label_style(weekday_index))
            self.weekday_labels.append(label)
            self.grid.addWidget(label, 0, col + column_offset)

        # R16: 모든 DayCell이 같은 dict 객체를 참조하게 해서(self.colors와 동일한 관례)
        # refresh_theme_styles()가 in-place로 갱신하면 재생성 없이 새 스타일이 반영된다.
        self.cell_style = calendar_cell_style(self.store, c)
        self.cell_style["date_alignment"] = preset["date_alignment"]
        for row in range(preset["week_count"]):
            if preset["show_week_numbers"]:
                week_number = QLabel()
                week_number.setObjectName("calendarWeekNumber")
                week_number.setAlignment(Qt.AlignCenter)
                week_number.setFixedWidth(34)
                self.week_number_labels.append(week_number)
                self.grid.addWidget(week_number, row + 1, 0)
            for col in range(7):
                cell = DayCell(c)
                cell.setMinimumHeight(preset["cell_minimum_height"])
                cell.style = self.cell_style
                cell.clicked.connect(self.on_day_cell_clicked)
                cell.double_clicked.connect(self.on_day_cell_double_clicked)
                self.day_cells.append(cell)
                self.grid.addWidget(cell, row + 1, col + column_offset)
        grid_frame_layout.addLayout(self.grid, 1)
        column_layout.addWidget(self.grid_frame, 1)

        footer_frame = QFrame()
        footer_frame.setObjectName("calendarFooter")
        footer_frame.setFixedHeight(preset["footer_height"])
        footer_frame.setVisible(preset["footer_height"] > 0)
        footer_frame.setStyleSheet(self.calendar_footer_style())
        self.footer_frame = footer_frame
        column_layout.addWidget(footer_frame)

        self.week_strip = None
        self.week_day_labels: list[QLabel] = []
        self.week_event_labels: list[QLabel] = []
        if preset["show_week_strip"]:
            week_strip = self.build_week_strip()
            self.week_strip = week_strip
            column_layout.addWidget(week_strip)

        body_layout.addWidget(calendar_column, 1)
        self.agenda_panel = None
        self.agenda_items_layout = None
        if preset["show_agenda"]:
            agenda_panel = self.build_agenda_panel()
            self.agenda_panel = agenda_panel
            body_layout.addWidget(agenda_panel)

        root_layout.addWidget(body, 1)
        layout.addWidget(root, 1)
        self.refresh_theme_styles()

    def build_week_strip(self) -> QFrame:
        """선택 날짜가 속한 한 주의 상세 요약 스트립을 만든다."""
        strip = QFrame()
        strip.setObjectName("calendarWeekStrip")
        strip.setFixedHeight(self.layout_preset["auxiliary_size"])
        strip_layout = QHBoxLayout(strip)
        strip_layout.setContentsMargins(10, 8, 10, 8)
        strip_layout.setSpacing(0)
        title = QLabel(self.tr("calendar.week_focus.title", "선택한 주"))
        title.setObjectName("calendarWeekTitle")
        title.setFixedWidth(78)
        title.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        strip_layout.addWidget(title)
        for _ in range(7):
            day_frame = QFrame()
            day_frame.setObjectName("calendarWeekDay")
            day_layout = QVBoxLayout(day_frame)
            day_layout.setContentsMargins(7, 3, 7, 3)
            day_layout.setSpacing(4)
            day_label = QLabel()
            day_label.setObjectName("calendarWeekDayLabel")
            event_label = QLabel()
            event_label.setObjectName("calendarWeekEventLabel")
            event_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            event_label.setWordWrap(True)
            day_layout.addWidget(day_label)
            day_layout.addWidget(event_label, 1)
            strip_layout.addWidget(day_frame, 1)
            self.week_day_labels.append(day_label)
            self.week_event_labels.append(event_label)
        return strip

    def build_agenda_panel(self) -> QFrame:
        """선택 날짜의 일정과 메모를 고정 표시하는 오른쪽 아젠다를 만든다."""
        panel = QFrame()
        panel.setObjectName("calendarAgendaPanel")
        panel.setFixedWidth(self.layout_preset["auxiliary_size"])
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(14, 14, 14, 12)
        panel_layout.setSpacing(7)
        self.agenda_title = QLabel()
        self.agenda_title.setObjectName("calendarAgendaTitle")
        self.agenda_count = QLabel()
        self.agenda_count.setObjectName("calendarAgendaCount")
        panel_layout.addWidget(self.agenda_title)
        panel_layout.addWidget(self.agenda_count)
        items = QFrame()
        items.setObjectName("calendarAgendaItems")
        self.agenda_items_layout = QVBoxLayout(items)
        self.agenda_items_layout.setContentsMargins(0, 4, 0, 4)
        self.agenda_items_layout.setSpacing(0)
        panel_layout.addWidget(items, 1)
        self.search_input.setMaximumWidth(16777215)
        self.search_input.setMinimumWidth(0)
        panel_layout.addWidget(self.search_input)
        return panel

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
        mode = getattr(self, "layout_preset", {}).get("header_mode", "classic")
        if mode == "desktop":
            return (
                f"QFrame#calendarHeader {{ background: {c['weekday']}; "
                f"border: 1px solid {c['grid']}; border-radius: 0px; }}"
            )
        if mode == "agenda":
            return (
                f"QFrame#calendarHeader {{ background: {c['panel']}; "
                f"border: 1px solid {c['border']}; border-bottom: none; border-radius: 0px; }}"
            )
        return (
            f"QFrame#calendarHeader {{ background: {c.get('header', c['panel'])}; "
            f"border: 1px solid {c['border']}; border-bottom: none; "
            f"border-top-left-radius: {self.radius}px; border-top-right-radius: {self.radius}px; }}"
        )

    def calendar_grid_style(self) -> str:
        """캘린더 날짜 그리드 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        if getattr(self, "layout_preset", {}).get("key") == "desktop":
            return (
                f"QFrame#calendarGridFrame {{ background: {c['cell']}; "
                f"border: 1px solid {c['grid']}; border-top: none; border-radius: 0px; }}"
            )
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

    def weekday_label_style(self, weekday_index: int) -> str:
        """요일 열과 프리셋에 맞는 절제된 요일 라벨 스타일을 반환한다."""
        c = self.colors
        weekday_color = c["text"]
        if weekday_index == 5:
            weekday_color = c["saturday"]
        elif weekday_index == 6:
            weekday_color = c["sunday"]
        background = c["weekday"]
        return (
            f"background: {background}; color: {weekday_color};"
            f"border: 0.5px solid {c['grid']};"
        )

    def calendar_auxiliary_style(self) -> str:
        """주간 스트립과 아젠다 패널 공용 QSS를 반환한다."""
        c = self.colors
        return (
            f"QFrame#calendarWeekStrip {{ background: {c['panel']}; border: 1px solid {c['border']}; border-top: none; }}"
            f"QFrame#calendarWeekDay {{ background: transparent; border-left: 1px solid {c['grid']}; }}"
            f"QFrame#calendarWeekDay[selected=\"true\"] {{ background: {c['selected_bg']}; }}"
            f"QLabel#calendarWeekNumberHeading, QLabel#calendarWeekNumber {{ background: {c['weekday']}; "
            f"color: {c['muted']}; border: 0.5px solid {c['grid']}; font-size: 8pt; }}"
            f"QLabel#calendarWeekTitle, QLabel#calendarWeekDayLabel, QLabel#calendarAgendaTitle {{ color: {c['text']}; font-weight: 700; }}"
            f"QLabel#calendarWeekEventLabel, QLabel#calendarAgendaCount {{ color: {c['muted']}; }}"
            f"QFrame#calendarAgendaPanel {{ background: {c['weekday']}; border-left: 1px solid {c['border']}; }}"
            f"QLabel#calendarAgendaItem {{ color: {c['text']}; border-top: 1px solid {c['grid']}; padding: 7px 2px; }}"
            f"QLabel#calendarAgendaEmpty {{ color: {c['muted']}; padding: 10px 2px; }}"
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
        style = self.layout_preset["key"]
        if style == "desktop":
            days = desktop_calendar_dates(self.selected_day)
            center_month = self.selected_day.replace(day=1)
            self.visible_month = center_month
            range_text = f"{days[0]:%m/%d}–{days[-1]:%m/%d}"
            self.month_label.setText(f"{self.month_title_text(center_month)}  ·  {range_text}")
            for label, week_number in zip(
                self.week_number_labels,
                desktop_calendar_week_numbers(days),
                strict=False,
            ):
                label.setText(str(week_number))
        else:
            self.month_label.setText(self.month_title_text(self.visible_month))
            weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
                self.visible_month.year,
                self.visible_month.month,
            )
            days = [day for week in weeks for day in week]
        plan_bars_by_day = self.plan_bars_for_days(days)
        for index, cell in enumerate(self.day_cells):
            if index >= len(days):
                cell.hide()
                continue
            cell.show()
            day = days[index]
            lines: list[str] = []
            line_overflow = 0
            holiday = self.get_holiday(day)
            plan_bars = plan_bars_by_day.get(day, [])
            schedule = self.get_schedule(day).strip()
            if style == "desktop":
                lines, line_overflow = calendar_text_summary(
                    self.plans_for_day(day),
                    schedule,
                    3,
                )
                plan_bars = [
                    {
                        **bar,
                        "show_title": not bar.get("from_prev") or day.weekday() == 0,
                    }
                    for bar in plan_bars
                    if bar.get("kind") == "long"
                ]
            elif schedule:
                lines.extend(line.strip() for line in schedule.splitlines() if line.strip())
            state = "normal"
            if day.month != self.visible_month.month:
                state = "other"
            if day == date.today():
                state = "today"
            elif day == self.selected_day:
                state = "selected"
            elif holiday:
                state = "holiday"
            cell.set_data(day, lines, state, holiday, plan_bars, line_overflow)
        self.refresh_calendar_auxiliary()

    def on_day_cell_clicked(self, day: date) -> None:
        """날짜를 선택만 하고 별도 일정 창은 열지 않는다."""
        self.selected_day = day
        self.render_calendar()

    def on_day_cell_double_clicked(self, day: date) -> None:
        """더블클릭 날짜의 빠른 입력 팝오버를 연다."""
        self.selected_day = day
        self.render_calendar()
        self.open_calendar_quick_popover(day)

    def open_calendar_quick_popover(self, day: date, text: str | None = "") -> None:
        """날짜 셀에 붙는 비모달 빠른 입력 팝오버를 열거나 재배치한다."""
        from chronofox.windows.calendar_quick_popover import CalendarQuickPopover

        anchor = next((cell for cell in self.day_cells if cell.day == day), None)
        if anchor is None:
            return
        if self.calendar_quick_popover is None:
            self.calendar_quick_popover = CalendarQuickPopover(self, self)
        self.calendar_quick_popover.apply_theme()
        self.calendar_quick_popover.open_for(day, anchor, text)

    def refresh_calendar_auxiliary(self) -> None:
        """현재 선택 날짜로 주간 스트립 또는 아젠다 패널 내용을 다시 만든다."""
        if self.week_strip is not None:
            weekday_keys = ("sun", "mon", "tue", "wed", "thu", "fri", "sat")
            for index, day in enumerate(calendar_week_dates(self.selected_day)):
                weekday = self.tr(f"calendar.weekday.{weekday_keys[index]}", weekday_keys[index])
                self.week_day_labels[index].setText(f"{weekday} {day.day}")
                entries = calendar_agenda_entries(self.plans_for_day(day), self.get_schedule(day))
                self.week_event_labels[index].setText("\n".join(
                    f"{time_text} {title}".strip()
                    for time_text, title in entries[:2]
                ))
                self.week_day_labels[index].parentWidget().setProperty("selected", day == self.selected_day)
                self.week_day_labels[index].parentWidget().style().unpolish(self.week_day_labels[index].parentWidget())
                self.week_day_labels[index].parentWidget().style().polish(self.week_day_labels[index].parentWidget())

        if self.agenda_panel is not None and self.agenda_items_layout is not None:
            day = self.selected_day
            title = self.tr("calendar.agenda.date", "{month}월 {day}일").format(month=day.month, day=day.day)
            entries = calendar_agenda_entries(self.plans_for_day(day), self.get_schedule(day))
            self.agenda_title.setText(title)
            self.agenda_count.setText(
                self.tr("calendar.agenda.count", "일정 {count}개").format(count=len(entries))
            )
            clear_layout(self.agenda_items_layout)
            if not entries:
                empty = QLabel(self.tr("calendar.agenda.empty", "등록된 일정이 없습니다."))
                empty.setObjectName("calendarAgendaEmpty")
                self.agenda_items_layout.addWidget(empty)
            else:
                for time_text, item_title in entries:
                    line = QLabel(f"{time_text}\n{item_title}" if time_text else item_title)
                    line.setObjectName("calendarAgendaItem")
                    line.setWordWrap(True)
                    self.agenda_items_layout.addWidget(line)
            self.agenda_items_layout.addStretch()

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

    def _timer_state(self) -> clock_domain.TimerState:
        """앱 전역 타이머 속성들을 TimerState로 모읍니다(clock/timer.py ClockTimerMixin과 동일 패턴)."""
        return clock_domain.TimerState(
            running=self.timer_running,
            start_time=self.timer_start_time,
            total_duration_ms=self.timer_total_duration,
            remaining_before_pause_ms=self.timer_remaining_before_pause_ms,
            remaining_ms=self.timer_remaining_ms,
        )

    def _apply_timer_state(self, state: clock_domain.TimerState) -> None:
        """TimerState를 앱 전역 타이머 속성에 반영합니다."""
        self.timer_running = state.running
        self.timer_start_time = state.start_time
        self.timer_total_duration = state.total_duration_ms
        self.timer_remaining_before_pause_ms = state.remaining_before_pause_ms
        self.timer_remaining_ms = state.remaining_ms

    def check_background_timer(self) -> None:
        """백그라운드 상태에서도 알람/리마인더를 확인하도록 주기적으로 호출됩니다."""
        if not (self.timer_running and self.timer_start_time is not None):
            return
        self.timer_remaining_ms = clock_domain.current_timer_remaining_ms(self._timer_state(), time.monotonic())
        if self.timer_remaining_ms == 0:
            self.timer_running = False
            self.timer_start_time = None
            self.timer_remaining_before_pause_ms = 0
            self.show_alert(self.tr("timer.finished", "타이머가 끝났습니다."))

    def start_timer_ms(self, duration_ms: int) -> None:
        """지정한 밀리초 길이로 타이머를 시작합니다(위젯 없는 경로 — Quick Input 전용).

        `ClockTimerMixin.start_timer()`는 스핀박스 위젯에서 길이를 읽지만, 이 얇은 위임
        메서드는 이미 계산된 `duration_ms`를 그대로 받는다. `clock_domain.start_timer()`가
        이미 실행 중이면 상태를 그대로 돌려주므로 중복 시작은 안전하게 무시된다. 시계 창이
        열려 있으면 그 타이머 라벨도 함께 갱신한다(같은 앱 전역 상태를 보여주므로)."""
        self._apply_timer_state(clock_domain.start_timer(self._timer_state(), duration_ms, time.monotonic()))
        if self.clock_window is not None:
            self.clock_window.timer_label.setText(self.clock_window.format_milliseconds(self.timer_remaining_ms))

    def add_alarm(self, payload: dict) -> dict | None:
        """알람을 추가합니다(위젯 없는 경로 — Quick Input 전용).

        알람 편집기 UI 경로(`ClockAlarmMixin.save_alarm_payload`, `alarm_id` 갱신·목록 위젯
        갱신 포함)와 달리 신규 추가만 지원한다. 시계 창이 열려 있으면 알람 목록도 새로고침한다."""
        alarm = clock_domain.save_alarm_payload(self.store.alarms(), payload, now=self.current_clock_datetime())
        self.save()
        self.store.notify("alarms")
        if self.clock_window is not None:
            self.clock_window.refresh_alarms()
        return alarm

    def current_stopwatch_elapsed(self) -> float:
        """현재 스톱워치 경과 시간을 반환합니다."""
        state = clock_domain.StopwatchState(
            running=self.stopwatch_running,
            start_time=self.stopwatch_start_time,
            elapsed_before_pause=self.stopwatch_elapsed_before_pause,
        )
        return clock_domain.current_stopwatch_elapsed(state, time.monotonic())

    def current_timer_remaining_ms(self) -> int:
        """현재 타이머 남은 시간(ms)을 반환합니다."""
        return clock_domain.current_timer_remaining_ms(self._timer_state(), time.monotonic())

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
        if normalized_calendar_style(self.store) == "desktop":
            self.selected_day -= timedelta(weeks=4)
            self.visible_month = self.selected_day.replace(day=1)
            self.render_calendar()
            return
        year = self.visible_month.year
        month = self.visible_month.month - 1
        if month == 0:
            year -= 1
            month = 12
        self.visible_month = date(year, month, 1)
        self.render_calendar()

    def next_month(self) -> None:
        """달력을 다음 달로 이동합니다."""
        if normalized_calendar_style(self.store) == "desktop":
            self.selected_day += timedelta(weeks=4)
            self.visible_month = self.selected_day.replace(day=1)
            self.render_calendar()
            return
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

    def open_quick_input(self) -> None:
        """Quick Input 입력바를 엽니다."""
        self.window_manager.open_quick_input()

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

    def set_calendar_style(self, style: str) -> None:
        """현재 프리셋 기하를 저장하고 다른 전체 달력 디자인을 즉시 적용한다."""
        current_style = normalized_calendar_style(self.store)
        requested = normalized_calendar_style({"calendar_style": style})
        if current_style == requested:
            return

        search_text = self.search_input.text() if hasattr(self, "search_input") else ""
        popover = self.calendar_quick_popover
        reopen_popover = bool(popover is not None and popover.isVisible())
        popover_day = popover.day if popover is not None else self.selected_day
        popover_text = popover.input.text() if popover is not None else ""
        if popover is not None:
            popover.hide()
        current_geometry = geometry_string(self)
        geometries = self.store.get("calendar_geometries", {})
        geometries = dict(geometries) if isinstance(geometries, dict) else {}
        geometries[current_style] = current_geometry
        target_geometry = calendar_geometry_for_style(
            self.store,
            requested,
            self.store.get("calendar_geometry", DEFAULT_CALENDAR_GEOMETRY),
        )

        self.store.set("calendar_geometries", geometries, notify_topic=None)
        self.store.set("calendar_style", requested)
        self.build_ui()
        self.search_input.setText(search_text)
        width, height, x, y = parse_geometry(
            target_geometry,
            (self.width(), self.height(), self.x(), self.y()),
        )
        self.setGeometry(x, y, width, height)
        applied_geometry = geometry_string(self)
        self.store.set("calendar_geometry", applied_geometry, notify_topic=None)
        self.store.save()
        self.render_calendar()
        if reopen_popover:
            QTimer.singleShot(
                0,
                lambda: self.open_calendar_quick_popover(popover_day, popover_text),
            )

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
                # C3(repo-layout-v1): 이 모듈은 chronofox/windows/ 하위로 이동했으므로
                # Path(__file__)는 더 이상 실행 진입점이 아니다 — 루트 shim(REPO_ROOT의
                # desktop_note_calendar.py)을 가리켜야 시작프로그램에서 정상 기동한다.
                STARTUP_PATH.write_text(
                    f'@echo off\nstart "" "{launcher}" "{REPO_ROOT / "desktop_note_calendar.py"}"\n',
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
        desired_style = normalized_calendar_style(self.store)
        if hasattr(self, "calendar_root") and getattr(self, "layout_preset", {}).get("key") != desired_style:
            self.build_ui()
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
        if hasattr(self, "layout_preset"):
            self.layout_preset.update(calendar_layout_preset(self.store, c))
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "calendar_root"):
            root_name = self.calendar_root.objectName()
            root_bg = self.layout_preset.get("window_background", c["bg"])
            self.calendar_root.setStyleSheet(
                f"QFrame#{root_name} {{ background: {root_bg}; border: none; }}"
                + self.calendar_auxiliary_style()
            )
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
        if self.calendar_quick_popover is not None:
            self.calendar_quick_popover.apply_theme()
        if hasattr(self, "header_separator"):
            self.header_separator.setStyleSheet(f"background: {c['border']};")
        for button in getattr(self, "header_buttons", []):
            button.setStyleSheet(self.header_button_style())
        for button in getattr(self, "icon_buttons", []):
            button.refresh_style()
            button.update()
        for label in getattr(self, "weekday_labels", []):
            weekday_index = int(label.property("weekday_index") or 0)
            label.setStyleSheet(self.weekday_label_style(weekday_index))
        # R16: calendar_style이 테마 페이지에서 바뀌었을 수도 있으니(apply_theme 경로 공용)
        # 매번 다시 계산한다. 기존 dict 객체를 in-place로 갱신해 모든 DayCell.style 참조가
        # 재할당 없이 최신값을 보게 한다(self.colors.update(...) 패턴과 동일).
        if hasattr(self, "cell_style"):
            self.cell_style.clear()
            self.cell_style.update(calendar_cell_style(self.store, c))
            self.cell_style["date_alignment"] = self.layout_preset.get("date_alignment", "left")
        for cell in self.day_cells:
            cell.update()

    def closeEvent(self, event) -> None:
        if not self.skip_exit_flush:
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
    # 창은 아래에서 뒤늦게 만들어지므로, crash handler에게는 mutable holder를 가리키는
    # lambda를 넘긴다 — 창 생성 전에 크래시가 나도 app_getter()가 안전하게 None을 반환한다.
    window_holder: dict[str, FoxCalendarApp | None] = {"window": None}
    install_crash_handler(lambda: window_holder["window"])
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    load_app_font(app, load_config())
    app.setQuitOnLastWindowClosed(False)
    window = FoxCalendarApp()
    window_holder["window"] = window
    app.main_window = window  # type: ignore[attr-defined]
    app.aboutToQuit.connect(window.persist_open_windows)
    # Q3: RegisterHotKey 해제를 앱 종료 시 보장한다. aboutToQuit는 트레이 종료
    # (QApplication.quit())와 정상 창 닫힘 양쪽 모두를 아우르는 단일 종료 지점이다.
    app.aboutToQuit.connect(window.global_hotkey.detach)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
