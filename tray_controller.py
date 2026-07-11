"""S4(M5): FoxCalendarApp의 트레이 아이콘/메뉴 책임 분리 (D8).

TrayController는 ``app``(FoxCalendarApp)을 받아 트레이 관련 상태(``app.tray``,
``app.tray_menu``)를 그대로 app 객체 위에 만든다 — clock/alarms.py의
``getattr(self.app, "tray", None)`` 같은 기존 호출부가 무수정으로 계속 동작해야
하기 때문이다(D8). app은 이 클래스의 메서드를 얇게 위임만 한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp


class TrayController:
    """트레이 아이콘 생성, 메뉴 구성/갱신, 활성화 이벤트를 담당합니다."""

    def __init__(self, app: FoxCalendarApp) -> None:
        self.app = app

    def setup_tray(self) -> None:
        """시스템 트레이 아이콘과 메뉴를 초기화합니다."""
        app = self.app
        app.tray = QSystemTrayIcon(app.icon, app)
        app.tray.setToolTip(app.app_display_name())

        app.tray_menu = QMenu()
        app.tray_menu.setAttribute(Qt.WA_TranslucentBackground, True)
        app.tray_menu.setWindowFlags(
            app.tray_menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
        )
        app.tray_menu.setStyleSheet(self.tray_menu_style())
        app.tray_menu.aboutToShow.connect(self.update_tray_menu)

        app.tray.setContextMenu(app.tray_menu)
        app.tray.activated.connect(self.handle_tray_activated)
        app.tray.show()

    def tray_menu_style(self) -> str:
        """트레이 메뉴 QSS 스타일 문자열을 만듭니다."""
        c = self.app.colors

        def hex_to_rgba(hex_str: str, alpha: float) -> str:
            """'#RRGGBB' 색상 문자열을 지정한 alpha의 rgba() CSS 값으로 변환합니다."""
            hex_str = hex_str.lstrip('#')
            if len(hex_str) == 6:
                r = int(hex_str[0:2], 16)
                g = int(hex_str[2:4], 16)
                b = int(hex_str[4:6], 16)
                return f"rgba({r}, {g}, {b}, {int(alpha * 255)})"
            return hex_str

        is_dark = c.get("bg", "#ffffff") in ["#1c1c1e", "#161617"]
        bg_alpha = 0.94 if is_dark else 0.96
        bg_color = hex_to_rgba(c["panel"], bg_alpha)
        text_color = c["text"]
        border_color = c["border"]
        accent_color = c["accent"]

        return (
            f"QMenu {{ "
            f"  background-color: {bg_color}; "
            f"  color: {text_color}; "
            f"  border: 1px solid {border_color}; "
            f"  border-radius: 12px; "
            f"  padding: 6px; "
            f"  font-family: 'SF Pro Text', system-ui, -apple-system, sans-serif; "
            f"  font-size: 13px; "
            f"}} "
            f"QMenu::item {{ "
            f"  padding: 8px 36px 8px 16px; "
            f"  margin: 2px 4px; "
            f"  border-radius: 6px; "
            f"  background: transparent; "
            f"}} "
            f"QMenu::item:selected {{ "
            f"  background-color: {accent_color}; "
            f"  color: #ffffff; "
            f"}} "
            f"QMenu::separator {{ "
            f"  height: 1px; "
            f"  background-color: {border_color}; "
            f"  margin: 6px 12px; "
            f"}} "
        )

    def update_tray_menu(self) -> None:
        """트레이 메뉴 항목을 현재 상태로 갱신합니다."""
        app = self.app
        app.tray_menu.setStyleSheet(self.tray_menu_style())
        app.tray_menu.clear()

        # 1. Alarm status (only when an upcoming alarm exists)
        status_item_added = False
        best_alarm = app.next_alarm_occurrence()
        if best_alarm:
            today = date.today()
            if best_alarm.date() == today:
                day_text = app.tr("detail.when.today", "오늘")
            elif best_alarm.date() == today + timedelta(days=1):
                day_text = app.tr("detail.when.tomorrow", "내일")
            else:
                weekday_keys = [
                    ("calendar.weekday.mon", "월"),
                    ("calendar.weekday.tue", "화"),
                    ("calendar.weekday.wed", "수"),
                    ("calendar.weekday.thu", "목"),
                    ("calendar.weekday.fri", "금"),
                    ("calendar.weekday.sat", "토"),
                    ("calendar.weekday.sun", "일"),
                ]
                key, fallback = weekday_keys[best_alarm.weekday()]
                day_text = app.tr(key, fallback)
            alarm_text = app.tr("clock.next_alarm", "다음 알람 · {day} {time}").format(day=day_text, time=f"{best_alarm:%H:%M}")

            alarm_action = QAction(alarm_text, app)
            alarm_action.triggered.connect(lambda: app.open_clock_tab(3))  # Alarm tab
            app.tray_menu.addAction(alarm_action)
            status_item_added = True

        # 2. Timer status (only while actively running)
        if app.timer_running:
            timer_text = app.tr("clock.tray.timer_running", "타이머 · {time} 남음").format(time=app.format_timer_tray(app.current_timer_remaining_ms()))
            timer_action = QAction(timer_text, app)
            timer_action.triggered.connect(lambda: app.open_clock_tab(2))  # Timer tab
            app.tray_menu.addAction(timer_action)
            status_item_added = True

        # 3. Stopwatch status (only while actively running)
        if app.stopwatch_running:
            stopwatch_text = app.tr("clock.tray.stopwatch_running", "스톱워치 · {time}").format(time=app.format_stopwatch_tray(app.current_stopwatch_elapsed()))
            stopwatch_action = QAction(stopwatch_text, app)
            stopwatch_action.triggered.connect(lambda: app.open_clock_tab(1))  # Stopwatch tab
            app.tray_menu.addAction(stopwatch_action)
            status_item_added = True

        if status_item_added:
            app.tray_menu.addSeparator()

        # 4. Standard items
        show_action = QAction(app.tr("tray.open", "크로노폭스 열기"), app)
        show_action.triggered.connect(app.show_calendar)
        app.tray_menu.addAction(show_action)

        memo_action = QAction(app.tr("tray.new_memo", "새 메모"), app)
        memo_action.triggered.connect(app.create_memo)
        app.tray_menu.addAction(memo_action)

        settings_action = QAction(app.tr("tray.settings", "설정"), app)
        settings_action.triggered.connect(app.open_settings)
        app.tray_menu.addAction(settings_action)

        app.tray_menu.addSeparator()

        quit_action = QAction(app.tr("tray.quit", "종료"), app)
        quit_action.triggered.connect(app.quit_from_tray)
        app.tray_menu.addAction(quit_action)

    def refresh_tray_texts(self) -> None:
        """언어가 바뀐 뒤 트레이 메뉴 텍스트를 다시 그립니다."""
        app = self.app
        if hasattr(app, "tray"):
            app.tray.setToolTip(app.app_display_name())

    def handle_tray_activated(self, reason) -> None:
        """트레이 아이콘 클릭/더블클릭 이벤트를 처리합니다."""
        app = self.app
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if app.isVisible() and app.isActiveWindow():
                app.hide()
            else:
                app.show_calendar()

    def quit_from_tray(self) -> None:
        """트레이 메뉴에서 앱을 종료합니다."""
        app = self.app
        app.force_quit = True
        # RESTORE1: 복원 직후에는 flush/save를 건너뛴다 — 디스크의 복원본을 옛 메모리
        # 상태로 덮어쓰지 않기 위함이다.
        if not getattr(app, "skip_exit_flush", False):
            app.persist_open_windows()
            app.save()
        QApplication.quit()
