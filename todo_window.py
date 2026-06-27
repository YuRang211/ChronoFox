from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QSize, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app_constants import APP_NAME
from app_i18n import translate
from app_ui import add_soft_shadow, app_font, clear_layout, geometry_string, parse_geometry
from app_widgets import ArrowComboBox, RoundedWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp


@dataclass(frozen=True, slots=True)
class RepeatTaskFormDraft:
    """Unsaved add/edit form state preserved while refreshing the theme."""

    text: str
    period: str
    list_name: str
    important: bool
    my_day: bool
    due_enabled: bool
    due_date: QDate
    notes: str


class RepeatWindow(RoundedWindow):
    """반복되는 할 일의 완료 횟수와 경과 시간을 관리합니다."""

    DEFAULT_LIST_NAME = "작업"
    PERIODS = [
        ("daily", "todo.period.daily", "매일"),
        ("weekly", "todo.period.weekly", "매주"),
        ("monthly", "todo.period.monthly", "매월"),
        ("yearly", "todo.period.yearly", "매년"),
    ]
    FILTERS = [
        ("all", "todo.filter.all", "전체"),
        ("myday", "todo.filter.myday", "나의 하루"),
        ("today", "todo.filter.today", "오늘"),
        ("important", "todo.filter.important", "중요"),
        ("completed", "todo.filter.completed", "완료됨"),
    ]

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.add_window: AddRepeatTaskWindow | None = None
        self.period_keys = self.current_period_keys()
        self.filter_mode = "all"
        self.list_filter = ""
        self.filter_buttons: dict[str, QPushButton] = {}
        self.setWindowTitle(self.tr("todo.window.title", f"{APP_NAME} 해야 할 일").format(app=self.app_display_name()))
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("repeat_geometry", "480x460"), (480, 460, 340, 160))
        self.setGeometry(x, y, width, height)
        self.build_ui()

    def build_ui(self) -> None:
        c = self.colors
        self.styled_buttons: list[QPushButton] = []
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(self.header())

        top_row = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("todo.search.placeholder", "검색"))
        self.search_input.setStyleSheet(self.input_style())
        self.search_input.textChanged.connect(self.refresh_all)
        add = QPushButton("+")
        self.add_button = add
        add.setFixedSize(38, 34)
        add.clicked.connect(self.open_add_task)
        add.setStyleSheet(self.plus_button_style())
        top_row.addWidget(self.search_input, 1)
        top_row.addWidget(add)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)
        self.filter_buttons = {}
        for key, label_key, fallback in self.FILTERS:
            label = self.tr(label_key, fallback)
            button = QPushButton(label)
            button.setCheckable(True)
            button.setChecked(key == self.filter_mode)
            button.clicked.connect(partial(self.set_filter, key))
            button.setStyleSheet(self.filter_button_style(key == self.filter_mode))
            self.filter_buttons[key] = button
            filter_row.addWidget(button)
        filter_row.addStretch()

        list_row = QHBoxLayout()
        self.list_label = QLabel(self.tr("todo.list.label", "목록"))
        self.list_label.setStyleSheet(f"color: {c['muted']};")
        self.list_combo = ArrowComboBox(c)
        self.list_combo.setStyleSheet(self.combo_style())
        self.list_combo.currentIndexChanged.connect(self.set_list_filter_from_combo)
        list_row.addWidget(self.list_label)
        list_row.addWidget(self.list_combo, 1)
        self.refresh_list_combo()

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(self.list_style())
        add_soft_shadow(self.list_widget, c, blur=14, alpha=24)
        layout.addLayout(top_row)
        layout.addLayout(filter_row)
        layout.addLayout(list_row)
        layout.addWidget(self.list_widget, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.refresh_all()
        if hasattr(self, "reset_check_timer"):
            self.reset_check_timer.stop()
            self.reset_check_timer.deleteLater()
        self.reset_check_timer = QTimer(self)
        self.reset_check_timer.setInterval(60000)
        self.reset_check_timer.timeout.connect(self.refresh_if_period_changed)
        self.reset_check_timer.start()

    def tr(self, key: str, fallback: str = "") -> str:
        return translate(self.app.config.get("language", "ko"), key, fallback)

    def app_display_name(self) -> str:
        return translate(self.app.config.get("language", "ko"), "app.name", APP_NAME)

    def apply_theme(self) -> None:
        self.colors.update(self.app.dialog_colors())
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        if hasattr(self, "search_input"):
            self.search_input.setStyleSheet(self.input_style())
        if hasattr(self, "add_button"):
            self.add_button.setStyleSheet(self.plus_button_style())
        if hasattr(self, "list_widget"):
            self.list_widget.setStyleSheet(self.list_style())
            self.refresh_all()
        for key, button in getattr(self, "filter_buttons", {}).items():
            button.setStyleSheet(self.filter_button_style(key == self.filter_mode))
        if hasattr(self, "list_combo"):
            self.list_combo.setStyleSheet(self.combo_style())
        for button in getattr(self, "styled_buttons", []):
            button.setStyleSheet(self.button_style())
        if self.add_window and self.add_window.isVisible():
            self.add_window.apply_theme()
        self.update()

    def apply_language(self) -> None:
        search_text = self.search_input.text() if hasattr(self, "search_input") else ""
        self.setWindowTitle(self.tr("todo.window.title", f"{APP_NAME} 해야 할 일").format(app=self.app_display_name()))
        self.build_ui()
        if hasattr(self, "search_input"):
            self.search_input.setText(search_text)
        if self.add_window and self.add_window.isVisible():
            self.add_window.apply_language()
        self.update()

    def header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        self.header_title = QLabel(self.tr("todo.title", "해야 할 일"))
        self.header_title.setFont(app_font(15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        self.styled_buttons.append(close)
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(close)
        return header

    def current_key(self, period: str) -> str:
        today = date.today()
        if period == "daily":
            return today.isoformat()
        if period == "weekly":
            year, week, _weekday = today.isocalendar()
            return f"{year}-W{week:02}"
        if period == "monthly":
            return today.strftime("%Y-%m")
        return today.strftime("%Y")

    def current_period_keys(self) -> dict[str, str]:
        return {period: self.current_key(period) for period, _label_key, _fallback in self.PERIODS}

    def refresh_if_period_changed(self) -> None:
        current = self.current_period_keys()
        if current != self.period_keys:
            self.period_keys = current
            self.refresh_all()

    def tasks(self, period: str) -> list[dict]:
        tasks = self.app.data.setdefault("recurring_tasks", {}).setdefault(period, [])
        return tasks

    def normalize_task(self, task: dict) -> dict:
        task.setdefault("id", datetime.now().strftime("%Y%m%d%H%M%S%f"))
        task.setdefault("text", "")
        task.setdefault("done", "")
        task.setdefault("created", date.today().isoformat())
        task.setdefault("done_count", 0)
        task.setdefault("counted_keys", [])
        task.setdefault("important", False)
        task.setdefault("due", "")
        task.setdefault("notes", "")
        task.setdefault("list_name", self.DEFAULT_LIST_NAME)
        task.setdefault("my_day", "")
        return task

    def period_label(self, period: str) -> str:
        labels = {key: self.tr(label_key, fallback) for key, label_key, fallback in self.PERIODS}
        return labels.get(period, period)

    def all_tasks(self) -> list[tuple[str, dict]]:
        rows: list[tuple[str, dict]] = []
        for period, _label_key, _fallback in self.PERIODS:
            for task in self.tasks(period):
                rows.append((period, task))
        return rows

    def task_lists(self) -> list[str]:
        names = {self.DEFAULT_LIST_NAME}
        for _period, task in self.all_tasks():
            self.normalize_task(task)
            name = str(task.get("list_name", "")).strip() or self.DEFAULT_LIST_NAME
            names.add(name)
        return sorted(names, key=lambda item: (item != self.DEFAULT_LIST_NAME, item.casefold()))

    def display_list_name(self, name: str) -> str:
        return self.tr("todo.list.default", "작업") if name == self.DEFAULT_LIST_NAME else name

    def storage_list_name(self, name: str) -> str:
        value = name.strip()
        default_display = self.display_list_name(self.DEFAULT_LIST_NAME)
        if not value or value == default_display:
            return self.DEFAULT_LIST_NAME
        return value

    def refresh_list_combo(self) -> None:
        if not hasattr(self, "list_combo"):
            return
        current = self.list_filter
        self.list_combo.blockSignals(True)
        self.list_combo.clear()
        self.list_combo.addItem(self.tr("todo.list.all", "모든 목록"), "")
        for name in self.task_lists():
            self.list_combo.addItem(self.display_list_name(name), name)
        index = self.list_combo.findData(current)
        self.list_combo.setCurrentIndex(max(0, index))
        self.list_combo.blockSignals(False)

    def set_list_filter_from_combo(self, _index: int) -> None:
        self.list_filter = self.list_combo.currentData() or ""
        self.refresh_all()

    def open_add_task(self) -> None:
        if self.add_window and self.add_window.isVisible():
            self.add_window.raise_()
            self.add_window.activateWindow()
            return
        self.add_window = AddRepeatTaskWindow(self)
        self.add_window.show()

    def open_edit_task(self, period: str, task: dict) -> None:
        if self.add_window and self.add_window.isVisible():
            self.add_window.close()
        self.add_window = AddRepeatTaskWindow(self, period, task)
        self.add_window.show()

    def add_task(
        self,
        period: str,
        text: str,
        due: str = "",
        important: bool = False,
        notes: str = "",
        list_name: str = DEFAULT_LIST_NAME,
        my_day: str = "",
    ) -> None:
        text = text.strip()
        if not text:
            return
        list_name = self.storage_list_name(list_name)
        self.tasks(period).append(
            {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "text": text,
                "done": "",
                "created": date.today().isoformat(),
                "done_count": 0,
                "counted_keys": [],
                "important": important,
                "due": due,
                "notes": notes.strip(),
                "list_name": list_name,
                "my_day": my_day,
            }
        )
        self.app.save()
        self.refresh_list_combo()
        self.refresh_all()

    def update_task(
        self,
        old_period: str,
        task: dict,
        new_period: str,
        text: str,
        due: str = "",
        important: bool = False,
        notes: str = "",
        list_name: str = DEFAULT_LIST_NAME,
        my_day: str = "",
    ) -> None:
        text = text.strip()
        if not text:
            return
        self.normalize_task(task)
        task["text"] = text
        task["due"] = due
        task["important"] = important
        task["notes"] = notes.strip()
        task["list_name"] = self.storage_list_name(list_name)
        task["my_day"] = my_day
        if old_period != new_period:
            self.tasks(old_period)[:] = [item for item in self.tasks(old_period) if item.get("id") != task.get("id")]
            self.tasks(new_period).append(task)
        self.app.save()
        self.refresh_list_combo()
        self.refresh_all()

    def delete_task(self, period: str, task_id: str) -> None:
        self.tasks(period)[:] = [task for task in self.tasks(period) if task.get("id") != task_id]
        self.app.save()
        self.refresh_list_combo()
        self.refresh_all()

    def set_filter(self, mode: str) -> None:
        self.filter_mode = mode
        for key, button in self.filter_buttons.items():
            button.setChecked(key == mode)
            button.setStyleSheet(self.filter_button_style(key == mode))
        self.refresh_all()

    def is_done(self, period: str, task: dict) -> bool:
        return task.get("done") == self.current_key(period)

    def is_today_task(self, period: str, task: dict) -> bool:
        today = date.today().isoformat()
        return task.get("due") == today or (period == "daily" and not self.is_done(period, task))

    def task_matches_filter(self, period: str, task: dict) -> bool:
        if self.list_filter and task.get("list_name", self.DEFAULT_LIST_NAME) != self.list_filter:
            return False
        if self.filter_mode == "today":
            return self.is_today_task(period, task)
        if self.filter_mode == "myday":
            return task.get("my_day") == date.today().isoformat()
        if self.filter_mode == "important":
            return bool(task.get("important"))
        if self.filter_mode == "completed":
            return self.is_done(period, task)
        return True

    def toggle_important(self, task: dict) -> None:
        self.normalize_task(task)
        task["important"] = not bool(task.get("important"))
        self.app.save()
        self.refresh_all()

    def toggle_my_day(self, task: dict) -> None:
        self.normalize_task(task)
        today = date.today().isoformat()
        task["my_day"] = "" if task.get("my_day") == today else today
        self.app.save()
        self.refresh_all()

    def refresh_all(self) -> None:
        self.list_widget.clear()
        query = self.search_input.text().strip().lower()
        changed = False
        for period, task in self.all_tasks():
            before = dict(task)
            self.normalize_task(task)
            changed = changed or task != before
            text = task.get("text", "")
            list_name = task.get("list_name", "")
            searchable = " ".join(
                [text, task.get("notes", ""), task.get("due", ""), list_name, self.display_list_name(list_name), self.period_label(period)]
            ).lower()
            if query and query not in searchable:
                continue
            if not self.task_matches_filter(period, task):
                continue
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 66))
            self.list_widget.addItem(item)
            row = RepeatTaskRow(self, period, task)
            self.list_widget.setItemWidget(item, row)
        if changed:
            self.app.save()

    def set_done(self, period: str, task: dict, checked: bool) -> None:
        task = self.normalize_task(task)
        current = self.current_key(period)
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
        self.app.save()
        self.refresh_all()

    def elapsed_text(self, period: str, task: dict) -> str:
        try:
            created = date.fromisoformat(task.get("created", ""))
        except ValueError:
            created = date.today()
        today = date.today()
        days = max(0, (today - created).days)
        if period == "daily":
            value, unit = days, self.elapsed_unit("day", days)
        elif period == "weekly":
            value = days // 7
            unit = self.elapsed_unit("week", value)
        elif period == "monthly":
            value = max(0, (today.year - created.year) * 12 + today.month - created.month)
            unit = self.elapsed_unit("month", value)
        else:
            value = max(0, today.year - created.year)
            unit = self.elapsed_unit("year", value)
        return self.tr("todo.elapsed.format", "{value}{unit} 지남").format(value=value, unit=unit)

    def elapsed_unit(self, unit: str, value: int) -> str:
        quantity = "one" if value == 1 else "many"
        return self.tr(f"todo.elapsed.unit.{unit}.{quantity}", unit)

    def list_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 6px; outline: none; }}"
            f"QListWidget::item:selected {{ background: {c['panel2']}; border-radius: 6px; }}"
        )

    def checkbox_style(self) -> str:
        c = self.colors
        return f"QCheckBox {{ color: {c['text']}; spacing: 8px; padding: 7px; }}"

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 8px; }}"
        )

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def plus_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; font-size: 20px; font-weight: 700; padding-bottom: 2px; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def edit_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 9px; font-size: 11px; font-weight: 700; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {c['border']}; color: {c['text']}; }}"
        )

    def filter_button_style(self, active: bool = False) -> str:
        c = self.colors
        background = c["accent"] if active else c["panel2"]
        color = "white" if active else c["muted"]
        border = c["accent"] if active else c["border"]
        return (
            f"QPushButton {{ background: {background}; color: {color}; border: 1px solid {border}; "
            "border-radius: 9px; padding: 6px 10px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['border']}; color: {c['text']}; }}"
        )

    def star_button_style(self, active: bool = False) -> str:
        c = self.colors
        color = "#d9a441" if active else c["muted"]
        return (
            f"QPushButton {{ background: transparent; color: {color}; border: none; "
            "font-size: 18px; font-weight: 800; padding: 0; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def closeEvent(self, event) -> None:
        self.app.config["repeat_geometry"] = geometry_string(self)
        self.app.save()
        self.app.repeat_window = None
        super().closeEvent(event)

class RepeatTaskRow(QWidget):
    """반복 할 일 한 줄입니다."""

    def __init__(self, window: RepeatWindow, period: str, task: dict) -> None:
        super().__init__()
        self.window = window
        self.period = period
        self.task = task
        self.build_ui()

    def build_ui(self) -> None:
        c = self.window.colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        check = QCheckBox()
        check.setChecked(self.window.is_done(self.period, self.task))
        check.setStyleSheet(self.window.checkbox_style())
        check.toggled.connect(partial(self.window.set_done, self.period, self.task))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        title = QLabel(self.task.get("text", ""))
        title.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-weight: 600; }}")
        list_name = str(self.task.get("list_name", RepeatWindow.DEFAULT_LIST_NAME)).strip() or RepeatWindow.DEFAULT_LIST_NAME
        meta_parts = [self.window.display_list_name(list_name), self.window.period_label(self.period), self.window.elapsed_text(self.period, self.task)]
        if self.task.get("due"):
            meta_parts.append(self.window.tr("todo.meta.due", "마감 {date}").format(date=self.task.get("due")))
        if self.task.get("my_day") == date.today().isoformat():
            meta_parts.append(self.window.tr("todo.meta.myday", "나의 하루"))
        meta_parts.append(self.window.tr("todo.meta.completed_count", "{count}회 완료").format(count=int(self.task.get("done_count", 0))))
        if self.task.get("notes"):
            meta_parts.append(str(self.task.get("notes"))[:24])
        meta = QLabel(" · ".join(meta_parts))
        meta.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; }}")
        texts.addWidget(title)
        texts.addWidget(meta)

        star = QPushButton("★" if self.task.get("important") else "☆")
        star.setFixedSize(28, 28)
        star.setStyleSheet(self.window.star_button_style(bool(self.task.get("important"))))
        star.clicked.connect(partial(self.window.toggle_important, self.task))

        my_day = QPushButton(self.window.tr("todo.action.today", "오늘"))
        my_day.setFixedSize(42, 28)
        my_day.setStyleSheet(self.window.edit_button_style())
        my_day.clicked.connect(partial(self.window.toggle_my_day, self.task))

        edit = QPushButton(self.window.tr("common.edit", "수정"))
        edit.setFixedSize(42, 28)
        edit.setStyleSheet(self.window.edit_button_style())
        edit.clicked.connect(partial(self.window.open_edit_task, self.period, self.task))

        layout.addWidget(check)
        layout.addLayout(texts, 1)
        layout.addWidget(star)
        layout.addWidget(my_day)
        layout.addWidget(edit)

class AddRepeatTaskWindow(RoundedWindow):
    """반복 할 일을 추가하거나 수정하는 작은 설정창입니다."""

    def __init__(self, repeat_window: RepeatWindow, edit_period: str | None = None, edit_task: dict | None = None) -> None:
        super().__init__(repeat_window.app.dialog_colors())
        self.repeat_window = repeat_window
        self.edit_period = edit_period
        self.edit_task = edit_task
        self.setWindowTitle(self.window_title_text())
        self.setWindowIcon(repeat_window.app.icon)
        anchor = repeat_window.geometry()
        self.setGeometry(anchor.x() + 36, anchor.y() + 72, 360, 350)
        self.build_ui()

    def window_title_text(self) -> str:
        key = "todo.editor.title.edit" if self.edit_task else "todo.editor.title.add"
        fallback = f"{APP_NAME} 해야 할 일 {'수정' if self.edit_task else '추가'}"
        return self.repeat_window.tr(key, fallback).format(app=self.repeat_window.app_display_name())

    def build_ui(self) -> None:
        c = self.colors
        existing = self.layout()
        if existing is None:
            layout = QVBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title_key = "todo.editor.heading.edit" if self.edit_task else "todo.editor.heading.add"
        title_fallback = "할 일 수정" if self.edit_task else "할 일 추가"
        self.header_title = QLabel(self.repeat_window.tr(title_key, title_fallback))
        self.header_title.setFont(app_font(13, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.repeat_window.button_style())
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(close)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText(self.repeat_window.tr("todo.editor.text.placeholder", "할 일 입력"))
        if self.edit_task:
            self.text_input.setText(self.edit_task.get("text", ""))
        self.text_input.setStyleSheet(self.repeat_window.input_style())
        self.text_input.returnPressed.connect(self.add_task)

        self.period_combo = ArrowComboBox(c)
        for key, label_key, fallback in RepeatWindow.PERIODS:
            self.period_combo.addItem(self.repeat_window.tr(label_key, fallback), key)
        if self.edit_period:
            index = self.period_combo.findData(self.edit_period)
            self.period_combo.setCurrentIndex(max(0, index))
        self.period_combo.setStyleSheet(self.combo_style())

        self.list_input = QLineEdit()
        self.list_input.setPlaceholderText(self.repeat_window.tr("todo.list.label", "목록"))
        stored_list_name = (self.edit_task or {}).get("list_name", RepeatWindow.DEFAULT_LIST_NAME)
        self.list_input.setText(self.repeat_window.display_list_name(str(stored_list_name).strip() or RepeatWindow.DEFAULT_LIST_NAME))
        self.list_input.setStyleSheet(self.repeat_window.input_style())

        self.important_check = QCheckBox(self.repeat_window.tr("todo.filter.important", "중요"))
        self.important_check.setChecked(bool(self.edit_task and self.edit_task.get("important")))
        self.important_check.setStyleSheet(self.repeat_window.checkbox_style())

        self.my_day_check = QCheckBox(self.repeat_window.tr("todo.editor.myday", "나의 하루에 추가"))
        self.my_day_check.setChecked(bool(self.edit_task and self.edit_task.get("my_day") == date.today().isoformat()))
        self.my_day_check.setStyleSheet(self.repeat_window.checkbox_style())

        due_row = QHBoxLayout()
        self.due_check = QCheckBox(self.repeat_window.tr("todo.editor.due", "마감일"))
        self.due_check.setStyleSheet(self.repeat_window.checkbox_style())
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("yyyy-MM-dd")
        self.due_date.setStyleSheet(self.date_style())
        due_value = self.edit_task.get("due", "") if self.edit_task else ""
        if due_value:
            parsed = QDate.fromString(due_value, "yyyy-MM-dd")
            self.due_date.setDate(parsed if parsed.isValid() else QDate.currentDate())
            self.due_check.setChecked(True)
        else:
            self.due_date.setDate(QDate.currentDate())
        self.due_date.setEnabled(self.due_check.isChecked())
        self.due_check.toggled.connect(self.due_date.setEnabled)
        due_row.addWidget(self.due_check)
        due_row.addWidget(self.due_date, 1)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText(self.repeat_window.tr("todo.editor.memo.placeholder", "메모"))
        if self.edit_task:
            self.notes_input.setText(self.edit_task.get("notes", ""))
        self.notes_input.setStyleSheet(self.repeat_window.input_style())

        apply = QPushButton(self.repeat_window.tr("common.save", "저장") if self.edit_task else "+")
        apply.setFixedHeight(34)
        apply.clicked.connect(self.add_task)
        apply.setStyleSheet(self.repeat_window.plus_button_style() if not self.edit_task else self.repeat_window.button_style())

        layout.addLayout(header)
        layout.addWidget(self.text_input)
        layout.addWidget(self.period_combo)
        layout.addWidget(self.list_input)
        layout.addWidget(self.important_check)
        layout.addWidget(self.my_day_check)
        layout.addLayout(due_row)
        layout.addWidget(self.notes_input)
        if self.edit_task:
            buttons = QHBoxLayout()
            delete = QPushButton(self.repeat_window.tr("common.delete", "삭제"))
            delete.setFixedHeight(34)
            delete.clicked.connect(self.delete_task)
            delete.setStyleSheet(self.delete_button_style())
            buttons.addWidget(delete)
            buttons.addWidget(apply)
            layout.addLayout(buttons)
        else:
            layout.addWidget(apply)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.text_input.setFocus()

    def apply_theme(self) -> None:
        draft = self.form_draft() if hasattr(self, "text_input") else None
        self.colors.update(self.repeat_window.app.dialog_colors())
        self.build_ui()
        if draft is not None:
            self.restore_form_draft(draft)
        self.update()

    def apply_language(self) -> None:
        draft = self.form_draft() if hasattr(self, "text_input") else None
        self.setWindowTitle(self.window_title_text())
        self.build_ui()
        if draft is not None:
            self.restore_form_draft(draft)
        self.update()

    def form_draft(self) -> RepeatTaskFormDraft:
        return RepeatTaskFormDraft(
            text=self.text_input.text(),
            period=str(self.period_combo.currentData() or ""),
            list_name=self.list_input.text(),
            important=self.important_check.isChecked(),
            my_day=self.my_day_check.isChecked(),
            due_enabled=self.due_check.isChecked(),
            due_date=self.due_date.date(),
            notes=self.notes_input.text(),
        )

    def restore_form_draft(self, draft: RepeatTaskFormDraft) -> None:
        self.text_input.setText(draft.text)
        period_index = self.period_combo.findData(draft.period)
        self.period_combo.setCurrentIndex(max(0, period_index))
        self.list_input.setText(draft.list_name)
        self.important_check.setChecked(draft.important)
        self.my_day_check.setChecked(draft.my_day)
        self.due_check.setChecked(draft.due_enabled)
        self.due_date.setDate(draft.due_date)
        self.due_date.setEnabled(draft.due_enabled)
        self.notes_input.setText(draft.notes)

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def date_style(self) -> str:
        c = self.colors
        return (
            f"QDateEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QDateEdit::drop-down {{ border: none; width: 20px; }}"
        )

    def delete_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: #d96f78; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 700; }}"
            "QPushButton:hover { background: #d96f78; color: white; }"
        )

    def add_task(self) -> None:
        due = self.due_date.date().toString("yyyy-MM-dd") if self.due_check.isChecked() else ""
        important = self.important_check.isChecked()
        my_day = date.today().isoformat() if self.my_day_check.isChecked() else ""
        notes = self.notes_input.text()
        list_name = self.list_input.text()
        if self.edit_task and self.edit_period:
            self.repeat_window.update_task(
                self.edit_period,
                self.edit_task,
                self.period_combo.currentData(),
                self.text_input.text(),
                due,
                important,
                notes,
                list_name,
                my_day,
            )
        else:
            self.repeat_window.add_task(
                self.period_combo.currentData(),
                self.text_input.text(),
                due,
                important,
                notes,
                list_name,
                my_day,
            )
        self.close()

    def delete_task(self) -> None:
        if self.edit_task and self.edit_period:
            self.repeat_window.delete_task(self.edit_period, str(self.edit_task.get("id", "")))
        self.close()

    def closeEvent(self, event) -> None:
        self.repeat_window.add_window = None
        super().closeEvent(event)

