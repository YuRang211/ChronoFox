"""Detail-schedule 창의 "해야 할 일" 섹션 믹스인.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어가 제공):
- `self.app`(FoxCalendarApp, `.repeat_window` 보관), `self.colors`(dict), `self.section`(str)
- `self.task_filter`(str), `self.tasks_box`(QVBoxLayout, build_tasks_view가 생성)
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.build_ui()`, `self.icon_only_button(icon, handler)`, `self.scroll_style()`, `self.close()`
"""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app_theme import IMPORTANT_STAR_COLOR
from app_ui import app_font, clear_layout
from todo_window import RepeatWindow

from .widgets import stroke_icon


class TasksSectionMixin:
    """할 일 목록 상단바/본문/행/필터/토글 액션과 관련 스타일을 담당합니다."""

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
        my_day.clicked.connect(lambda _checked=False, t=task: self.toggle_task_my_day(t))

        edit = QPushButton(self.tr("common.edit", "수정"))
        edit.setFixedHeight(28)
        edit.setCursor(Qt.PointingHandCursor)
        edit.clicked.connect(lambda _checked=False, p=period, t=task: self.edit_task_item(p, t))

        for button in (my_day, edit):
            button.setStyleSheet(self.task_edit_style())

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
        color = IMPORTANT_STAR_COLOR if active else c["muted"]
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
