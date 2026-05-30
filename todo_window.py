from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget

from app_constants import APP_NAME
from app_ui import add_soft_shadow, app_font, clear_layout, geometry_string, parse_geometry
from app_widgets import ArrowComboBox, RoundedWindow

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

class RepeatWindow(RoundedWindow):
    """반복되는 할 일의 완료 횟수와 경과 시간을 관리합니다."""

    PERIODS = [("daily", "매일"), ("weekly", "매주"), ("monthly", "매월"), ("yearly", "매년")]

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.add_window: AddRepeatTaskWindow | None = None
        self.period_keys = self.current_period_keys()
        self.setWindowTitle(f"{APP_NAME} 해야 할 일")
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
        self.search_input.setPlaceholderText("검색")
        self.search_input.setStyleSheet(self.input_style())
        self.search_input.textChanged.connect(self.refresh_all)
        add = QPushButton("+")
        self.add_button = add
        add.setFixedSize(38, 34)
        add.clicked.connect(self.open_add_task)
        add.setStyleSheet(self.plus_button_style())
        top_row.addWidget(self.search_input, 1)
        top_row.addWidget(add)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(self.list_style())
        add_soft_shadow(self.list_widget, c, blur=14, alpha=24)
        layout.addLayout(top_row)
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
        for button in getattr(self, "styled_buttons", []):
            button.setStyleSheet(self.button_style())
        if self.add_window and self.add_window.isVisible():
            self.add_window.apply_theme()
        self.update()

    def header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        title = QLabel("해야 할 일")
        title.setFont(app_font(15, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.button_style())
        self.styled_buttons.append(close)
        header.addWidget(title)
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
        return {period: self.current_key(period) for period, _label in self.PERIODS}

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
        return task

    def period_label(self, period: str) -> str:
        return dict(self.PERIODS).get(period, period)

    def all_tasks(self) -> list[tuple[str, dict]]:
        rows: list[tuple[str, dict]] = []
        for period, _label in self.PERIODS:
            for task in self.tasks(period):
                rows.append((period, task))
        return rows

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

    def add_task(self, period: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.tasks(period).append(
            {
                "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                "text": text,
                "done": "",
                "created": date.today().isoformat(),
                "done_count": 0,
                "counted_keys": [],
            }
        )
        self.app.save()
        self.refresh_all()

    def update_task(self, old_period: str, task: dict, new_period: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        self.normalize_task(task)
        task["text"] = text
        if old_period != new_period:
            self.tasks(old_period)[:] = [item for item in self.tasks(old_period) if item.get("id") != task.get("id")]
            self.tasks(new_period).append(task)
        self.app.save()
        self.refresh_all()

    def delete_task(self, period: str, task_id: str) -> None:
        self.tasks(period)[:] = [task for task in self.tasks(period) if task.get("id") != task_id]
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
            if query and query not in text.lower() and query not in self.period_label(period):
                continue
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 58))
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
            value, unit = days, "일"
        elif period == "weekly":
            value, unit = days // 7, "주"
        elif period == "monthly":
            value = max(0, (today.year - created.year) * 12 + today.month - created.month)
            unit = "개월"
        else:
            value, unit = max(0, today.year - created.year), "년"
        return f"{value}{unit} 지남"

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
        check.setChecked(self.task.get("done") == self.window.current_key(self.period))
        check.setStyleSheet(self.window.checkbox_style())
        check.toggled.connect(lambda checked: self.window.set_done(self.period, self.task, checked))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        title = QLabel(self.task.get("text", ""))
        title.setStyleSheet(f"QLabel {{ color: {c['text']}; background: transparent; font-weight: 600; }}")
        meta = QLabel(f"{self.window.elapsed_text(self.period, self.task)} · {int(self.task.get('done_count', 0))}회 완료")
        meta.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; }}")
        texts.addWidget(title)
        texts.addWidget(meta)

        badge = QLabel(self.window.period_label(self.period))
        badge.setAlignment(Qt.AlignCenter)
        badge.setFixedWidth(44)
        badge.setStyleSheet(
            f"QLabel {{ color: {c['muted']}; background: {c['panel2']}; border-radius: 8px; padding: 4px 6px; }}"
        )

        edit = QPushButton("수정")
        edit.setFixedSize(42, 28)
        edit.setStyleSheet(self.window.edit_button_style())
        edit.clicked.connect(lambda: self.window.open_edit_task(self.period, self.task))

        layout.addWidget(check)
        layout.addLayout(texts, 1)
        layout.addWidget(badge)
        layout.addWidget(edit)

class AddRepeatTaskWindow(RoundedWindow):
    """반복 할 일을 추가하거나 수정하는 작은 설정창입니다."""

    def __init__(self, repeat_window: RepeatWindow, edit_period: str | None = None, edit_task: dict | None = None) -> None:
        super().__init__(repeat_window.app.dialog_colors())
        self.repeat_window = repeat_window
        self.edit_period = edit_period
        self.edit_task = edit_task
        self.setWindowTitle(f"{APP_NAME} 해야 할 일 {'수정' if edit_task else '추가'}")
        self.setWindowIcon(repeat_window.app.icon)
        anchor = repeat_window.geometry()
        self.setGeometry(anchor.x() + 36, anchor.y() + 72, 320, 180)
        self.build_ui()

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
        title = QLabel("할 일 수정" if self.edit_task else "할 일 추가")
        title.setFont(app_font(13, QFont.Bold))
        close = QPushButton("x")
        close.setFixedSize(24, 24)
        close.clicked.connect(self.close)
        close.setStyleSheet(self.repeat_window.button_style())
        header.addWidget(title)
        header.addStretch()
        header.addWidget(close)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("할 일 입력")
        if self.edit_task:
            self.text_input.setText(self.edit_task.get("text", ""))
        self.text_input.setStyleSheet(self.repeat_window.input_style())
        self.text_input.returnPressed.connect(self.add_task)

        self.period_combo = ArrowComboBox(c)
        for key, label in RepeatWindow.PERIODS:
            self.period_combo.addItem(label, key)
        if self.edit_period:
            index = self.period_combo.findData(self.edit_period)
            self.period_combo.setCurrentIndex(max(0, index))
        self.period_combo.setStyleSheet(self.combo_style())

        apply = QPushButton("저장" if self.edit_task else "+")
        apply.setFixedHeight(34)
        apply.clicked.connect(self.add_task)
        apply.setStyleSheet(self.repeat_window.plus_button_style() if not self.edit_task else self.repeat_window.button_style())

        layout.addLayout(header)
        layout.addWidget(self.text_input)
        layout.addWidget(self.period_combo)
        if self.edit_task:
            buttons = QHBoxLayout()
            delete = QPushButton("삭제")
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
        self.colors.update(self.repeat_window.app.dialog_colors())
        self.build_ui()
        self.update()

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def delete_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: #d96f78; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 700; }}"
            "QPushButton:hover { background: #d96f78; color: white; }"
        )

    def add_task(self) -> None:
        if self.edit_task and self.edit_period:
            self.repeat_window.update_task(
                self.edit_period,
                self.edit_task,
                self.period_combo.currentData(),
                self.text_input.text(),
            )
        else:
            self.repeat_window.add_task(self.period_combo.currentData(), self.text_input.text())
        self.close()

    def delete_task(self) -> None:
        if self.edit_task and self.edit_period:
            self.repeat_window.delete_task(self.edit_period, str(self.edit_task.get("id", "")))
        self.close()

    def closeEvent(self, event) -> None:
        self.repeat_window.add_window = None
        super().closeEvent(event)

