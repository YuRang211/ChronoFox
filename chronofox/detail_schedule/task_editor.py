"""허브 할 일 섹션의 비모달 추가·수정 창.

독립 목록 창의 수명주기를 재사용하지 않고 ``TaskService``에 직접 저장한다. 따라서
허브를 열었다는 이유만으로 숨은 QWidget이나 날짜 변경 콜백이 생기지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from chronofox.core.app_constants import APP_NAME
from chronofox.core.todo_logic import TASK_PERIOD_CHOICES
from chronofox.ui.app_i18n import TrMixin
from chronofox.ui.app_theme import DANGER_COLOR
from chronofox.ui.app_ui import app_font, clear_layout
from chronofox.ui.app_widgets import ArrowComboBox, IconButton, RoundedWindow

if TYPE_CHECKING:
    from .window import DetailScheduleWindow


class TaskNotesEdit(QTextEdit):
    """포커스를 잃을 때만 메모를 커밋해 입력 중 목록 재구성을 막는다."""

    def __init__(self, initial: str, on_commit) -> None:
        super().__init__(initial)
        self._on_commit = on_commit
        self._committed = initial

    def focusOutEvent(self, event) -> None:
        text = self.toPlainText()
        if text != self._committed:
            self._committed = text
            self._on_commit(text)
        super().focusOutEvent(event)


@dataclass(frozen=True, slots=True)
class TaskFormDraft:
    """테마·언어 갱신 중 보존할 미저장 편집값."""

    text: str
    period: str
    list_name: str
    important: bool
    my_day: bool
    due_enabled: bool
    due_date: QDate
    notes: str


class TaskEditorWindow(TrMixin, RoundedWindow):
    """할 일을 추가하거나 수정하는 허브 소유 비모달 창."""

    NONE_PERIOD = ""

    def __init__(self, owner: DetailScheduleWindow, edit_task: dict | None = None) -> None:
        super().__init__(owner.app.dialog_colors())
        self.owner = owner
        self.app = owner.app
        self.edit_task = edit_task
        self.setWindowTitle(self.window_title_text())
        self.setWindowIcon(self.app.icon)
        anchor = owner.geometry()
        self.setGeometry(anchor.x() + 36, anchor.y() + 72, 360, 350)
        self.build_ui()

    def window_title_text(self) -> str:
        key = "todo.editor.title.edit" if self.edit_task else "todo.editor.title.add"
        fallback = f"{{app}} 해야 할 일 {'수정' if self.edit_task else '추가'}"
        return self.tr(key, fallback, app=self.tr("app.name", APP_NAME))

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
        title_fallback = "해야 할 일 수정" if self.edit_task else "해야 할 일 추가"
        self.header_title = QLabel(self.tr(title_key, title_fallback))
        self.header_title.setFont(app_font(13, QFont.Bold))
        close = IconButton("close", self.colors)
        close.setFixedSize(26, 24)
        close.clicked.connect(self.close)
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(close)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText(self.tr("todo.editor.text.placeholder", "할 일 입력"))
        if self.edit_task:
            self.text_input.setText(str(self.edit_task.get("text", "")))
        self.text_input.returnPressed.connect(self.add_task)

        self.period_combo = ArrowComboBox(c)
        self.period_combo.addItem(self.tr("todo.period.none", "반복 없음"), self.NONE_PERIOD)
        for key, label_key, fallback in TASK_PERIOD_CHOICES:
            self.period_combo.addItem(self.tr(label_key, fallback), key)
        initial_recurrence = (self.edit_task or {}).get("recurrence")
        initial_period = initial_recurrence.get("period") if initial_recurrence else self.NONE_PERIOD
        self.period_combo.setCurrentIndex(max(0, self.period_combo.findData(initial_period)))
        self.period_combo.setStyleSheet(self.combo_style())

        self.list_input = QLineEdit()
        self.list_input.setPlaceholderText(self.tr("todo.list.label", "목록"))
        stored_list_id = (self.edit_task or {}).get("list_id")
        if stored_list_id:
            self.list_input.setText(self.display_list_name_for(str(stored_list_id)))

        self.important_check = QCheckBox(self.tr("todo.filter.important", "중요"))
        self.important_check.setChecked(bool(self.edit_task and self.edit_task.get("important")))
        self.my_day_check = QCheckBox(self.tr("todo.editor.myday", "나의 하루에 추가"))
        self.my_day_check.setChecked(bool(self.edit_task and self.edit_task.get("my_day_date") == date.today().isoformat()))

        due_row = QHBoxLayout()
        self.due_check = QCheckBox(self.tr("todo.editor.due", "마감일"))
        self.due_date = QDateEdit()
        self.due_date.setCalendarPopup(True)
        self.due_date.setDisplayFormat("yyyy-MM-dd")
        self.due_date.setStyleSheet(self.date_style())
        due_value = self.edit_task.get("due") if self.edit_task else None
        if due_value:
            parsed = QDate.fromString(str(due_value), "yyyy-MM-dd")
            self.due_date.setDate(parsed if parsed.isValid() else QDate.currentDate())
            self.due_check.setChecked(True)
        else:
            self.due_date.setDate(QDate.currentDate())
        self.due_date.setEnabled(self.due_check.isChecked())
        self.due_check.toggled.connect(self.due_date.setEnabled)
        due_row.addWidget(self.due_check)
        due_row.addWidget(self.due_date, 1)

        self.notes_input = QLineEdit()
        self.notes_input.setPlaceholderText(self.tr("todo.editor.memo.placeholder", "메모"))
        if self.edit_task:
            self.notes_input.setText(str(self.edit_task.get("notes", "")))

        for line_edit in (self.text_input, self.list_input, self.notes_input):
            line_edit.setStyleSheet(self.input_style())
        for checkbox in (self.important_check, self.my_day_check, self.due_check):
            checkbox.setStyleSheet(self.checkbox_style())

        apply = QPushButton(self.tr("common.save", "저장") if self.edit_task else "+")
        apply.setFixedHeight(34)
        apply.clicked.connect(self.add_task)
        apply.setStyleSheet(self.button_style() if self.edit_task else self.plus_button_style())

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
            delete = QPushButton(self.tr("common.delete", "삭제"))
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

    def display_list_name_for(self, list_id: str) -> str:
        task_list = self.app.task_service.find_task_list(list_id)
        if task_list is not None:
            return str(task_list.get("name", ""))
        return self.tr("todo.list.unfiled", "미분류")

    def resolve_list_id(self, raw_name: str) -> str | None:
        name = raw_name.strip()
        if not name:
            return None
        for task_list in self.app.task_service.task_lists():
            if task_list.get("name") == name:
                return str(task_list.get("id")) or None
        created = self.app.task_service.add_task_list(name)
        return str(created.get("id")) if created else None

    def _resolve_recurrence(self, period: str | None) -> dict | None:
        if not period:
            return None
        if self.edit_task:
            existing = self.edit_task.get("recurrence")
            if existing and existing.get("period") == period:
                return existing
        return {"period": period}

    def add_task(self) -> None:
        text = self.text_input.text().strip()
        if not text:
            return
        due = self.due_date.date().toString("yyyy-MM-dd") if self.due_check.isChecked() else None
        my_day_date = date.today().isoformat() if self.my_day_check.isChecked() else None
        recurrence = self._resolve_recurrence(self.period_combo.currentData() or None)
        fields = {
            "text": text,
            "notes": self.notes_input.text().strip(),
            "due": due,
            "important": self.important_check.isChecked(),
            "my_day_date": my_day_date,
            "list_id": self.resolve_list_id(self.list_input.text()),
            "recurrence": recurrence,
        }
        if self.edit_task:
            updated = self.app.task_service.update_task(str(self.edit_task.get("id", "")), **fields)
            if updated is None:
                return
            self.owner.selected_task = updated
        else:
            created = self.app.task_service.add_task(**fields)
            if created is None:
                return
        self.close()

    def delete_task(self) -> None:
        if not self.edit_task:
            return
        task_id = str(self.edit_task.get("id", ""))
        self.owner.selected_task = None
        if self.app.task_service.delete_task(task_id):
            self.close()

    def form_draft(self) -> TaskFormDraft:
        return TaskFormDraft(
            text=self.text_input.text(),
            period=str(self.period_combo.currentData() or ""),
            list_name=self.list_input.text(),
            important=self.important_check.isChecked(),
            my_day=self.my_day_check.isChecked(),
            due_enabled=self.due_check.isChecked(),
            due_date=self.due_date.date(),
            notes=self.notes_input.text(),
        )

    def restore_form_draft(self, draft: TaskFormDraft) -> None:
        self.text_input.setText(draft.text)
        self.period_combo.setCurrentIndex(max(0, self.period_combo.findData(draft.period)))
        self.list_input.setText(draft.list_name)
        self.important_check.setChecked(draft.important)
        self.my_day_check.setChecked(draft.my_day)
        self.due_check.setChecked(draft.due_enabled)
        self.due_date.setDate(draft.due_date)
        self.due_date.setEnabled(draft.due_enabled)
        self.notes_input.setText(draft.notes)

    def apply_theme(self) -> None:
        draft = self.form_draft() if hasattr(self, "text_input") else None
        self.colors.update(self.app.dialog_colors())
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

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 8px; }}"
        )

    def checkbox_style(self) -> str:
        return f"QCheckBox {{ color: {self.colors['text']}; spacing: 8px; padding: 7px; }}"

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            "QComboBox::drop-down { border: none; width: 22px; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def date_style(self) -> str:
        c = self.colors
        return (
            f"QDateEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            "QDateEdit::drop-down { border: none; width: 20px; }"
        )

    def plus_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; font-size: 20px; font-weight: 700; padding-bottom: 2px; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def delete_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {DANGER_COLOR}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {DANGER_COLOR}; color: white; }}"
        )

    def closeEvent(self, event) -> None:
        if getattr(self.owner, "task_editor_window", None) is self:
            self.owner.task_editor_window = None
        super().closeEvent(event)
