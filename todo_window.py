"""반복 작업(할 일) 목록 창 RepeatWindow와 작업 추가/편집 창 AddRepeatTaskWindow를 구현하는 모듈."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QSize, Qt, QTimer
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app_constants import APP_NAME, SEARCH_DEBOUNCE_MS
from app_i18n import TrMixin, translate
from app_theme import DANGER_COLOR, IMPORTANT_STAR_COLOR
from app_ui import add_soft_shadow, app_font, clear_layout, geometry_string, meta_segments_html, parse_geometry
from app_widgets import ArrowComboBox, IconButton, RoundedWindow
from todo_logic import (
    classify_and_sort,
    compute_streak,
    days_until,
    last_completed_key,
    normalize_step,
    period_key,
    reset_steps_for_period,
    steps_progress,
)

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp

# D3: 완료 상태/연속 표시에 쓰이는 주기별 i18n 키+한국어 폴백. 관리 탭(tasks_section.py)도
# RepeatWindow.task_meta_text()를 그대로 호출해 이 표를 공유한다(공통 note).
_META_DONE_KEYS = {
    "daily": ("todo.meta.done.daily", "오늘 완료"),
    "weekly": ("todo.meta.done.weekly", "이번 주 완료"),
    "monthly": ("todo.meta.done.monthly", "이번 달 완료"),
    "yearly": ("todo.meta.done.yearly", "올해 완료"),
}
_META_STREAK_KEYS = {
    "daily": ("todo.meta.streak.daily", "연속 {n}일"),
    "weekly": ("todo.meta.streak.weekly", "연속 {n}주"),
    "monthly": ("todo.meta.streak.monthly", "연속 {n}개월"),
    "yearly": ("todo.meta.streak.yearly", "연속 {n}년"),
}


class TaskNotesEdit(QTextEdit):
    """D6 메모 편집 표면 — 타이핑 중마다 커밋(전체 목록 재구성)하면 포커스/커서가
    끊기므로, 포커스를 잃을 때만(focus-out) 콜백을 호출한다. RepeatWindow 아코디언과
    관리 탭 상세 패널이 함께 쓴다."""

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


class RepeatWindow(TrMixin, RoundedWindow):
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
        # D4: 완료됨 섹션 접힘 상태는 세션 동안만 유지한다(기본 접힘).
        self.done_collapsed = True
        # D6: 아코디언(인라인 상세 편집)으로 펼쳐진 작업 id. 세션 동안만 유지, 최대 1개.
        self.expanded_task_id: str = ""
        # PERF1: 검색 입력은 SearchWindow와 같은 패턴으로 디바운스한다 — 키 입력마다
        # 전체 행 재구성을 하지 않는다. 타이머는 build_ui 재실행(테마/언어 변경)과
        # 무관하게 1개만 유지되도록 __init__에서 만든다.
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(SEARCH_DEBOUNCE_MS)
        self.search_timer.timeout.connect(self.refresh_all)
        self.setWindowTitle(self.tr("todo.window.title", f"{APP_NAME} 해야 할 일").format(app=self.app_display_name()))
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("repeat_geometry", "480x460"), (480, 460, 340, 160))
        self.setGeometry(x, y, width, height)
        self.build_ui()
        # F2: 60초 폴링 대신 스케줄러의 day_changed 구독으로 자정 롤오버를 1초 내에 반영한다.
        scheduler = getattr(app, "scheduler", None)
        if scheduler is not None:
            scheduler.on_day_changed.append(self.refresh_if_period_changed)

    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
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
        self.search_input.textChanged.connect(self.queue_refresh_all)
        add = QPushButton("+")
        self.add_button = add
        add.setFixedSize(38, 34)
        add.clicked.connect(self.open_add_task)
        add.setStyleSheet(self.plus_button_style())
        add.setToolTip(self.tr("todo.add.tooltip", "해야 할 일 추가"))
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

        # D2: 인라인 빠른 추가 — Enter로 저장하고 입력창은 비운 채 포커스를 유지해
        # 연속으로 여러 개를 추가할 수 있게 한다. 기존 + 버튼(상세 편집 창)은 그대로 둔다.
        self.quick_add_input = QLineEdit()
        self.quick_add_input.setPlaceholderText(self.tr("todo.quickadd.placeholder", "할 일 추가 — Enter로 저장"))
        self.quick_add_input.setStyleSheet(self.input_style())
        self.quick_add_input.returnPressed.connect(self.quick_add_task)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(self.list_style())
        add_soft_shadow(self.list_widget, c, blur=14, alpha=24)
        layout.addLayout(top_row)
        layout.addLayout(filter_row)
        layout.addLayout(list_row)
        layout.addWidget(self.quick_add_input)
        layout.addWidget(self.list_widget, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.refresh_all()

    def quick_add_task(self) -> None:
        """빠른 추가 입력창에서 Enter로 새 작업을 추가합니다(D2). 빈 입력은 무시하고,
        추가에 성공하면 입력창을 비운 채 포커스를 유지해 연속 추가를 돕는다."""
        text = self.quick_add_input.text().strip()
        if not text:
            return
        self.add_task("daily", text)
        self.quick_add_input.clear()
        self.quick_add_input.setFocus()

    def app_display_name(self) -> str:
        """현재 언어에 맞는 앱 표시 이름을 반환합니다."""
        return translate(self.app.store.get("language", "ko"), "app.name", APP_NAME)

    def apply_theme(self) -> None:
        """현재 테마 색상을 위젯 스타일에 다시 적용합니다."""
        self.colors.update(self.app.dialog_colors())
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        if hasattr(self, "search_input"):
            self.search_input.setStyleSheet(self.input_style())
        if hasattr(self, "add_button"):
            self.add_button.setStyleSheet(self.plus_button_style())
        if hasattr(self, "quick_add_input"):
            self.quick_add_input.setStyleSheet(self.input_style())
        if hasattr(self, "list_widget"):
            self.list_widget.setStyleSheet(self.list_style())
            self.refresh_all()
        for key, button in getattr(self, "filter_buttons", {}).items():
            button.setStyleSheet(self.filter_button_style(key == self.filter_mode))
        if hasattr(self, "list_combo"):
            self.list_combo.setStyleSheet(self.combo_style())
        for button in getattr(self, "styled_buttons", []):
            button.setStyleSheet(self.button_style())
        if hasattr(self, "header_close"):
            self.header_close.refresh_style()
            self.header_close.update()
        if self.add_window and self.add_window.isVisible():
            self.add_window.apply_theme()
        self.update()

    def apply_language(self) -> None:
        """현재 언어 설정에 맞춰 화면 텍스트를 다시 그립니다."""
        search_text = self.search_input.text() if hasattr(self, "search_input") else ""
        self.setWindowTitle(self.tr("todo.window.title", f"{APP_NAME} 해야 할 일").format(app=self.app_display_name()))
        self.build_ui()
        if hasattr(self, "search_input"):
            self.search_input.setText(search_text)
        if self.add_window and self.add_window.isVisible():
            self.add_window.apply_language()
        self.update()

    def header(self) -> QHBoxLayout:
        """창 상단 헤더 위젯을 만듭니다."""
        header = QHBoxLayout()
        self.header_title = QLabel(self.tr("todo.title", "해야 할 일"))
        self.header_title.setFont(app_font(15, QFont.Bold))
        close = IconButton("close", self.colors)
        close.setFixedSize(26, 24)
        close.clicked.connect(self.close)
        self.header_close = close
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(close)
        return header

    def current_key(self, period: str) -> str:
        """현재 반복 주기 키(예: 오늘 날짜/이번 주 등)를 반환합니다."""
        return period_key(period, date.today())

    def current_period_keys(self) -> dict[str, str]:
        """현재 및 인접 주기의 키 목록을 반환합니다."""
        return {period: self.current_key(period) for period, _label_key, _fallback in self.PERIODS}

    def refresh_if_period_changed(self) -> None:
        """주기가 바뀌었으면 화면을 다시 그립니다."""
        current = self.current_period_keys()
        if current != self.period_keys:
            self.period_keys = current
            self.refresh_all()

    def notify_data_changed(self) -> None:
        """다른 곳(세부 일정 창의 할 일 섹션 등)에 임베드된 할 일 목록도 함께
        갱신되도록 store 구독자에게 알립니다 (S4/M6/D9 — 이전에는
        app.refresh_detail_window()를 직접 호출하는 수동 fanout이었다)."""
        store = getattr(self.app, "store", None)
        if store is not None:
            store.notify("tasks")

    def tasks(self, period: str) -> list[dict]:
        """현재 필터/주기에 해당하는 작업 목록을 반환합니다."""
        tasks = self.app.store.recurring_tasks().setdefault(period, [])
        return tasks

    def normalize_task(self, task: dict) -> dict:
        """작업 dict에 누락된 기본 필드를 채웁니다."""
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
        # D7/D8 — additive, schema_version 무변경(D9). steps는 setdefault로 채우고 각
        # 항목도 정규화한다. order는 개별 setdefault가 아니라 ensure_task_order()가
        # 목록 내 위치를 기준으로 일괄 채운다(리스트 인덱스가 필요해서 여기서는 못 한다).
        task.setdefault("steps", [])
        for step in task["steps"]:
            normalize_step(step)
        return task

    def ensure_task_order(self) -> bool:
        """order 필드가 없는 작업에 현재 저장 순서(index)를 기본값으로 채웁니다(D8, additive).

        반환값은 무언가 채워졌는지 여부(호출부의 저장 트리거용)다.
        """
        changed = False
        for period, _label_key, _fallback in self.PERIODS:
            for index, task in enumerate(self.tasks(period)):
                order = task.get("order")
                if not isinstance(order, int) or isinstance(order, bool):
                    task["order"] = index
                    changed = True
        return changed

    def period_label(self, period: str) -> str:
        """반복 주기(daily/weekly/monthly/yearly)를 화면용 라벨로 변환합니다."""
        labels = {key: self.tr(label_key, fallback) for key, label_key, fallback in self.PERIODS}
        return labels.get(period, period)

    def all_tasks(self) -> list[tuple[str, dict]]:
        """모든 주기의 작업을 하나의 목록으로 반환합니다."""
        rows: list[tuple[str, dict]] = []
        for period, _label_key, _fallback in self.PERIODS:
            for task in self.tasks(period):
                rows.append((period, task))
        return rows

    def task_lists(self) -> list[str]:
        """존재하는 작업 목록(리스트) 이름들을 반환합니다."""
        names = {self.DEFAULT_LIST_NAME}
        for _period, task in self.all_tasks():
            self.normalize_task(task)
            name = str(task.get("list_name", "")).strip() or self.DEFAULT_LIST_NAME
            names.add(name)
        return sorted(names, key=lambda item: (item != self.DEFAULT_LIST_NAME, item.casefold()))

    def display_list_name(self, name: str) -> str:
        """목록 이름을 화면 표시용 문자열로 변환합니다."""
        return self.tr("todo.list.default", "작업") if name == self.DEFAULT_LIST_NAME else name

    def storage_list_name(self, name: str) -> str:
        """화면 표시용 목록 이름을 저장용 값으로 변환합니다."""
        value = name.strip()
        default_display = self.display_list_name(self.DEFAULT_LIST_NAME)
        if not value or value == default_display:
            return self.DEFAULT_LIST_NAME
        return value

    def refresh_list_combo(self) -> None:
        """목록 선택 콤보박스를 현재 목록들로 채웁니다."""
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
        """콤보박스 선택값으로 목록 필터를 설정합니다."""
        self.list_filter = self.list_combo.currentData() or ""
        self.refresh_all()

    def open_add_task(self) -> None:
        """새 작업 추가 창을 엽니다."""
        if self.add_window and self.add_window.isVisible():
            self.add_window.raise_()
            self.add_window.activateWindow()
            return
        self.add_window = AddRepeatTaskWindow(self)
        self.add_window.show()

    def open_edit_task(self, period: str, task: dict) -> None:
        """기존 작업 편집 창을 엽니다."""
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
        """새 작업을 추가하고 저장합니다."""
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
        self.notify_data_changed()

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
        """기존 작업 내용을 수정하고 저장합니다."""
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
        self.notify_data_changed()

    def delete_task(self, period: str, task_id: str) -> None:
        """작업을 삭제하고 저장합니다."""
        self.tasks(period)[:] = [task for task in self.tasks(period) if task.get("id") != task_id]
        self.app.save()
        self.refresh_list_combo()
        self.refresh_all()
        self.notify_data_changed()

    def set_filter(self, mode: str) -> None:
        """작업 목록 필터를 설정합니다."""
        self.filter_mode = mode
        for key, button in self.filter_buttons.items():
            button.setChecked(key == mode)
            button.setStyleSheet(self.filter_button_style(key == mode))
        self.refresh_all()

    def is_done(self, period: str, task: dict) -> bool:
        """작업이 완료 상태인지 반환합니다."""
        return task.get("done") == self.current_key(period)

    def task_streak(self, period: str, task: dict) -> int:
        """counted_keys 기반으로 현재까지의 연속 완료 횟수를 반환합니다(D3)."""
        return compute_streak(period, task.get("counted_keys", []), self.current_key(period))

    def task_meta_text(self, period: str, task: dict) -> list[tuple[str, str]]:
        """행 메타라인 세그먼트 목록을 만듭니다(D3, AUDIT-D1 수정).

        각 항목은 `(text, role)` 튜플이며 role은 "normal" 또는 "danger"다.
        "아직 안 함"과 마감이 지난 "n일 지남"만 danger, 주기/연속/D-n/단계 같은
        나머지 정보는 normal로 남는다 — 예전에는 미완료 시 라인 전체가 danger
        색이라 스트릭·단계 같은 긍정 정보까지 붉게 칠해졌다(감사 D1).
        RepeatWindow(목록 창)와 detail_schedule의 관리 탭이 이 메서드 하나를 공유한다
        (공통 note — 행 위젯 자체는 컨테이너가 달라 완전 통합 대신 이 빌더만 공유).
        호출부는 `app_ui.meta_segments_html()`로 세그먼트를 rich-text로 합친다.
        """
        done = self.is_done(period, task)
        segments: list[tuple[str, str]] = [(self.period_label(period), "normal")]
        if done:
            status_key, status_fallback = _META_DONE_KEYS.get(period, ("todo.meta.done.daily", "완료"))
            segments.append((self.tr(status_key, status_fallback), "normal"))
        else:
            segments.append((self.tr("todo.meta.not_done", "아직 안 함"), "danger"))
        streak = self.task_streak(period, task)
        if streak >= 2:
            streak_key, streak_fallback = _META_STREAK_KEYS.get(period, ("todo.meta.streak.daily", "연속 {n}"))
            segments.append((self.tr(streak_key, streak_fallback, n=streak), "normal"))
        due = str(task.get("due", "") or "")
        if due:
            delta = days_until(due, date.today())
            if delta is not None:
                if delta < 0:
                    segments.append((self.tr("todo.meta.overdue", "{n}일 지남", n=abs(delta)), "danger"))
                else:
                    segments.append((self.tr("todo.meta.due", "D-{n}", n=delta), "normal"))
        # D7: 단계가 있으면 "단계 완료/전체"를 메타라인 끝에 덧붙인다(하위 호환 확장 —
        # steps가 없는 기존 작업은 total_steps=0이라 아무 것도 추가되지 않는다).
        done_steps, total_steps = steps_progress(task.get("steps") or [])
        if total_steps > 0:
            segments.append(
                (self.tr("todo.meta.steps", "단계 {done}/{total}", done=done_steps, total=total_steps), "normal")
            )
        return segments

    def is_today_task(self, period: str, task: dict) -> bool:
        """오늘 마감/등록된 작업인지 반환합니다."""
        today = date.today().isoformat()
        return task.get("due") == today or (period == "daily" and not self.is_done(period, task))

    def task_matches_filter(self, period: str, task: dict) -> bool:
        """작업이 현재 필터 조건에 맞는지 반환합니다."""
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
        """작업의 중요 표시를 토글합니다."""
        self.normalize_task(task)
        task["important"] = not bool(task.get("important"))
        self.app.save()
        self.refresh_all()

    def toggle_my_day(self, task: dict) -> None:
        """작업의 '내 하루' 포함 여부를 토글합니다."""
        self.normalize_task(task)
        today = date.today().isoformat()
        task["my_day"] = "" if task.get("my_day") == today else today
        self.app.save()
        self.refresh_all()

    def set_task_field(self, period: str, task: dict, **fields) -> None:
        """작업의 일부 필드만 갱신하고 저장합니다(D6 — 상세 패널/아코디언의 부분 편집용).

        주기(period)는 여기서 바꾸지 않는다 — 주기 변경은 기존 AddRepeatTaskWindow
        편집 흐름을 그대로 쓴다. text가 비어 있으면(공백만 입력) 무시한다.
        """
        self.normalize_task(task)
        if "text" in fields:
            text = str(fields["text"]).strip()
            if not text:
                return
            fields["text"] = text
        if "notes" in fields:
            fields["notes"] = str(fields["notes"]).strip()
        task.update(fields)
        self.app.save()
        self.refresh_all()
        self.notify_data_changed()

    def add_step(self, task: dict, text: str) -> bool:
        """작업에 단계(step)를 추가합니다(D7). 빈 입력은 무시하고 False를 반환합니다."""
        text = text.strip()
        if not text:
            return False
        self.normalize_task(task)
        task.setdefault("steps", []).append(
            {"id": datetime.now().strftime("%Y%m%d%H%M%S%f"), "text": text, "done": False}
        )
        self.app.save()
        self.refresh_all()
        self.notify_data_changed()
        return True

    def toggle_step(self, task: dict, step_id: str, checked: bool) -> None:
        """작업의 특정 단계 완료 여부를 설정합니다(D7)."""
        self.normalize_task(task)
        for step in task.get("steps", []):
            if step.get("id") == step_id:
                step["done"] = checked
                break
        self.app.save()
        self.refresh_all()
        self.notify_data_changed()

    def delete_step(self, task: dict, step_id: str) -> None:
        """작업에서 단계를 삭제합니다(D7)."""
        self.normalize_task(task)
        steps = task.get("steps", [])
        steps[:] = [step for step in steps if step.get("id") != step_id]
        self.app.save()
        self.refresh_all()
        self.notify_data_changed()

    def toggle_task_expand(self, task_id: str) -> None:
        """RepeatWindow 목록에서 작업 행의 아코디언(인라인 상세 편집) 확장을 토글합니다(D6)."""
        self.expanded_task_id = "" if self.expanded_task_id == task_id else task_id
        self.refresh_all()

    def task_stats_text(self, period: str, task: dict) -> tuple[str, str, str]:
        """상세 패널/아코디언 통계 블록에 쓸 (연속, 총 완료, 최근 완료) 문자열 3개를 만듭니다(D6)."""
        streak = self.task_streak(period, task)
        if streak >= 1:
            streak_key, streak_fallback = _META_STREAK_KEYS.get(period, ("todo.meta.streak.daily", "연속 {n}"))
            streak_text = self.tr(streak_key, streak_fallback, n=streak)
        else:
            streak_text = self.tr("todo.stats.streak.none", "연속 기록 없음")
        done_count = int(task.get("done_count", 0) or 0)
        done_text = self.tr("todo.stats.done_count", "총 {n}회 완료", n=done_count)
        last_key = last_completed_key(task.get("counted_keys", []))
        last_text = (
            self.tr("todo.stats.last.none", "완료 기록 없음")
            if not last_key
            else self.tr("todo.stats.last", "최근 완료: {value}", value=last_key)
        )
        return streak_text, done_text, last_text

    def move_task_order(self, task: dict, direction: int) -> None:
        """미완료 목록에서 작업의 표시 순서를 위/아래로 한 칸 옮기고 order를 재기록합니다(D8).

        판단: QListWidget에 setItemWidget으로 올린 커스텀 위젯은 InternalMove drag의
        drop 이후 위젯-행 연결이 어긋나기 쉬운 Qt의 잘 알려진 함정이라, 신뢰성이 검증된
        위/아래 버튼(스펙 D8의 명시적 폴백)으로 구현했다. 완료된 항목/헤더는 애초에
        이 메서드를 호출할 버튼 자체가 없다(TaskAccordion — 미완료일 때만 버튼 노출).
        """
        pending, _done, _changed, _total = self.visible_rows()
        task_id = str(task.get("id", ""))
        ids = [str(item_task.get("id", "")) for _period, item_task in pending]
        try:
            index = ids.index(task_id)
        except ValueError:
            return
        target = index + direction
        if target < 0 or target >= len(pending):
            return
        pending[index], pending[target] = pending[target], pending[index]
        for new_index, (_period, item_task) in enumerate(pending):
            item_task["order"] = new_index
        self.app.save()
        self.refresh_all()
        self.notify_data_changed()

    def queue_refresh_all(self, _query: str = "") -> None:
        """검색 textChanged용 디바운스 진입점 — 프로그램적 갱신은 refresh_all을 직접 호출한다."""
        self.search_timer.start()

    def toggle_done_section(self) -> None:
        """완료됨 섹션 접힘/펼침을 토글합니다(D4, 세션 단위 상태)."""
        self.done_collapsed = not self.done_collapsed
        self.refresh_all()

    def _add_task_item(self, period: str, task: dict, *, pending_ids: list[str] | None = None) -> None:
        """할 일 한 줄을 list_widget에 추가합니다. 펼쳐진 작업이면 아코디언도 뒤이어 추가한다(D6)."""
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 66))
        self.list_widget.addItem(item)
        row = RepeatTaskRow(self, period, task)
        self.list_widget.setItemWidget(item, row)
        if self.expanded_task_id and str(task.get("id", "")) == self.expanded_task_id:
            self._add_accordion_item(period, task, pending_ids=pending_ids or [])

    def _add_accordion_item(self, period: str, task: dict, *, pending_ids: list[str]) -> None:
        """D6 — 펼쳐진 작업 바로 아래에 인라인 상세 편집 아코디언을 추가합니다."""
        accordion = TaskAccordion(self, period, task, pending_ids=pending_ids)
        item = QListWidgetItem()
        item.setFlags(Qt.NoItemFlags)
        item.setSizeHint(accordion.sizeHint())
        self.list_widget.addItem(item)
        self.list_widget.setItemWidget(item, accordion)

    def _add_header_item(self, text: str, *, toggle: bool = False) -> None:
        """섹션 헤더 한 줄을 list_widget에 추가합니다(D4)."""
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 28))
        self.list_widget.addItem(item)
        header = SectionHeaderRow(self, text, toggle=toggle)
        self.list_widget.setItemWidget(item, header)

    def visible_rows(self) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]], bool, int]:
        """검색/필터를 적용해 미완료/완료로 분류한 행 목록을 반환합니다.

        refresh_all()과 D8 move_task_order()가 정확히 같은 목록 구성을 공유해야
        "지금 보이는 순서"와 "재기록되는 순서"가 어긋나지 않는다. 반환값은
        (미완료, 완료, normalize/D7 리셋으로 데이터가 바뀌었는지, 전체 작업 수)다.
        """
        query = self.search_input.text().strip().lower() if hasattr(self, "search_input") else ""
        changed = self.ensure_task_order()
        all_tasks = self.all_tasks()
        filtered: list[tuple[str, dict]] = []
        for period, task in all_tasks:
            before = dict(task)
            self.normalize_task(task)
            if reset_steps_for_period(task, self.current_key(period)):
                changed = True
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
            filtered.append((period, task))
        pending, done = classify_and_sort(filtered, self.is_done)
        return pending, done, changed, len(all_tasks)

    def refresh_all(self) -> None:
        """전체 화면을 현재 데이터로 다시 그립니다."""
        if self.search_timer.isActive():
            self.search_timer.stop()
        self.list_widget.clear()
        pending, done, changed, total_count = self.visible_rows()
        pending_ids = [str(task.get("id", "")) for _period, task in pending]

        # D4: 완료됨 필터 선택 시엔 단일 목록(섹션 없음). 그 외에는 미완료/완료됨
        # 2섹션으로 나누고, 완료됨은 기본 접힘(session-only)으로 보여준다.
        if self.filter_mode == "completed":
            for period, task in done:
                self._add_task_item(period, task, pending_ids=pending_ids)
        else:
            if pending:
                self._add_header_item(self.tr("todo.section.pending", "미완료"))
                for period, task in pending:
                    self._add_task_item(period, task, pending_ids=pending_ids)
            if done:
                label = self.tr("todo.section.done", "완료됨 {n}", n=len(done))
                self._add_header_item(label, toggle=True)
                if not self.done_collapsed:
                    for period, task in done:
                        self._add_task_item(period, task, pending_ids=pending_ids)

        if not pending and not done:
            empty_text = (
                self.tr("todo.empty", "아직 해야 할 일이 없습니다. + 버튼으로 추가하세요.")
                if total_count == 0
                else self.tr("todo.empty.filter", "이 조건에 맞는 해야 할 일이 없습니다.")
            )
            empty_item = QListWidgetItem(empty_text)
            empty_item.setFlags(Qt.NoItemFlags)
            self.list_widget.addItem(empty_item)
        if changed:
            self.app.save()

    def set_done(self, period: str, task: dict, checked: bool) -> None:
        """작업의 완료 여부를 설정합니다."""
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

    def list_style(self) -> str:
        """목록 위젯 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QListWidget {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 6px; outline: none; }}"
            f"QListWidget::item:selected {{ background: {c['panel2']}; border-radius: 6px; }}"
        )

    def checkbox_style(self) -> str:
        """체크박스 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return f"QCheckBox {{ color: {c['text']}; spacing: 8px; padding: 7px; }}"

    def input_style(self) -> str:
        """입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 8px; }}"
        )

    def combo_style(self) -> str:
        """콤보박스 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def plus_button_style(self) -> str:
        """추가(+) 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; font-size: 20px; font-weight: 700; padding-bottom: 2px; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def edit_button_style(self) -> str:
        """편집 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 9px; font-size: 11px; font-weight: 700; padding: 4px 8px; }}"
            f"QPushButton:hover {{ background: {c['border']}; color: {c['text']}; }}"
        )

    def filter_button_style(self, active: bool = False) -> str:
        """필터 버튼 QSS 스타일 문자열을 만듭니다."""
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
        """중요 표시(별) 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        color = IMPORTANT_STAR_COLOR if active else c["muted"]
        return (
            f"QPushButton {{ background: transparent; color: {color}; border: none; "
            "font-size: 18px; font-weight: 800; padding: 0; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )

    def button_style(self) -> str:
        """버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def closeEvent(self, event) -> None:
        self.app.store.set("repeat_geometry", geometry_string(self), notify_topic=None)
        self.app.save()
        scheduler = getattr(self.app, "scheduler", None)
        if scheduler is not None and self.refresh_if_period_changed in scheduler.on_day_changed:
            scheduler.on_day_changed.remove(self.refresh_if_period_changed)
        self.app.repeat_window = None
        super().closeEvent(event)

class RepeatTaskRow(QWidget):
    """반복 할 일 한 줄입니다. 행 자체(체크박스/별/버튼이 아닌 부분) 클릭으로
    아코디언(인라인 상세 편집, D6)을 펼치고 접을 수 있다."""

    def __init__(self, window: RepeatWindow, period: str, task: dict) -> None:
        super().__init__()
        self.window = window
        self.period = period
        self.task = task
        self.setCursor(Qt.PointingHandCursor)
        self.build_ui()

    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
        c = self.window.colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        done = self.window.is_done(self.period, self.task)
        check = QCheckBox()
        check.setChecked(done)
        check.setStyleSheet(self.window.checkbox_style())
        check.toggled.connect(partial(self.window.set_done, self.period, self.task))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        title = QLabel(self.task.get("text", ""))
        # 완료된 항목은 훑어볼 때 바로 구분되도록 취소선 + 흐린 색으로 표시한다.
        title_color = c["muted"] if done else c["text"]
        strike = "text-decoration: line-through;" if done else ""
        title.setStyleSheet(f"QLabel {{ color: {title_color}; background: transparent; font-weight: 600; {strike} }}")
        # D3: 메타라인은 "{주기} · {상태}[ · 연속 N단위][ · D-n][ · 단계 k/n]"로 재설계됐다 —
        # list_name은 목록 필터/콤보로 이미 드러나고, 목록 이름 경과·N회 완료는 행에서
        # 제거되어 세부 패널/아코디언(D6)으로 옮겨간다. 관리 탭도 이 빌더를 그대로 공유한다.
        segments = self.window.task_meta_text(self.period, self.task)
        meta_html = meta_segments_html(segments, c["muted"], DANGER_COLOR)
        meta = QLabel(meta_html)
        meta.setTextFormat(Qt.RichText)
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

        expanded = self.window.expanded_task_id == str(self.task.get("id", ""))
        # AUDIT-B D5 검수 중 발견: U+25B8/25BE(작은 삼각형)는 Pretendard+폴백 체인에서
        # tofu로 렌더된다(실측: capture_all.py 캡처 줌인). U+25B6/25BC(▶▼, 굵은 삼각형)는
        # 정상 렌더 확인 — 같은 글리프 결함이라 이 행 아코디언 화살표도 함께 교체한다.
        chevron = QLabel("▼" if expanded else "▶")
        chevron.setFixedWidth(14)
        chevron.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; }}")

        layout.addWidget(check)
        layout.addLayout(texts, 1)
        layout.addWidget(star)
        layout.addWidget(my_day)
        layout.addWidget(edit)
        layout.addWidget(chevron)

    def mousePressEvent(self, event) -> None:
        """행 배경(체크박스/버튼이 아닌 영역) 클릭으로 아코디언을 토글한다(D6).

        체크박스/별/오늘/수정 버튼은 각각 자기 클릭을 소비해 이 핸들러까지 전파되지
        않는다(make_upcoming_row/EventBlock과 같은 기존 패턴)."""
        if event.button() == Qt.LeftButton:
            self.window.toggle_task_expand(str(self.task.get("id", "")))
            event.accept()
            return
        super().mousePressEvent(event)


class SectionHeaderRow(QWidget):
    """할 일 목록의 섹션 헤더 한 줄입니다(D4 — "미완료"/"완료됨 N").

    `toggle=True`면 완료됨 섹션 헤더로, 클릭하면 접힘/펼침을 토글한다.
    AUDIT-B D5: 시인성·클릭 대상 보강 — 글자 소폭 확대(11→12px)+500 굵기,
    ▶/▼ 화살표를 접두로 옮겨 상태 표시를 더 눈에 띄게 하고, 버튼에 고정 높이+
    패딩+hover 배경을 줘 클릭 영역을 넓힌다. (작은 삼각형 ▸/▾ 대신 ▶/▼를 쓰는
    이유는 TaskAccordion 화살표 쪽 주석 참고 — 폰트 폴백 체인에서 tofu가 됨.)
    """

    def __init__(self, window: RepeatWindow, text: str, *, toggle: bool = False) -> None:
        super().__init__()
        self.window = window
        c = window.colors
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        if toggle:
            arrow = "▶" if window.done_collapsed else "▼"
            button = QPushButton(f"{arrow}  {text}")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(28)
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; border-radius: 6px; "
                "font-size: 12px; font-weight: 500; text-align: left; padding: 4px 8px; }}"
                f"QPushButton:hover {{ background: {c['panel2']}; color: {c['text']}; }}"
            )
            button.clicked.connect(window.toggle_done_section)
            layout.addWidget(button)
        else:
            label = QLabel(text)
            label.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 12px; font-weight: 500; }}")
            layout.addWidget(label)
        layout.addStretch()


class TaskAccordion(QWidget):
    """RepeatWindow 행 아래 펼쳐지는 인라인 상세 편집 표면입니다(D6).

    480px 폭 제약 때문에 관리 탭처럼 별도 우측 패널을 두지 못해, 행을 클릭하면
    같은 자리 아래로 펼쳐지는 아코디언으로 구현했다. 제목/중요/나의 하루/마감일/메모/
    단계 편집과 통계를 담고, 미완료 작업에는 순서 위/아래 버튼(D8)도 보여준다.

    D8 판단: QListWidget에 setItemWidget으로 올라간 커스텀 위젯은 InternalMove
    drag의 drop 이후 위젯-행 매핑이 어긋나기 쉬운 Qt의 잘 알려진 함정이다. 헤더/완료
    섹션이 섞인 이 목록에서 안전하게 구현하기엔 리스크가 커서, 스펙이 명시한 폴백대로
    위/아래 버튼 방식을 택했다(보고 사항 — 관리 탭 tasks_section.py는 order만
    반영하고 버튼은 없음, "order-only" 판단).
    """

    def __init__(self, window: RepeatWindow, period: str, task: dict, *, pending_ids: list[str]) -> None:
        super().__init__()
        self.window = window
        self.period = period
        self.task = task
        self.pending_ids = pending_ids
        self.build_ui()

    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
        window = self.window
        c = window.colors
        self.setStyleSheet(f"QWidget {{ background: {c['panel2']}; border-radius: 8px; }}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(6)

        self.title_input = QLineEdit(self.task.get("text", ""))
        self.title_input.setStyleSheet(window.input_style())
        self.title_input.editingFinished.connect(self.commit_title)
        layout.addWidget(self.title_input)

        info_row = QHBoxLayout()
        period_label = QLabel(window.period_label(self.period))
        period_label.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; }}")
        info_row.addWidget(period_label)
        info_row.addStretch()
        if not window.is_done(self.period, self.task):
            task_id = str(self.task.get("id", ""))
            try:
                index = self.pending_ids.index(task_id)
            except ValueError:
                index = -1
            up = QPushButton("▲")
            down = QPushButton("▼")
            for button in (up, down):
                button.setFixedSize(24, 24)
                button.setCursor(Qt.PointingHandCursor)
                button.setStyleSheet(window.edit_button_style())
            up.setEnabled(index > 0)
            down.setEnabled(0 <= index < len(self.pending_ids) - 1)
            up.clicked.connect(partial(window.move_task_order, self.task, -1))
            down.clicked.connect(partial(window.move_task_order, self.task, 1))
            info_row.addWidget(up)
            info_row.addWidget(down)
        layout.addLayout(info_row)

        toggle_row = QHBoxLayout()
        important_check = QCheckBox(window.tr("todo.filter.important", "중요"))
        important_check.setStyleSheet(window.checkbox_style())
        important_check.setChecked(bool(self.task.get("important")))
        important_check.toggled.connect(lambda _checked: window.toggle_important(self.task))
        my_day_check = QCheckBox(window.tr("todo.editor.myday", "나의 하루에 추가"))
        my_day_check.setStyleSheet(window.checkbox_style())
        my_day_check.setChecked(self.task.get("my_day") == date.today().isoformat())
        my_day_check.toggled.connect(lambda _checked: window.toggle_my_day(self.task))
        toggle_row.addWidget(important_check)
        toggle_row.addWidget(my_day_check)
        layout.addLayout(toggle_row)

        due_row = QHBoxLayout()
        due_check = QCheckBox(window.tr("todo.editor.due", "마감일"))
        due_check.setStyleSheet(window.checkbox_style())
        due_date = QDateEdit()
        due_date.setCalendarPopup(True)
        due_date.setDisplayFormat("yyyy-MM-dd")
        due_date.setStyleSheet(window.input_style())
        due_value = str(self.task.get("due", "") or "")
        if due_value:
            parsed = QDate.fromString(due_value, "yyyy-MM-dd")
            due_date.setDate(parsed if parsed.isValid() else QDate.currentDate())
            due_check.setChecked(True)
        else:
            due_date.setDate(QDate.currentDate())
        due_date.setEnabled(due_check.isChecked())
        due_check.toggled.connect(due_date.setEnabled)
        due_check.toggled.connect(lambda _checked: self.commit_due(due_check, due_date))
        due_date.dateChanged.connect(lambda _value: self.commit_due(due_check, due_date) if due_check.isChecked() else None)
        due_row.addWidget(due_check)
        due_row.addWidget(due_date, 1)
        layout.addLayout(due_row)

        self.notes_input = TaskNotesEdit(str(self.task.get("notes", "")), self.commit_notes)
        self.notes_input.setFixedHeight(52)
        self.notes_input.setStyleSheet(window.input_style())
        self.notes_input.setPlaceholderText(window.tr("todo.editor.memo.placeholder", "메모"))
        layout.addWidget(self.notes_input)

        steps_label = QLabel(window.tr("todo.steps.label", "단계"))
        steps_label.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 11px; font-weight: 700; }}")
        layout.addWidget(steps_label)
        for step in self.task.get("steps", []):
            layout.addWidget(self.build_step_row(step))

        self.step_input = QLineEdit()
        self.step_input.setPlaceholderText(window.tr("todo.steps.add_placeholder", "단계 추가 — Enter로 저장"))
        self.step_input.setStyleSheet(window.input_style())
        self.step_input.returnPressed.connect(self.add_step)
        layout.addWidget(self.step_input)

        stats_line = QLabel(" · ".join(window.task_stats_text(self.period, self.task)))
        stats_line.setWordWrap(True)
        stats_line.setStyleSheet(f"QLabel {{ color: {c['muted']}; background: transparent; font-size: 10px; }}")
        layout.addWidget(stats_line)

    def build_step_row(self, step: dict) -> QWidget:
        """단계 한 줄(체크 + 텍스트 + 삭제)을 만듭니다(D7)."""
        window = self.window
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        check = QCheckBox(step.get("text", ""))
        check.setStyleSheet(window.checkbox_style())
        check.setChecked(bool(step.get("done")))
        step_id = str(step.get("id", ""))
        check.toggled.connect(partial(window.toggle_step, self.task, step_id))
        delete = QPushButton("×")
        delete.setFixedSize(22, 22)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setStyleSheet(window.edit_button_style())
        delete.clicked.connect(partial(window.delete_step, self.task, step_id))
        row_layout.addWidget(check, 1)
        row_layout.addWidget(delete)
        return row

    def commit_title(self) -> None:
        """제목 편집을 커밋합니다(Enter 또는 포커스 아웃 시 QLineEdit.editingFinished)."""
        text = self.title_input.text().strip()
        if text and text != self.task.get("text", ""):
            self.window.set_task_field(self.period, self.task, text=text)

    def commit_notes(self, text: str) -> None:
        """메모 편집을 커밋합니다(포커스 아웃 시 TaskNotesEdit이 호출)."""
        if text.strip() != str(self.task.get("notes", "")):
            self.window.set_task_field(self.period, self.task, notes=text)

    def commit_due(self, due_check: QCheckBox, due_date: QDateEdit) -> None:
        """마감일 편집을 커밋합니다."""
        due = due_date.date().toString("yyyy-MM-dd") if due_check.isChecked() else ""
        if due != self.task.get("due", ""):
            self.window.set_task_field(self.period, self.task, due=due)

    def add_step(self) -> None:
        """단계 추가 입력창에서 Enter로 새 단계를 추가합니다(D7)."""
        text = self.step_input.text()
        if self.window.add_step(self.task, text):
            self.step_input.clear()


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
        """현재 언어에 맞는 창 제목 문자열을 반환합니다."""
        key = "todo.editor.title.edit" if self.edit_task else "todo.editor.title.add"
        fallback = f"{APP_NAME} 해야 할 일 {'수정' if self.edit_task else '추가'}"
        return self.repeat_window.tr(key, fallback).format(app=self.repeat_window.app_display_name())

    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
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
        self.header_title = QLabel(self.repeat_window.tr(title_key, title_fallback))
        self.header_title.setFont(app_font(13, QFont.Bold))
        close = IconButton("close", self.colors)
        close.setFixedSize(26, 24)
        close.clicked.connect(self.close)
        header.addWidget(self.header_title)
        header.addStretch()
        header.addWidget(close)

        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText(self.repeat_window.tr("todo.editor.text.placeholder", "할 일 입력"))
        if self.edit_task:
            self.text_input.setText(self.edit_task.get("text", ""))
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

        self.important_check = QCheckBox(self.repeat_window.tr("todo.filter.important", "중요"))
        self.important_check.setChecked(bool(self.edit_task and self.edit_task.get("important")))

        self.my_day_check = QCheckBox(self.repeat_window.tr("todo.editor.myday", "나의 하루에 추가"))
        self.my_day_check.setChecked(bool(self.edit_task and self.edit_task.get("my_day") == date.today().isoformat()))

        due_row = QHBoxLayout()
        self.due_check = QCheckBox(self.repeat_window.tr("todo.editor.due", "마감일"))
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

        # M1 QSS 정리: 같은 빌더를 개별 위젯마다 반복 호출하던 것을 루프 하나로 묶는다.
        for line_edit in (self.text_input, self.list_input, self.notes_input):
            line_edit.setStyleSheet(self.repeat_window.input_style())
        for checkbox in (self.important_check, self.my_day_check, self.due_check):
            checkbox.setStyleSheet(self.repeat_window.checkbox_style())

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
        """현재 테마 색상을 위젯 스타일에 다시 적용합니다."""
        draft = self.form_draft() if hasattr(self, "text_input") else None
        self.colors.update(self.repeat_window.app.dialog_colors())
        self.build_ui()
        if draft is not None:
            self.restore_form_draft(draft)
        self.update()

    def apply_language(self) -> None:
        """현재 언어 설정에 맞춰 화면 텍스트를 다시 그립니다."""
        draft = self.form_draft() if hasattr(self, "text_input") else None
        self.setWindowTitle(self.window_title_text())
        self.build_ui()
        if draft is not None:
            self.restore_form_draft(draft)
        self.update()

    def form_draft(self) -> RepeatTaskFormDraft:
        """편집 중인 입력값을 임시 저장용 draft로 만듭니다."""
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
        """임시 저장된 입력값(draft)을 폼에 되돌립니다."""
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
        """콤보박스 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox::drop-down {{ border: none; width: 22px; }}"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def date_style(self) -> str:
        """날짜 표시/입력 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QDateEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QDateEdit::drop-down {{ border: none; width: 20px; }}"
        )

    def delete_button_style(self) -> str:
        """삭제 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {DANGER_COLOR}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {DANGER_COLOR}; color: white; }}"
        )

    def add_task(self) -> None:
        """새 작업을 추가하고 저장합니다."""
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
        """작업을 삭제하고 저장합니다."""
        if self.edit_task and self.edit_period:
            self.repeat_window.delete_task(self.edit_period, str(self.edit_task.get("id", "")))
        self.close()

    def closeEvent(self, event) -> None:
        self.repeat_window.add_window = None
        super().closeEvent(event)

