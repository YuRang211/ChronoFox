from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QDateTime, Qt, QTime
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QDateEdit, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QStackedWidget, QTextEdit, QTimeEdit, QVBoxLayout, QWidget

from app_constants import APP_NAME
from app_ui import add_soft_shadow, app_font, clear_layout, parse_geometry
from app_widgets import ArrowComboBox, RoundedWindow, Switch

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class ScheduleWindow(RoundedWindow):
    """선택한 날짜의 일정 텍스트를 편집하는 창입니다."""

    def __init__(self, app: "FoxCalendarApp", schedule_day: date, geometry: str | None = None) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.schedule_day = schedule_day
        self.plan_window: PlanWindow | None = None
        self.setWindowTitle(f"{APP_NAME} {self.schedule_day:%Y.%m.%d}")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(geometry or "620x430+260+160", (620, 430, 260, 160))
        width = max(width, 560)
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        colors = self.colors
        self.styled_buttons: list[QPushButton] = []
        self.pages: list[QWidget] = []
        existing = self.layout()
        if existing is None:
            layout = QHBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(134)
        self.sidebar.setStyleSheet(
            f"QFrame {{ background: {colors['panel2']}; border: none; border-top-left-radius: {self.radius}px; "
            f"border-bottom-left-radius: {self.radius}px; }}"
        )
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setContentsMargins(14, 18, 10, 18)
        sidebar_layout.setSpacing(8)
        self.side_date = QLabel(f"{self.schedule_day:%y.%m.%d}\n{self.schedule_day.isocalendar().week}주차")
        self.side_date.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.side_date.setFixedWidth(98)
        self.side_date.setWordWrap(False)
        self.side_date.setFont(app_font(12, QFont.Bold))
        self.side_date.setStyleSheet(f"color: {colors['text']};")
        self.sidebar_list = QListWidget()
        self.sidebar_list.setFrameShape(QFrame.NoFrame)
        self.sidebar_list.setStyleSheet(self.sidebar_style())
        self.sidebar_list.addItem("일정")
        self.sidebar_list.addItem("해야 할 일")
        self.sidebar_list.addItem("계획")
        self.sidebar_list.setCurrentRow(0)
        self.sidebar_list.currentRowChanged.connect(self.switch_page)
        top_info = QHBoxLayout()
        top_info.setContentsMargins(0, 0, 0, 0)
        top_info.setSpacing(6)
        top_info.addWidget(self.side_date)
        top_info.addStretch()
        sidebar_layout.addLayout(top_info)
        sidebar_layout.addSpacing(6)
        sidebar_layout.addWidget(self.sidebar_list, 1)

        self.content = QFrame()
        self.content.setStyleSheet(
            f"QFrame {{ background: {colors['bg']}; border: none; border-top-right-radius: {self.radius}px; "
            f"border-bottom-right-radius: {self.radius}px; }}"
        )
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(18, 14, 18, 16)
        content_layout.setSpacing(10)

        header = QHBoxLayout()
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        self.styled_buttons.append(close)
        header.addStretch()
        header.addWidget(close)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.schedule_page(colors))
        self.stack.addWidget(self.recurring_page(colors))
        self.stack.addWidget(self.plans_page(colors))

        content_layout.addLayout(header)
        content_layout.addWidget(self.stack, 1)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.content, 1)
        self.setStyleSheet(f"QLabel {{ color: {colors['text']}; }}")
        self.text.setFocus()

    def schedule_page(self, colors: dict[str, str]) -> QWidget:
        page = QWidget()
        self.pages.append(page)
        page.setStyleSheet(f"background: {colors['bg']};")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)

        self.text = QTextEdit()
        self.text.setPlainText(self.app.get_schedule(self.schedule_day))
        self.text.textChanged.connect(self.save_now)
        self.text.setStyleSheet(
            f"QTextEdit {{ background: {colors['panel']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 10px; padding: 10px; }}"
        )
        add_soft_shadow(self.text, colors, blur=14, alpha=24)

        footer = QHBoxLayout()
        plan_button = QPushButton("추가")
        plan_button.clicked.connect(self.open_plan)
        close_button = QPushButton("닫기")
        close_button.clicked.connect(self.close)
        for button in (plan_button, close_button):
            button.setStyleSheet(self.button_style())
            self.styled_buttons.append(button)
        footer.addStretch()
        footer.addWidget(plan_button)
        footer.addWidget(close_button)

        page_layout.addWidget(self.text, 1)
        page_layout.addLayout(footer)
        return page

    def recurring_page(self, colors: dict[str, str]) -> QWidget:
        page = QWidget()
        self.pages.append(page)
        page.setStyleSheet(f"background: {colors['bg']};")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)
        self.todo_list = QListWidget()
        self.todo_list.setStyleSheet(
            f"QListWidget {{ background: {colors['panel']}; color: {colors['text']}; border: 1px solid {colors['border']}; "
            "border-radius: 10px; padding: 6px; outline: none; }}"
            f"QListWidget::item {{ padding: 4px; }}"
        )
        add_soft_shadow(self.todo_list, colors, blur=14, alpha=24)
        self.fill_recurring_tasks()
        page_layout.addWidget(self.todo_list, 1)
        return page

    def plans_page(self, colors: dict[str, str]) -> QWidget:
        page = QWidget()
        self.pages.append(page)
        page.setStyleSheet(f"background: {colors['bg']};")
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(10)
        self.plan_list = QListWidget()
        self.plan_list.setStyleSheet(
            f"QListWidget {{ background: {colors['panel']}; color: {colors['text']}; border: 1px solid {colors['border']}; "
            "border-radius: 10px; padding: 6px; outline: none; }}"
            f"QListWidget::item {{ padding: 7px; }}"
        )
        add_soft_shadow(self.plan_list, colors, blur=14, alpha=24)
        self.plan_list.itemDoubleClicked.connect(self.edit_selected_plan)
        self.fill_plans()
        footer = QHBoxLayout()
        delete_button = QPushButton("삭제")
        delete_button.clicked.connect(self.delete_selected_plan)
        plan_button = QPushButton("일정")
        plan_button.clicked.connect(self.open_plan)
        for button in (delete_button, plan_button):
            button.setStyleSheet(self.button_style())
            self.styled_buttons.append(button)
        footer.addStretch()
        footer.addWidget(delete_button)
        footer.addWidget(plan_button)
        page_layout.addWidget(self.plan_list, 1)
        page_layout.addLayout(footer)
        return page

    def switch_page(self, row: int) -> None:
        if row >= 0:
            self.stack.setCurrentIndex(row)

    def sidebar_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: transparent; color: {c['muted']}; border: none; outline: none; }}"
            f"QListWidget::item {{ border: 1px solid transparent; border-radius: 7px; padding: 9px 10px; margin: 2px 0; }}"
            f"QListWidget::item:selected {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; }}"
            f"QListWidget::item:hover {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; }}"
        )

    def section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(app_font(10, QFont.Bold))
        return label

    def fill_recurring_tasks(self) -> None:
        self.todo_list.clear()
        for period, task in self.app.recurring_tasks_for_today():
            item = QListWidgetItem(f"{task.get('text', '')}  ·  {self.app.period_label(period)}")
            item.setCheckState(Qt.Checked if task.get("done") == self.app.recurring_current_key(period) else Qt.Unchecked)
            item.setData(Qt.UserRole, (period, task.get("id", "")))
            self.todo_list.addItem(item)
        self.todo_list.itemChanged.connect(self.toggle_recurring_item)

    def fill_plans(self) -> None:
        self.plan_list.clear()
        for plan in self.app.plans_for_day(self.schedule_day):
            label = self.app.plan_display_text(plan)
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, plan.get("id", ""))
            self.plan_list.addItem(item)

    def selected_plan(self) -> dict | None:
        item = self.plan_list.currentItem()
        if item is None:
            return None
        return self.app.find_plan(str(item.data(Qt.UserRole)))

    def edit_selected_plan(self) -> None:
        plan = self.selected_plan()
        if plan is not None:
            self.open_plan(plan)

    def delete_selected_plan(self) -> None:
        plan = self.selected_plan()
        if plan is not None:
            self.app.delete_plan(str(plan.get("id", "")))
            self.fill_plans()

    def toggle_recurring_item(self, item: QListWidgetItem) -> None:
        period, task_id = item.data(Qt.UserRole)
        task = self.app.find_recurring_task(period, task_id)
        if task is not None:
            self.app.set_recurring_done(period, task, item.checkState() == Qt.Checked)

    def open_plan(self, plan: dict | None = None) -> None:
        if self.plan_window and self.plan_window.isVisible():
            self.plan_window.close()
        self.plan_window = PlanWindow(self.app, self.schedule_day, plan)
        self.plan_window.show()

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 6px; padding: 6px 14px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def save_now(self) -> None:
        self.app.set_schedule(self.schedule_day, self.text.toPlainText())

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "sidebar"):
            self.sidebar.setStyleSheet(
                f"QFrame {{ background: {c['panel2']}; border: none; border-top-left-radius: {self.radius}px; "
                f"border-bottom-left-radius: {self.radius}px; }}"
            )
        if hasattr(self, "content"):
            self.content.setStyleSheet(
                f"QFrame {{ background: {c['bg']}; border: none; border-top-right-radius: {self.radius}px; "
                f"border-bottom-right-radius: {self.radius}px; }}"
            )
        if hasattr(self, "side_date"):
            self.side_date.setStyleSheet(f"color: {c['text']};")
        if hasattr(self, "sidebar_list"):
            self.sidebar_list.setStyleSheet(self.sidebar_style())
        for page in getattr(self, "pages", []):
            page.setStyleSheet(f"background: {c['bg']};")
        if hasattr(self, "text"):
            self.text.setStyleSheet(
                f"QTextEdit {{ background: {c['panel']}; color: {c['text']}; "
                f"border: 1px solid {c['border']}; border-radius: 10px; padding: 10px; }}"
            )
        if hasattr(self, "todo_list"):
            self.todo_list.setStyleSheet(
                f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
                "border-radius: 10px; padding: 6px; outline: none; }}"
                f"QListWidget::item {{ padding: 4px; }}"
            )
            self.fill_recurring_tasks()
        if hasattr(self, "plan_list"):
            self.plan_list.setStyleSheet(
                f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
                "border-radius: 10px; padding: 6px; outline: none; }}"
                f"QListWidget::item {{ padding: 7px; }}"
            )
            self.fill_plans()
        for button in getattr(self, "styled_buttons", []):
            button.setStyleSheet(self.button_style())
        if self.plan_window and self.plan_window.isVisible():
            self.plan_window.apply_theme()
        self.update()

    def closeEvent(self, event) -> None:
        self.save_now()
        self.app.schedule_windows.pop(self.schedule_day.isoformat(), None)
        super().closeEvent(event)

class PlanWindow(RoundedWindow):
    """날짜와 시간이 있는 별도 계획을 추가하는 창입니다."""

    COLORS = ["#3abf7a", "#e47d7d", "#7d8bd9", "#d9a441", "#5aa7d9", "#9b7bd9"]

    def __init__(self, app: "FoxCalendarApp", plan_day: date, plan: dict | None = None) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.plan_day = plan_day
        self.plan = plan
        self.selected_color = (plan or {}).get("color", self.COLORS[0])
        self.setWindowTitle(f"{APP_NAME} 계획 {'수정' if plan else '추가'}")
        self.setWindowIcon(app.icon)
        self.setGeometry(300, 190, 420, 360)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        self.styled_buttons: list[QPushButton] = []
        self.inputs: list[QWidget] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("계획 수정" if self.plan else "계획")
        title.setFont(app_font(15, QFont.Bold))
        all_day_label = QLabel("종일")
        all_day_label.setFont(app_font(10, QFont.Bold))
        self.all_day_switch = Switch((self.plan or {}).get("kind") == "long", c)
        self.all_day_switch.toggled.connect(lambda _checked: self.toggle_kind_fields())
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        self.styled_buttons.append(close)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(all_day_label)
        header.addWidget(self.all_day_switch)
        header.addWidget(close)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("제목")
        if self.plan:
            self.title_input.setText(self.plan.get("title", ""))
        self.title_input.setStyleSheet(self.input_style())
        self.inputs.append(self.title_input)

        self.day_row = QWidget()
        day_layout = QHBoxLayout(self.day_row)
        day_layout.setContentsMargins(0, 0, 0, 0)
        day_layout.setSpacing(8)
        self.start_time = QTimeEdit()
        self.start_time.setDisplayFormat("HH:mm")
        self.start_time.setTime(QTime.currentTime())
        self.start_time.setStyleSheet(self.input_style())
        self.inputs.append(self.start_time)
        self.end_time = QTimeEdit()
        self.end_time.setDisplayFormat("HH:mm")
        self.end_time.setTime(QTime.currentTime().addSecs(3600))
        self.end_time.setStyleSheet(self.input_style())
        self.inputs.append(self.end_time)
        day_layout.addWidget(self.start_time)
        day_layout.addWidget(self.end_time)

        self.date_row = QWidget()
        date_layout = QHBoxLayout(self.date_row)
        date_layout.setContentsMargins(0, 0, 0, 0)
        date_layout.setSpacing(8)
        self.start_date = QDateEdit()
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy.MM.dd")
        self.start_date.setDate(QDate(self.plan_day.year, self.plan_day.month, self.plan_day.day))
        self.start_date.setStyleSheet(self.input_style())
        self.inputs.append(self.start_date)

        self.end_date = QDateEdit()
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy.MM.dd")
        self.end_date.setDate(self.start_date.date())
        self.end_date.setStyleSheet(self.input_style())
        self.inputs.append(self.end_date)
        date_layout.addWidget(self.start_date)
        date_layout.addWidget(self.end_date)
        if self.plan:
            start_dt = QDateTime.fromString(str(self.plan.get("start", "")), Qt.ISODate)
            end_dt = QDateTime.fromString(str(self.plan.get("end", "")), Qt.ISODate)
            if start_dt.isValid():
                self.start_date.setDate(start_dt.date())
                self.start_time.setTime(start_dt.time())
            if end_dt.isValid():
                self.end_date.setDate(end_dt.date())
                self.end_time.setTime(end_dt.time())

        self.color_row = QWidget()
        color_layout = QHBoxLayout(self.color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(6)
        self.color_label = QLabel("색상")
        self.color_label.setStyleSheet(f"color: {c['muted']};")
        color_layout.addWidget(self.color_label)
        self.color_buttons = []
        for color in self.COLORS:
            button = QPushButton("")
            button.setFixedSize(24, 24)
            button.clicked.connect(lambda _checked=False, selected=color: self.set_plan_color(selected))
            self.color_buttons.append(button)
            color_layout.addWidget(button)
        color_layout.addStretch()
        self.refresh_color_buttons()

        self.description = QTextEdit()
        self.description.setPlaceholderText("설명")
        if self.plan:
            self.description.setPlainText(self.plan.get("description", ""))
        self.description.setStyleSheet(
            f"QTextEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; padding: 10px; }}"
        )
        self.inputs.append(self.description)

        save = QPushButton("저장" if self.plan else "추가")
        save.clicked.connect(self.save_plan)
        save.setStyleSheet(self.button_style())
        self.styled_buttons.append(save)

        layout.addLayout(header)
        layout.addWidget(self.title_input)
        layout.addWidget(self.day_row)
        layout.addWidget(self.date_row)
        layout.addWidget(self.color_row)
        layout.addWidget(self.description, 1)
        layout.addWidget(save, 0, Qt.AlignRight)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.toggle_kind_fields()

    def toggle_kind_fields(self) -> None:
        self.day_row.setVisible(not self.all_day_switch.checked)
        self.date_row.setVisible(self.all_day_switch.checked)

    def set_plan_color(self, color: str) -> None:
        self.selected_color = color
        self.refresh_color_buttons()

    def refresh_color_buttons(self) -> None:
        for index, button in enumerate(getattr(self, "color_buttons", [])):
            color = self.COLORS[index]
            border = "#ffffff" if color == self.selected_color else "transparent"
            button.setStyleSheet(f"QPushButton {{ background: {color}; border: 2px solid {border}; border-radius: 12px; }}")

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit, QDateEdit, QDateTimeEdit, QTimeEdit, QComboBox {{ background: {c['panel2']}; color: {c['text']}; "
            f"border: 1px solid {c['border']}; border-radius: 8px; padding: 8px 30px 8px 10px; }}"
            "QComboBox::drop-down { border: none; width: 28px; }"
            "QComboBox::down-arrow { image: none; width: 0; height: 0; }"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 6px; padding: 7px 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "color_label"):
            self.color_label.setStyleSheet(f"color: {c['muted']};")
        if hasattr(self, "all_day_switch"):
            self.all_day_switch.colors = c
            self.all_day_switch.update()
        for widget in getattr(self, "inputs", []):
            if isinstance(widget, QTextEdit):
                widget.setStyleSheet(
                    f"QTextEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
                    "border-radius: 10px; padding: 10px; }}"
                )
            else:
                widget.setStyleSheet(self.input_style())
        for button in getattr(self, "styled_buttons", []):
            button.setStyleSheet(self.button_style())
        self.refresh_color_buttons()
        self.update()

    def save_plan(self) -> None:
        title = self.title_input.text().strip()
        if not title:
            self.title_input.setFocus()
            return
        if self.all_day_switch.checked:
            start = QDateTime(self.start_date.date(), QTime(0, 0))
            end = QDateTime(self.end_date.date(), QTime(23, 59))
            if end < start:
                end = QDateTime(self.start_date.date(), QTime(23, 59))
        else:
            plan_date = QDate(self.plan_day.year, self.plan_day.month, self.plan_day.day)
            start = QDateTime(plan_date, self.start_time.time())
            end = QDateTime(plan_date, self.end_time.time())
        plan_data = {
            "id": self.plan.get("id") if self.plan else datetime.now().strftime("%Y%m%d%H%M%S%f"),
            "kind": "long" if self.all_day_switch.checked else "day",
            "title": title,
            "start": start.toString(Qt.ISODate),
            "end": end.toString(Qt.ISODate),
            "description": self.description.toPlainText().strip(),
            "color": self.selected_color,
        }
        if self.plan:
            self.app.update_plan(plan_data)
        else:
            self.app.add_plan(plan_data)
        self.close()

