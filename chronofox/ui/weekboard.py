"""Weekly calendar surface; its owning window controls refresh and subscriptions."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.task_logic import is_active, is_upcoming, recurrence_available_on
from chronofox.core.todo_logic import classify_and_sort
from chronofox.ui.app_ui import app_font


class _DayButton(QPushButton):
    activated = Signal()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit()
        super().mouseDoubleClickEvent(event)


class WeekboardWidget(QWidget):
    daySelected = Signal(object)
    dayActivated = Signal(object)

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        self.days = []
        self._state = None
        self._in_task_action = False
        self._deferred = False
        self.setObjectName("weekboard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._body = None
        self._day_buttons = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._finish_refresh)

    def _tr(self, key, fallback):
        return self.app.tr(key, fallback)

    def _label(self, text, size=9, color=None, bold=False):
        label = QLabel(str(text))
        label.setTextFormat(Qt.PlainText)
        label.setFont(app_font(size, QFont.DemiBold if bold else QFont.Normal))
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        if color:
            label.setStyleSheet(f"color: {color}; background: transparent; border: none;")
        return label

    def _scroll(self, content, background):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{background: {background}; border: none;}}")
        scroll.viewport().setStyleSheet(f"background: {background};")
        content.setStyleSheet(f"background: {background};")
        scroll.setWidget(content)
        return scroll

    def _task_groups(self, selected, today):
        dated, undated = [], []
        for task in self.app.store.tasks():
            if not is_active(task):
                continue
            if task.get("recurrence"):
                start = recurrence_available_on(task)
                belongs = (
                    start == selected if is_upcoming(task, today)
                    else selected == today
                )
                if belongs:
                    dated.append(("", task))
            elif task.get("due") == selected.isoformat() or task.get("my_day_date") == selected.isoformat():
                dated.append(("", task))
            elif not task.get("due") and not task.get("my_day_date"):
                undated.append(("", task))
        return [task for _, task in classify_and_sort(dated, lambda *_: False)[0]], [
            task for _, task in classify_and_sort(undated, lambda *_: False)[0]
        ]

    def refresh(self, anchor_day, selected_day, first_weekday):
        self._state = (anchor_day, selected_day, int(first_weekday) % 7)
        if self._in_task_action:
            self._deferred = True
            return
        self._render()

    def _finish_refresh(self):
        if self._state is not None:
            self._deferred = False
            self._render()

    def _toggle_task(self, task_id):
        # Store notifications are synchronous; retain the emitting checkbox until
        # its signal unwinds rather than rebuilding children inside its callback.
        self._in_task_action = True
        try:
            self.app.task_service.toggle_complete(task_id)
        finally:
            self._in_task_action = False
            self._refresh_timer.start(0)

    def _select(self, day):
        self.daySelected.emit(day)

    def _render(self):
        anchor, selected, first = self._state
        today = date.today()
        start = anchor - timedelta(days=(anchor.weekday() - first) % 7)
        self.days = [start + timedelta(days=i) for i in range(7)]
        previous_buttons = self._day_buttons
        self._day_buttons = {}
        c = self.app.calendar_colors
        bg, ink, muted, line = c["bg"], c["text"], c["muted"], c["border"]
        side = c.get("wb_sidebar", c["panel2"])
        side_text = c.get("wb_sidebar_text", ink)
        side_muted = c.get("wb_sidebar_muted", muted)
        lime = c.get("wb_lime", c["accent"])
        lime_text = c.get("wb_lime_text", c["text"])
        card = c.get("wb_card", c["panel"])
        body = QWidget()
        body.setObjectName("wbBody")
        body.setStyleSheet(f"QWidget#wbBody {{ background: {bg}; color: {ink}; }}")
        outer = QVBoxLayout(body)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(16)
        heading = QHBoxLayout()
        titlebox = QVBoxLayout()
        titlebox.setSpacing(4)
        titlebox.addWidget(self._label(self._tr("weekboard.kicker", "주간 일정 · TODO"), 8, muted))
        title = self._tr("weekboard.title", "이번 주.") if today in self.days else self._tr("weekboard.selected_week", "선택한 주.")
        titlebox.addWidget(self._label(title, 30, ink, True))
        # ISO 주는 목요일이 속한 주다. 일요일 시작에서도 날짜 선택으로 주차가 바뀌면 안 된다.
        iso = next(day for day in self.days if day.weekday() == 3).isocalendar()
        titlebox.addWidget(self._label(f"{start:%Y.%m.%d} — {self.days[-1]:%Y.%m.%d}  ·  {iso.year} / W{iso.week:02}", 9, muted))
        heading.addLayout(titlebox, 1)
        today_button = QPushButton(self._tr("weekboard.today", "오늘로"))
        today_button.setFont(app_font(9))
        today_button.setStyleSheet(f"background: {lime}; color: {lime_text}; border: none; border-radius: 6px; padding: 9px 16px;")
        today_button.clicked.connect(lambda: self._select(today))
        heading.addWidget(today_button, 0, Qt.AlignBottom)
        outer.addLayout(heading)
        main = QHBoxLayout()
        main.setSpacing(20)
        week = QWidget()
        week_layout = QVBoxLayout(week)
        week_layout.setContentsMargins(0, 0, 0, 0)
        week_layout.setSpacing(14)
        columns = QHBoxLayout()
        columns.setSpacing(0)
        event_ids = set()
        schedule_count = 0
        weekdays = [("mon", "월"), ("tue", "화"), ("wed", "수"), ("thu", "목"), ("fri", "금"), ("sat", "토"), ("sun", "일")]
        for day in self.days:
            column = QFrame()
            column.setObjectName("wbColumn")
            column.setStyleSheet(f"QFrame#wbColumn {{background: {card if day == selected else bg}; border-top: 1px solid {line}; border-right: 1px solid {line}; border-bottom: 1px solid {line};}}")
            vertical = QVBoxLayout(column)
            vertical.setContentsMargins(7, 12, 7, 12)
            vertical.setSpacing(12)
            key, fallback = weekdays[day.weekday()]
            name = self._tr(f"calendar.weekday.{key}", fallback)
            if day == today:
                name += " · " + self._tr("weekboard.today_tag", "오늘")
            vertical.addWidget(self._label(name, 8, muted))
            button = previous_buttons.get(day)
            if button is None:
                button = _DayButton(str(day.day))
                button.clicked.connect(lambda checked=False, d=day: self._select(d))
                button.activated.connect(lambda d=day: self.dayActivated.emit(d))
            else:
                # Qt tracks double-clicks by receiver identity; keep the date
                # button alive while updating the selection and TODO panel.
                button.setParent(column)
            self._day_buttons[day] = button
            button.setObjectName(f"wbDay_{day.isoformat()}")
            button.setFont(app_font(22, QFont.DemiBold))
            button.setMinimumHeight(52)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
            button.setAccessibleName(f"{day.isoformat()} {name}")
            button.setCheckable(True)
            button.setChecked(day == selected)
            button.setStyleSheet(f"QPushButton {{text-align: left; padding: 5px; border: none; background: transparent; color: {ink};}} QPushButton:checked {{background: {lime}; color: {lime_text}; border-radius: 6px;}} QPushButton:hover {{border: 1px solid {line};}}")
            vertical.addWidget(button)
            button.show()
            events = QWidget()
            event_layout = QVBoxLayout(events)
            event_layout.setContentsMargins(0, 0, 0, 0)
            event_layout.setSpacing(16)
            plans = sorted(self.app.plan_service.plans_for_day(day), key=lambda plan: str(plan.get("start", "")))
            schedule = self.app.plan_service.get_schedule(day)
            for plan in plans:
                event_ids.add(str(plan.get("id") or (plan.get("title"), plan.get("start"), plan.get("end"))))
                event = QFrame()
                event.setStyleSheet(f"QFrame {{border-left: 2px solid {muted};}}")
                el = QVBoxLayout(event)
                el.setContentsMargins(6, 2, 1, 2)
                el.setSpacing(4)
                value = str(plan.get("start", ""))
                time = value[11:16] if plan.get("kind") != "long" and "T" in value and len(value) >= 16 else self._tr("weekboard.all_day", "종일")
                el.addWidget(self._label(time, 8, muted))
                el.addWidget(self._label(plan.get("title", ""), 9, ink))
                event_layout.addWidget(event)
            if schedule:
                schedule_count += 1
                event_layout.addWidget(self._label(schedule, 9, ink))
            if not plans and not schedule:
                event_layout.addWidget(self._label(self._tr("weekboard.free", "여유로운 하루"), 8, muted))
            event_layout.addStretch()
            vertical.addWidget(self._scroll(events, card if day == selected else bg), 1)
            tasks, _ = self._task_groups(day, today)
            vertical.addWidget(self._label(self._tr("weekboard.task_count", "할 일 {n}개").format(n=len(tasks)), 8, muted))
            columns.addWidget(column, 1)
        week_layout.addLayout(columns, 1)
        dated, undated = self._task_groups(selected, today)
        summary = self._tr("weekboard.summary", "일정 {events}개 · 선택일 할 일 {tasks}개").format(events=len(event_ids) + schedule_count, tasks=len(dated))
        week_layout.addWidget(self._label(self._tr("weekboard.flow", "한 주의 흐름") + "  ·  " + summary, 9, muted))
        main.addWidget(week, 1)
        pane = QFrame()
        pane.setObjectName("wbTaskPane")
        pane.setFixedWidth(250)
        pane.setStyleSheet(f"QFrame#wbTaskPane {{background: {side}; border-top: 3px solid {lime}; border-radius: 4px;}}")
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(18, 18, 18, 16)
        pv.setSpacing(12)
        pv.addWidget(self._label(self._tr("weekboard.tasks_today", "오늘 할 일") if selected == today else self._tr("weekboard.tasks_day", "이날 할 일"), 16, side_text, True))
        pv.addWidget(self._label(f"{selected:%Y.%m.%d}", 9, side_muted))
        task_content = QWidget()
        tv = QVBoxLayout(task_content)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(12)
        if not dated:
            tv.addWidget(self._label(self._tr("weekboard.empty_tasks", "이날 할 일이 없습니다."), 9, side_muted))
        for group, items in ((None, dated), (self._tr("weekboard.unscheduled", "날짜 미지정"), undated)):
            if group and items:
                tv.addWidget(self._label(group, 8, side_muted, True))
            for task in items:
                row = QWidget()
                rv = QHBoxLayout(row)
                rv.setContentsMargins(0, 8, 0, 8)
                rv.setSpacing(9)
                check = QCheckBox()
                check.setEnabled(not self.app.task_service.locked())
                check.setProperty("task_id", task.get("id"))
                check.setAccessibleName(str(task.get("text", "")))
                check.setStyleSheet(f"QCheckBox::indicator {{width: 15px; height: 15px; border: 1px solid {side_muted}; border-radius: 3px; background: {side};}} QCheckBox::indicator:checked {{background: {lime}; border-color: {lime};}}")
                task_id = task.get("id")
                check.clicked.connect(lambda checked=False, tid=task_id: self._toggle_task(tid))
                rv.addWidget(check, 0, Qt.AlignTop)
                text = QVBoxLayout()
                text.setSpacing(4)
                if task.get("important"):
                    text.addWidget(self._label(self._tr("weekboard.priority", "우선 처리"), 8, lime))
                text.addWidget(self._label(task.get("text", ""), 10, side_text))
                if task.get("due") and not task.get("recurrence"):
                    text.addWidget(self._label(self._tr("weekboard.due", "마감 {date}").format(date=task["due"]), 8, side_muted))
                rv.addLayout(text, 1)
                tv.addWidget(row)
        tv.addStretch()
        pv.addWidget(self._scroll(task_content, side), 1)
        pv.addWidget(self._label(self._tr("weekboard.remaining", "{n}개 남음").format(n=len(dated) + len(undated)), 8, side_muted))
        open_button = QPushButton(self._tr("weekboard.open_tasks", "전체 할 일 열기 ↗"))
        open_button.setFont(app_font(9))
        open_button.setStyleSheet(f"color: {side_text}; background: transparent; border: 1px solid {side_muted}; border-radius: 5px; padding: 9px;")
        open_button.clicked.connect(lambda: self.app.open_repeat())
        pv.addWidget(open_button)
        main.addWidget(pane)
        outer.addLayout(main, 1)
        footer = self._label(self._tr("weekboard.footer", "7일 보기 · 날짜 두 번 클릭으로 일정 열기"), 8, muted)
        outer.addWidget(footer)
        old = self._body
        self._body = body
        self._layout.addWidget(body)
        if old is not None:
            self._layout.removeWidget(old)
            old.hide()
            old.setParent(None)
            old.deleteLater()
