"""Quick Input(0.9) Q2 — 입력바 + 실시간 미리보기 카드 UI.

`planning/specs/quick-input-parser.md` §4(U2~U6)/§4b(Q2) 구현. `chronofox.core.
quick_input_parser.parse(text, now) -> Draft`만 호출해 분류하고, 저장은 종류별
기존 API만 경유한다(PlanService.add_plan/schedule 도메인/RepeatWindow.add_task/
FoxCalendarApp.add_alarm·start_timer_ms). 파서 자체는 손대지 않는다 — P0/P1.

ALARM/TIMER 저장(B1, `planning/QA.md`)은 `FoxCalendarApp.add_alarm`/`start_timer_ms`
얇은 위임 메서드를 거쳐 `chronofox.core.clock_domain`의 Qt-free 순수 함수를 직접
호출한다. 예전에는 이 두 종류만 데이터 변경 로직이 `ClockWindow` 믹스인 메서드로만
존재해 화면에 띄우지 않는 숨김 `ClockWindow` 인스턴스(`_headless_clock_window`)를
만드는 우회가 필요했지만, 도메인 로직이 `core/`로 옮겨진 뒤로는 더 이상 어떤 창도
만들지 않는다 — "창 열지 않고 데이터 추가"(U5/보고 조항) 요건을 우회 없이 만족한다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from chronofox.core.app_constants import APP_NAME, SEARCH_DEBOUNCE_MS
from chronofox.core.quick_input_parser import Draft, Kind, parse
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_theme import IMPORTANT_STAR_COLOR, PLAN_COLOR_CHOICES
from chronofox.ui.app_ui import app_font, clamp_window_position
from chronofox.ui.app_widgets import RoundedWindow
from chronofox.windows.todo_window import RepeatWindow

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp

WINDOW_WIDTH = 580
WINDOW_HEIGHT = 224

_PERIOD_LABEL_KEYS = {
    "daily": ("todo.period.daily", "매일"),
    "weekly": ("todo.period.weekly", "매주"),
    "monthly": ("todo.period.monthly", "매월"),
    "yearly": ("todo.period.yearly", "매년"),
}

_KIND_LABEL_KEYS = {
    Kind.PLAN: ("quick.kind.plan", "일정"),
    Kind.NOTE: ("quick.kind.note", "노트"),
    Kind.ALARM: ("quick.kind.alarm", "알람"),
    Kind.TIMER: ("quick.kind.timer", "타이머"),
    Kind.TASK: ("quick.kind.task", "할 일"),
    Kind.RECURRING: ("quick.kind.task", "할 일"),
}


# ---------------------------------------------------------------------------
# 순수 Draft 변환 헬퍼 (재파싱 아님 — parse()는 recurring_to_plan 케이스에서만,
# 그것도 UI 계층에서 명시적으로 호출한다. 파서 모듈 자체는 그대로 둔다)
# ---------------------------------------------------------------------------


def _shift_ampm(value: datetime) -> datetime:
    """12시간을 더하거나 빼 AM/PM 해석을 뒤집습니다(왕복 가능한 순수 변환)."""
    return value + timedelta(hours=(-12 if value.hour >= 12 else 12))


def toggle_ampm(draft: Draft) -> Draft:
    """AM/PM 모호성 토글: start/end를 함께 12시간 이동시켜 지속시간을 보존합니다."""
    if draft.start is None:
        return draft
    new_start = _shift_ampm(draft.start)
    new_end = _shift_ampm(draft.end) if draft.end is not None else None
    return replace(draft, start=new_start, end=new_end)


def toggle_alarm_or_plan(draft: Draft) -> Draft:
    """알람 ↔ 오늘 일정 전환(왕복 가능): PLAN 기본 지속시간은 1시간."""
    if draft.kind == Kind.ALARM and draft.start is not None:
        return replace(draft, kind=Kind.PLAN, end=draft.start + timedelta(hours=1))
    if draft.kind == Kind.PLAN:
        return replace(draft, kind=Kind.ALARM, end=None)
    return draft


def toggle_recurring_to_plan(draft: Draft, now: datetime) -> Draft:
    """반복 할 일 → 일정 전환. 제목에 남아 있는 날짜/시각 토큰을 다시 해석해야 하므로
    이 한 번의 전환에 한해 remainder 텍스트에 parse()를 호출한다(원본 전체 재분류가
    아니라 이미 RECURRING으로 확정된 뒤 그 제목만 대상으로 한다). 실패하면(PLAN이
    아니면) 원본을 그대로 반환한다 — 조용히 아무 일도 하지 않음(P1, 보수적)."""
    if draft.kind != Kind.RECURRING:
        return draft
    reparsed = parse(draft.title, now)
    if reparsed.kind == Kind.PLAN:
        return reparsed
    return draft


class _QuickInputLineEdit(QLineEdit):
    """Esc를 부모(QuickInputWindow)로 넘기지 않고 명시적 시그널로 알리는 입력창."""

    escape_pressed = Signal()

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.escape_pressed.emit()
            return
        super().keyPressEvent(event)


class QuickInputWindow(TrMixin, RoundedWindow):
    """빠른 입력 입력바 + 실시간 미리보기 카드(U3~U5)."""

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.setWindowTitle(self.window_title_text())
        self.setWindowIcon(app.icon)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize_handle.setVisible(False)
        self.setFixedSize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._base_draft: Draft | None = None
        self._now = datetime.now()
        self._ampm_flipped = False
        self._reclassified = False
        self._card_active = False
        self._activated_once = False

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self.preview_timer.timeout.connect(self._refresh_preview)

        self._build_ui()
        self._position_top_center()

    # -- window title / i18n ------------------------------------------------
    def window_title_text(self) -> str:
        """현재 언어에 맞는 창 제목 문자열을 반환합니다."""
        return self.tr("quick.window.title", "{app} 빠른 입력", app=self.tr("app.name", APP_NAME))

    # -- layout ---------------------------------------------------------------
    def _build_ui(self) -> None:
        c = self.colors
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        self.input = _QuickInputLineEdit()
        self.input.setPlaceholderText(self.tr("quick.placeholder", "예: 내일 3시 병원, 매일 물 마시기…"))
        self.input.setFont(app_font(13))
        self.input.setStyleSheet(self._input_style())
        self.input.textChanged.connect(self._on_text_changed)
        self.input.returnPressed.connect(self._on_return_pressed)
        self.input.escape_pressed.connect(self.close)
        layout.addWidget(self.input)

        self.card = QWidget()
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(12, 10, 12, 10)
        card_layout.setSpacing(8)

        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        self.kind_badge = QLabel("")
        self.kind_badge.setFont(app_font(10, QFont.Bold))
        self.kind_badge.setStyleSheet(
            f"background: {c['accent']}; color: #ffffff; border-radius: 8px; padding: 3px 10px;"
        )
        self.summary_label = QLabel("")
        self.summary_label.setFont(app_font(11))
        self.summary_label.setStyleSheet(f"color: {c['text']};")
        self.past_badge = QLabel(self.tr("quick.badge.past_time", "지난 시각입니다"))
        self.past_badge.setFont(app_font(9, QFont.Bold))
        self.past_badge.setStyleSheet(f"color: {IMPORTANT_STAR_COLOR};")
        self.past_badge.setVisible(False)
        top_row.addWidget(self.kind_badge)
        top_row.addWidget(self.summary_label)
        top_row.addStretch()
        top_row.addWidget(self.past_badge)
        card_layout.addLayout(top_row)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)
        self.ampm_button = QPushButton("")
        self.reclass_button = QPushButton("")
        for button in (self.ampm_button, self.reclass_button):
            button.setCursor(Qt.PointingHandCursor)
            button.setStyleSheet(self._toggle_button_style())
            button.setVisible(False)
        self.ampm_button.clicked.connect(self._on_toggle_ampm)
        self.reclass_button.clicked.connect(self._on_toggle_reclass)
        toggle_row.addWidget(self.ampm_button)
        toggle_row.addWidget(self.reclass_button)
        toggle_row.addStretch()
        card_layout.addLayout(toggle_row)
        card_layout.addStretch()

        layout.addWidget(self.card, 1)

        self.hint_label = QLabel(self.tr("quick.hint", "Enter로 저장 · Esc로 취소"))
        self.hint_label.setFont(app_font(9))
        self.hint_label.setStyleSheet(f"color: {c['muted']};")
        layout.addWidget(self.hint_label)

        self.card.setVisible(False)
        self.input.setFocus()

    def _input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; padding: 10px 12px; }}"
            f"QLineEdit:focus {{ border-color: {c['accent']}; }}"
        )

    def _toggle_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 4px 10px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )

    # -- positioning ----------------------------------------------------------
    def _position_top_center(self) -> None:
        """U3: 주 모니터 중앙 상단 1/3 지점에 배치합니다."""
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        if available is None:
            return
        preferred_x = available.x() + (available.width() - WINDOW_WIDTH) // 2
        preferred_y = available.y() + int(available.height() / 3) - WINDOW_HEIGHT // 2
        x, y = clamp_window_position(WINDOW_WIDTH, WINDOW_HEIGHT, preferred_x, preferred_y, available)
        self.move(x, y)

    # -- preview lifecycle ------------------------------------------------------
    def _on_text_changed(self, _text: str) -> None:
        self._ampm_flipped = False
        self._reclassified = False
        self.preview_timer.start()

    def _refresh_preview(self) -> None:
        if self.preview_timer.isActive():
            self.preview_timer.stop()
        text = self.input.text()
        if not text.strip():
            self._base_draft = None
            self._refresh_card()
            return
        self._now = datetime.now()
        self._base_draft = parse(text, self._now)
        self._refresh_card()

    def _effective_draft(self) -> Draft | None:
        base = self._base_draft
        if base is None:
            return None
        draft = base
        if self._reclassified:
            if base.kind == Kind.RECURRING and "recurring_time_kept_in_title" in base.ambiguity_flags:
                draft = toggle_recurring_to_plan(base, self._now)
            elif base.kind == Kind.ALARM and "alarm_or_plan" in base.ambiguity_flags:
                draft = toggle_alarm_or_plan(base)
        if self._ampm_flipped and "ampm" in draft.ambiguity_flags:
            draft = toggle_ampm(draft)
        return draft

    def _refresh_card(self) -> None:
        base = self._base_draft
        if base is None or not self.input.text().strip():
            self._card_active = False
            self.card.setVisible(False)
            return

        draft = self._effective_draft()
        assert draft is not None  # base is not None here
        self._card_active = True
        self.card.setVisible(True)

        label_key, label_fallback = _KIND_LABEL_KEYS[draft.kind]
        self.kind_badge.setText(self.tr(label_key, label_fallback))
        self.summary_label.setText(self._summary_text(draft))
        self.past_badge.setVisible(draft.kind == Kind.PLAN and "past_time" in draft.ambiguity_flags)

        show_ampm = "ampm" in base.ambiguity_flags
        self.ampm_button.setVisible(show_ampm)
        if show_ampm:
            is_pm = draft.start is not None and draft.start.hour >= 12
            key, fallback = ("quick.toggle.ampm_to_am", "오전으로") if is_pm else ("quick.toggle.ampm_to_pm", "오후로")
            self.ampm_button.setText(self.tr(key, fallback))

        show_reclass = "alarm_or_plan" in base.ambiguity_flags or "recurring_time_kept_in_title" in base.ambiguity_flags
        self.reclass_button.setVisible(show_reclass)
        if show_reclass:
            if base.kind == Kind.ALARM:
                key, fallback = (
                    ("quick.toggle.to_alarm", "알람으로") if self._reclassified else ("quick.toggle.to_plan", "오늘 일정으로")
                )
            else:
                key, fallback = (
                    ("quick.toggle.plan_to_recurring", "할 일로 되돌리기")
                    if self._reclassified
                    else ("quick.toggle.recurring_to_plan", "일정으로 만들기")
                )
            self.reclass_button.setText(self.tr(key, fallback))

    def _summary_text(self, draft: Draft) -> str:
        if draft.kind == Kind.PLAN and draft.start is not None:
            end_text = f"–{draft.end:%H:%M}" if draft.end is not None else ""
            return f"{draft.start:%m.%d} {draft.start:%H:%M}{end_text}"
        if draft.kind == Kind.NOTE and draft.start is not None:
            return f"{draft.start:%m.%d}"
        if draft.kind == Kind.ALARM and draft.start is not None:
            return f"{draft.start:%m.%d} {draft.start:%H:%M}"
        if draft.kind == Kind.TIMER and draft.duration_minutes is not None:
            return f"{draft.duration_minutes}{self.tr('quick.unit.minutes', '분')}"
        if draft.kind == Kind.RECURRING:
            key, fallback = _PERIOD_LABEL_KEYS.get(draft.period or "daily", _PERIOD_LABEL_KEYS["daily"])
            return self.tr(key, fallback)
        return ""

    # -- toggles ----------------------------------------------------------------
    def _on_toggle_ampm(self) -> None:
        self._ampm_flipped = not self._ampm_flipped
        self._refresh_card()

    def _on_toggle_reclass(self) -> None:
        self._reclassified = not self._reclassified
        self._refresh_card()

    # -- save ---------------------------------------------------------------------
    def _on_return_pressed(self) -> None:
        if not self._card_active:
            return
        self._save_current()

    def _save_current(self) -> None:
        draft = self._effective_draft()
        if draft is None:
            return
        title = draft.title.strip() or self.input.text().strip()
        if not title:
            return

        if draft.kind == Kind.PLAN:
            self._save_plan(draft, title)
        elif draft.kind == Kind.NOTE:
            self._save_note(draft, title)
        elif draft.kind in (Kind.TASK, Kind.RECURRING):
            self._save_task(draft, title)
        elif draft.kind == Kind.ALARM:
            self._save_alarm(draft, title)
        elif draft.kind == Kind.TIMER:
            self._save_timer(draft, title)
        else:  # pragma: no cover - Kind는 위 다섯 값만 가능
            return

        self._show_saved_toast(draft.kind, title)
        self.close()

    def _save_plan(self, draft: Draft, title: str) -> None:
        """PLAN → 기존 plan_service.add_plan 시그니처(schedule_window.save_plan 선례)."""
        start = draft.start
        end = draft.end or (start + timedelta(hours=1) if start else None)
        plan_data = {
            "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "kind": "day",
            "title": title,
            "start": start.isoformat() if start else "",
            "end": end.isoformat() if end else "",
            "description": "",
            "color": PLAN_COLOR_CHOICES[0],
            "reminder_minutes": -1,
            "reminder_fired": "",
        }
        self.app.add_plan(plan_data)

    def _save_note(self, draft: Draft, title: str) -> None:
        """NOTE → 기존 get_schedule/set_schedule로 해당 날짜에 한 줄 append."""
        day = draft.start.date() if draft.start is not None else date.today()
        existing = self.app.get_schedule(day)
        merged = f"{existing}\n{title}" if existing.strip() else title
        self.app.set_schedule(day, merged)

    def _save_task(self, draft: Draft, title: str) -> None:
        """TASK/RECURRING → RepeatWindow.add_task 공유 컨트롤러(tasks_section.task_controller 선례)."""
        period = draft.period or "daily"
        controller = self.app.repeat_window
        if controller is None:
            controller = RepeatWindow(self.app)
            self.app.repeat_window = controller
        controller.add_task(period, title)

    def _save_alarm(self, draft: Draft, title: str) -> None:
        """ALARM → FoxCalendarApp.add_alarm(얇은 위임, 내부는 clock_domain 순수 함수). 창을 만들지 않는다."""
        if draft.start is None:
            return
        payload = {
            "time": f"{draft.start:%H:%M}",
            "label": title,
            "enabled": True,
            "last_triggered": "",
            "kind": "date",
            "date": draft.start.date().isoformat(),
            "notify_mode": "popup",
            "repeat_days": [draft.start.weekday()],
            "snooze_minutes": 5,
            "snoozed_until": "",
            "sound_mode": "default",
            "sound_path": "",
            "sound_url": "",
        }
        self.app.add_alarm(payload)

    def _save_timer(self, draft: Draft, title: str) -> None:
        """TIMER → FoxCalendarApp.start_timer_ms(얇은 위임, 내부는 clock_domain 순수 함수). 창을 만들지 않는다."""
        minutes_total = max(1, int(draft.duration_minutes or 0))
        self.app.start_timer_ms(minutes_total * 60_000)

    def _show_saved_toast(self, kind: Kind, title: str) -> None:
        tray = getattr(self.app, "tray", None)
        if tray is None:
            return
        label_key, label_fallback = _KIND_LABEL_KEYS[kind]
        message = self.tr("quick.save.toast", "저장됨: {title}", title=title)
        tray.showMessage(self.tr(label_key, label_fallback), message, msecs=4000)

    # -- lifecycle -------------------------------------------------------------
    def changeEvent(self, event) -> None:
        if event.type() == QEvent.ActivationChange:
            if self.isActiveWindow():
                self._activated_once = True
            elif self._activated_once:
                # U3: Esc 또는 포커스 아웃 시 닫힘(저장 안 함). 실제로 한 번이라도
                # 활성화된 뒤에만 적용해, 오프스크린/초기 표시 단계의 가짜
                # 비활성 이벤트로 창이 뜨자마자 닫히는 것을 막는다.
                self.close()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        self.input.clear()
        self.app.quick_input_window = None
        super().closeEvent(event)
