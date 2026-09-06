"""Detail-schedule 창의 "해야 할 일" 섹션 믹스인.

T4(todo-v3): 평면 `tasks: []` 모델(`chronofox.core.task_logic`)을 다룬다. 이 믹스인은
`self.app.task_service`(TaskService)가 제공하는 데이터 조작/필터 계산을 호출해 화면을
그린다. 필터·접힘·선택 상태는 이 허브 섹션의 세션 상태다.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어가 제공):
- `self.app`(FoxCalendarApp), `self.colors`(dict), `self.section`(str)
- `self.task_filter`(str), `self.tasks_box`(QVBoxLayout, build_tasks_view가 생성)
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.build_ui()`, `self.icon_only_button(icon, handler)`, `self.scroll_style()`, `self.close()`
"""

from __future__ import annotations

from datetime import date
from functools import partial

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QDateEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.task_logic import is_active, is_completed
from chronofox.core.task_logic import normalize_task as _normalize_task
from chronofox.core.task_logic import task_streak as _task_streak
from chronofox.core.todo_logic import (
    TASK_FILTER_CHOICES,
    TASK_META_DONE_KEYS,
    TASK_META_STREAK_KEYS,
    TASK_PERIOD_CHOICES,
    days_until,
    last_completed_key,
    steps_progress,
)
from chronofox.ui.app_theme import DANGER_COLOR, IMPORTANT_STAR_COLOR
from chronofox.ui.app_ui import app_font, clear_layout, meta_segments_html

from .task_editor import TaskEditorWindow, TaskNotesEdit
from .widgets import stroke_icon


class TasksSectionMixin:
    """할 일 목록 상단바/본문/행/필터/토글 액션과 관련 스타일을 담당합니다."""

    def task_period_label(self, period: str | None) -> str:
        """저장된 반복 주기를 현재 언어의 화면 라벨로 바꿉니다."""
        if period is None:
            return self.tr("todo.period.none", "반복 없음")
        labels = {key: self.tr(label_key, fallback) for key, label_key, fallback in TASK_PERIOD_CHOICES}
        return labels.get(period, period)

    def task_is_today(self, task: dict) -> bool:
        """오늘 마감이거나 매일 반복인 미완료 작업인지 반환합니다."""
        if not is_active(task):
            return False
        if task.get("due") == date.today().isoformat():
            return True
        recurrence = task.get("recurrence")
        return bool(recurrence) and recurrence.get("period") == "daily"

    def task_mode_lists(self, mode: str) -> tuple[list[dict], list[dict]]:
        """선택한 필터에 맞는 미완료·완료 목록을 서비스 정렬 순서로 반환합니다."""
        service = self.app.task_service
        if mode == "myday":
            return service.smart_list_my_day(), []
        if mode == "important":
            return service.smart_list_important(), []
        if mode == "completed":
            return [], service.smart_list_completed()
        if mode == "today":
            return [task for task in service.smart_list_all() if self.task_is_today(task)], []
        return service.smart_list_all(), service.smart_list_completed()

    def task_meta_text(self, task: dict) -> list[tuple[str, str]]:
        """작업 행과 Today 요약에서 공유할 메타 세그먼트를 만듭니다."""
        today = date.today()
        recurrence = task.get("recurrence")
        done = is_completed(task)
        segments: list[tuple[str, str]] = []
        if recurrence is not None:
            period = recurrence.get("period", "daily")
            segments.append((self.task_period_label(period), "normal"))
            if done:
                status_key, status_fallback = TASK_META_DONE_KEYS.get(period, ("todo.meta.done.daily", "완료"))
                segments.append((self.tr(status_key, status_fallback), "normal"))
            else:
                segments.append((self.tr("todo.meta.not_done", "아직 안 함"), "danger"))
            streak = _task_streak(task, today)
            if streak >= 2:
                streak_key, streak_fallback = TASK_META_STREAK_KEYS.get(
                    period, ("todo.meta.streak.daily", "연속 {n}")
                )
                segments.append((self.tr(streak_key, streak_fallback, n=streak), "normal"))
        elif done:
            segments.append((self.tr("todo.meta.done.once", "완료"), "normal"))
        else:
            segments.append((self.tr("todo.meta.not_done", "아직 안 함"), "danger"))

        due = str(task.get("due") or "")
        if due:
            delta = days_until(due, today)
            if delta is not None:
                if delta < 0:
                    segments.append((self.tr("todo.meta.overdue", "{n}일 지남", n=abs(delta)), "danger"))
                else:
                    segments.append((self.tr("todo.meta.due", "D-{n}", n=delta), "normal"))
        done_steps, total_steps = steps_progress(task.get("steps") or [])
        if total_steps:
            segments.append(
                (self.tr("todo.meta.steps", "단계 {done}/{total}", done=done_steps, total=total_steps), "normal")
            )
        return segments

    def task_stats_text(self, task: dict) -> tuple[str, str, str]:
        """상세 패널의 연속·완료 횟수·최근 완료 문자열을 만듭니다."""
        recurrence = task.get("recurrence")
        streak = _task_streak(task, date.today())
        period = recurrence.get("period", "daily") if recurrence else "daily"
        if streak:
            streak_key, streak_fallback = TASK_META_STREAK_KEYS.get(
                period, ("todo.meta.streak.daily", "연속 {n}")
            )
            streak_text = self.tr(streak_key, streak_fallback, n=streak)
        else:
            streak_text = self.tr("todo.stats.streak.none", "연속 기록 없음")
        if recurrence is not None:
            streak_keys = recurrence.get("streak_keys", [])
            done_count = len(streak_keys)
            last_key = last_completed_key(streak_keys)
        else:
            done_count = 1 if is_completed(task) else 0
            last_key = str(task.get("completed_at") or "")[:10]
        done_text = self.tr("todo.stats.done_count", "총 {n}회 완료", n=done_count)
        last_text = (
            self.tr("todo.stats.last.none", "완료 기록 없음")
            if not last_key
            else self.tr("todo.stats.last", "최근 완료: {value}", value=last_key)
        )
        return streak_text, done_text, last_text

    def show_tasks_view(self) -> None:
        """호환 위임: 기존 호출부가 그대로 동작하도록 show_section("tasks")를 부른다."""
        self.show_section("tasks")

    def build_tasks_top_bar(self) -> QHBoxLayout:
        """작업 화면 상단 바를 구성합니다."""
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
        for key, label_key, fallback in TASK_FILTER_CHOICES:
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

        close_button = self.icon_only_button("close", self.close)

        bar.addWidget(title)
        bar.addSpacing(8)
        bar.addLayout(filter_row)
        bar.addStretch()
        bar.addWidget(add_button)
        bar.addWidget(close_button)
        return bar

    def build_tasks_view(self) -> QWidget:
        """작업 목록 화면을 구성합니다."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # 입력 행은 스크롤 목록 밖에 둬 새로고침 때 입력 내용과 포커스를 보존한다.
        # 목록이 다시 그려져도 입력창 자체는 살아남는다(포커스 유지).
        self.tasks_quick_add_input = QLineEdit()
        self.tasks_quick_add_input.setPlaceholderText(self.tr("todo.quickadd.placeholder", "할 일 추가 — Enter로 저장"))
        self.tasks_quick_add_input.setStyleSheet(self.task_quick_add_style())
        self.tasks_quick_add_input.returnPressed.connect(self.quick_add_task_item)
        layout.addWidget(self.tasks_quick_add_input)

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

    def quick_add_task_item(self) -> None:
        """빠른 추가 입력창에서 Enter로 새 작업을 추가합니다(D2, 관리 탭, T4 — 1회성으로
        저장한다). 빈 입력은 무시하고, 추가에 성공하면 입력창을 비운 채 포커스를 유지한다."""
        text = self.tasks_quick_add_input.text().strip()
        if not text:
            return
        self.app.task_service.add_task(text)
        self.tasks_quick_add_input.clear()
        self.tasks_quick_add_input.setFocus()

    def toggle_tasks_done_section(self) -> None:
        """완료됨 섹션 접힘/펼침을 토글합니다(D4, 세션 단위 상태)."""
        self.tasks_done_collapsed = not self.tasks_done_collapsed
        self.refresh_tasks_view()

    def make_task_section_header(self, text: str, *, toggle: bool = False) -> QWidget:
        """작업 목록의 섹션 헤더 한 줄을 만듭니다(D4 — "미완료"/"완료됨 N").

        AUDIT-B D5: 시인성·클릭 대상 보강 — `muted2`(옅음) 대신 `muted`로 대비를
        올리고, 글자 소폭 확대(10→11px)+500 굵기, ▶/▼ 화살표를 접두로, 버튼에
        고정 높이+패딩+hover 배경을 줘 클릭 영역을 넓힌다. (작은 삼각형 ▸/▾가 아니라
        ▶/▼를 쓰는 이유: Pretendard+폴백 체인에서 U+25B8/25BE만 tofu로 렌더됨 — 실측
        확인.)
        """
        c = self.colors
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        if toggle:
            arrow = "▶" if self.tasks_done_collapsed else "▼"
            button = QPushButton(f"{arrow}  {text}")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(26)
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; border-radius: 6px; "
                "font-size: 11px; font-weight: 500; text-align: left; padding: 4px 8px; }}"
                f"QPushButton:hover {{ background: {c['hover']}; color: {c['text_soft']}; }}"
            )
            button.clicked.connect(self.toggle_tasks_done_section)
            layout.addWidget(button)
        else:
            label = QLabel(text)
            label.setStyleSheet(f"color: {c['muted']}; background: transparent; font-size: 11px; font-weight: 500;")
            layout.addWidget(label)
        layout.addStretch()
        return row

    def refresh_tasks_view(self) -> None:
        """작업 목록을 현재 데이터/필터로 다시 그립니다.

        필터 판정은 ``task_mode_lists(self.task_filter)``에 모아 목록과 Today가 같은
        TaskService 정렬 계약을 사용한다."""
        if self.section != "tasks" or not hasattr(self, "tasks_box"):
            return
        clear_layout(self.tasks_box)
        self.app.task_service.ensure_task_order()
        pending, done = self.task_mode_lists(self.task_filter)
        if not pending and not done:
            key = "detail.tasks.empty" if self.task_filter == "all" else "detail.tasks.empty_filter"
            empty = QLabel(self.tr(key, "해야 할 일이 없습니다."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.colors['muted2']}; padding: 10px 4px;")
            self.tasks_box.addWidget(empty)
            self.tasks_box.addStretch()
            return
        # 완료 필터만 단일 목록이고 나머지는 미완료와 접힌 완료 목록으로 나눈다.
        if self.task_filter == "completed":
            for task in done:
                self.tasks_box.addWidget(self.make_task_row(task))
        else:
            if pending:
                self.tasks_box.addWidget(self.make_task_section_header(self.tr("todo.section.pending", "미완료")))
                for task in pending:
                    self.tasks_box.addWidget(self.make_task_row(task))
            if done:
                label = self.tr("todo.section.done", "완료됨 {n}", n=len(done))
                self.tasks_box.addWidget(self.make_task_section_header(label, toggle=True))
                if not self.tasks_done_collapsed:
                    for task in done:
                        self.tasks_box.addWidget(self.make_task_row(task))
        self.tasks_box.addStretch()

    def make_task_row(self, task: dict) -> QFrame:
        """작업 목록의 한 줄 위젯을 만듭니다. 행(체크박스/별/버튼이 아닌 부분) 클릭으로
        우측 패널을 이 작업의 상세 편집 화면으로 전환한다(D6)."""
        c = self.colors
        done = is_completed(task)
        row = QFrame()
        row.setObjectName("taskRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QFrame#taskRow {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}"
        )
        row.mousePressEvent = (  # type: ignore[assignment]
            lambda _event, t=task: self.select_task_detail(t)
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 9, 10, 9)
        layout.setSpacing(10)

        check = QCheckBox()
        check.setChecked(done)
        check.setCursor(Qt.PointingHandCursor)
        check.setStyleSheet(self.task_checkbox_style())
        check.toggled.connect(lambda checked, t=task: self.toggle_task_done(t, checked))

        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title = QLabel(task.get("text", "") or self.tr("detail.untitled", "(제목 없음)"))
        title.setFont(app_font(11, QFont.Bold))
        strike = "text-decoration: line-through;" if done else ""
        title.setStyleSheet(f"color: {c['muted2'] if done else c['text_soft']}; background: transparent; {strike}")
        segments = self.task_meta_text(task)
        meta_html = meta_segments_html(segments, c["muted2"], DANGER_COLOR)
        meta = QLabel(meta_html)
        meta.setTextFormat(Qt.RichText)
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
        edit.clicked.connect(lambda _checked=False, t=task: self.edit_task_item(t))

        for button in (my_day, edit):
            button.setStyleSheet(self.task_edit_style())

        layout.addWidget(check)
        layout.addLayout(texts, 1)
        layout.addWidget(star)
        layout.addWidget(my_day)
        layout.addWidget(edit)
        return row

    def set_task_filter(self, mode: str) -> None:
        """작업 목록 필터(전체/오늘/중요 등)를 설정합니다."""
        self.task_filter = mode
        for key, button in getattr(self, "task_filter_buttons", {}).items():
            button.setStyleSheet(self.task_filter_style(key == mode))
        self.refresh_tasks_view()

    def toggle_task_done(self, task: dict, checked: bool) -> None:
        """작업의 완료 여부를 토글합니다."""
        if checked == is_completed(task):
            return
        self.app.task_service.toggle_complete(task.get("id", ""))

    def toggle_task_important(self, task: dict) -> None:
        """작업의 중요 표시를 토글합니다."""
        self.app.task_service.toggle_important(task.get("id", ""))

    def toggle_task_my_day(self, task: dict) -> None:
        """작업의 '내 하루' 포함 여부를 토글합니다."""
        self.app.task_service.toggle_my_day(task.get("id", ""))

    def add_task_item(self) -> None:
        """상세 추가 편집기를 엽니다."""
        editor = getattr(self, "task_editor_window", None)
        if editor is not None and editor.isVisible():
            editor.raise_()
            editor.activateWindow()
            return
        self.task_editor_window = TaskEditorWindow(self)
        self.task_editor_window.show()
        self.task_editor_window.raise_()
        self.task_editor_window.activateWindow()

    def edit_task_item(self, task: dict) -> None:
        """기존 작업을 상세 편집기에서 엽니다."""
        editor = getattr(self, "task_editor_window", None)
        if editor is not None and editor.isVisible():
            editor.close()
        self.task_editor_window = TaskEditorWindow(self, task)
        self.task_editor_window.show()
        self.task_editor_window.raise_()
        self.task_editor_window.activateWindow()

    # D6 — 상세 패널 -----------------------------------------------------
    def select_task_detail(self, task: dict) -> None:
        """작업 행을 클릭하면 우측 "한눈에 보기" 패널을 상세 편집 화면으로 전환합니다(D6)."""
        self.selected_task = task
        self.refresh_side_panel()

    def close_task_detail(self) -> None:
        """상세 패널의 뒤로가기 — 한눈에 보기 패널로 복귀합니다(D6)."""
        self.selected_task = None
        self.refresh_side_panel()

    def build_task_detail_panel(self, layout: QVBoxLayout) -> None:
        """우측 패널을 작업 상세 편집 화면으로 채웁니다(D6).

        저장은 TaskService의 update_task/add_step/toggle_step/delete_step만 사용하고,
        위젯은 detail_schedule 전용 팔레트와 240px 고정 폭에 맞춘다."""
        if self.selected_task is None:
            return
        task = self.selected_task
        _normalize_task(task)
        c = self.colors

        back_row = QHBoxLayout()
        back = QPushButton(f"  {self.tr('detail.tasks.back', '뒤로')}")
        back.setCursor(Qt.PointingHandCursor)
        back.setIcon(QIcon(stroke_icon("chevron_left", c["muted"], 14)))
        back.setFixedHeight(26)
        back.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; "
            "text-align: left; font-size: 11px; font-weight: 700; padding: 0; }}"
            f"QPushButton:hover {{ color: {c['text_soft']}; }}"
        )
        back.clicked.connect(self.close_task_detail)
        back_row.addWidget(back)
        back_row.addStretch()
        layout.addLayout(back_row)

        title_input = QLineEdit(task.get("text", ""))
        title_input.setStyleSheet(self.task_detail_input_style())
        title_input.editingFinished.connect(lambda: self._commit_detail_field(task, "text", title_input.text()))
        layout.addWidget(title_input)

        recurrence = task.get("recurrence")
        period_label = QLabel(self.task_period_label(recurrence.get("period") if recurrence else None))
        period_label.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px; font-weight: 700;")
        layout.addWidget(period_label)

        important_check = QCheckBox(self.tr("todo.filter.important", "중요"))
        important_check.setStyleSheet(self.task_checkbox_label_style())
        important_check.setChecked(bool(task.get("important")))
        important_check.toggled.connect(lambda _checked: self._toggle_detail_important(task))
        layout.addWidget(important_check)
        my_day_check = QCheckBox(self.tr("todo.editor.myday", "나의 하루에 추가"))
        my_day_check.setStyleSheet(self.task_checkbox_label_style())
        my_day_check.setChecked(task.get("my_day_date") == date.today().isoformat())
        my_day_check.toggled.connect(lambda _checked: self._toggle_detail_my_day(task))
        layout.addWidget(my_day_check)

        due_row = QHBoxLayout()
        due_check = QCheckBox(self.tr("todo.editor.due", "마감일"))
        due_check.setStyleSheet(self.task_checkbox_label_style())
        due_date = QDateEdit()
        due_date.setCalendarPopup(True)
        due_date.setDisplayFormat("yyyy-MM-dd")
        due_date.setStyleSheet(self.task_detail_input_style())
        due_value = str(task.get("due") or "")
        if due_value:
            parsed = QDate.fromString(due_value, "yyyy-MM-dd")
            due_date.setDate(parsed if parsed.isValid() else QDate.currentDate())
            due_check.setChecked(True)
        else:
            due_date.setDate(QDate.currentDate())
        due_date.setEnabled(due_check.isChecked())
        due_check.toggled.connect(due_date.setEnabled)
        due_check.toggled.connect(lambda _checked: self._commit_detail_due(task, due_check, due_date))
        due_date.dateChanged.connect(
            lambda _value: self._commit_detail_due(task, due_check, due_date) if due_check.isChecked() else None
        )
        due_row.addWidget(due_check)
        due_row.addWidget(due_date, 1)
        layout.addLayout(due_row)

        notes_input = TaskNotesEdit(
            str(task.get("notes", "")),
            lambda text: self._commit_detail_field(task, "notes", text),
        )
        notes_input.setFixedHeight(64)
        notes_input.setStyleSheet(self.task_detail_input_style())
        notes_input.setPlaceholderText(self.tr("todo.editor.memo.placeholder", "메모"))
        layout.addWidget(notes_input)

        steps_label = QLabel(self.tr("todo.steps.label", "단계"))
        steps_label.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px; font-weight: 700;")
        layout.addWidget(steps_label)
        for step in task.get("steps", []):
            layout.addWidget(self._build_detail_step_row(task, step))

        step_input = QLineEdit()
        step_input.setPlaceholderText(self.tr("todo.steps.add_placeholder", "단계 추가 — Enter로 저장"))
        step_input.setStyleSheet(self.task_detail_input_style())
        step_input.returnPressed.connect(lambda: self._add_detail_step(task, step_input))
        layout.addWidget(step_input)

        stats_label = QLabel(self.tr("detail.tasks.stats", "통계"))
        stats_label.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px; font-weight: 700;")
        layout.addWidget(stats_label)
        for stat_text in self.task_stats_text(task):
            stat_line = QLabel(stat_text)
            stat_line.setWordWrap(True)
            stat_line.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px;")
            layout.addWidget(stat_line)

        layout.addStretch()

    def _build_detail_step_row(self, task: dict, step: dict) -> QWidget:
        """상세 패널의 단계 한 줄(체크 + 텍스트 + 삭제)을 만듭니다(D7)."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        check = QCheckBox(step.get("text", ""))
        check.setStyleSheet(self.task_checkbox_label_style())
        check.setChecked(bool(step.get("done")))
        step_id = str(step.get("id", ""))
        check.toggled.connect(partial(self._toggle_detail_step, task, step_id))
        delete = QPushButton("×")
        delete.setFixedSize(20, 20)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setStyleSheet(self.task_edit_style())
        delete.clicked.connect(partial(self._delete_detail_step, task, step_id))
        row_layout.addWidget(check, 1)
        row_layout.addWidget(delete)
        return row

    def _commit_detail_field(self, task: dict, field: str, value: str) -> None:
        """제목(text)/메모(notes) 필드 편집을 커밋합니다(공백 트림 후 비교, 무변경이면 무시)."""
        value = value.strip()
        if not value and field == "text":
            return
        if value == str(task.get(field, "")).strip():
            return
        self.app.task_service.update_task(task.get("id", ""), **{field: value})

    def _commit_detail_due(self, task: dict, due_check: QCheckBox, due_date: QDateEdit) -> None:
        due = due_date.date().toString("yyyy-MM-dd") if due_check.isChecked() else None
        if due == task.get("due"):
            return
        self.app.task_service.update_task(task.get("id", ""), due=due)

    def _toggle_detail_important(self, task: dict) -> None:
        self.app.task_service.toggle_important(task.get("id", ""))

    def _toggle_detail_my_day(self, task: dict) -> None:
        self.app.task_service.toggle_my_day(task.get("id", ""))

    def _toggle_detail_step(self, task: dict, step_id: str, checked: bool) -> None:
        self.app.task_service.toggle_step(task.get("id", ""), step_id, checked)

    def _delete_detail_step(self, task: dict, step_id: str) -> None:
        self.app.task_service.delete_step(task.get("id", ""), step_id)

    def _add_detail_step(self, task: dict, step_input: QLineEdit) -> None:
        if self.app.task_service.add_step(task.get("id", ""), step_input.text()):
            step_input.clear()

    def task_filter_style(self, active: bool) -> str:
        """작업 필터 버튼 QSS 스타일 문자열을 만듭니다."""
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

    def task_quick_add_style(self) -> str:
        """빠른 추가 입력창(D2) QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 8px 10px; }}"
        )

    def task_checkbox_style(self) -> str:
        """작업 완료 체크박스 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QCheckBox {{ spacing: 0; }}"
            f"QCheckBox::indicator {{ width: 18px; height: 18px; border: 1px solid {c['faint']}; border-radius: 6px; "
            f"background: {c['panel2']}; }}"
            f"QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}"
        )

    def task_star_style(self, active: bool) -> str:
        """작업 중요 표시(별) QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        color = IMPORTANT_STAR_COLOR if active else c["muted"]
        return (
            f"QPushButton {{ background: transparent; color: {color}; border: none; font-size: 17px; "
            "font-weight: 800; padding: 0; }}"
            f"QPushButton:hover {{ color: {c['accent']}; }}"
        )

    def task_edit_style(self) -> str:
        """작업 편집 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 8px; font-size: 11px; font-weight: 700; padding: 0 9px; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['text']}; }}"
        )

    def task_checkbox_label_style(self) -> str:
        """텍스트가 붙은 체크박스(중요/나의 하루/단계 등, D6 상세 패널) QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QCheckBox {{ color: {c['text_soft']}; spacing: 6px; font-size: 10px; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid {c['faint']}; border-radius: 5px; "
            f"background: {c['panel2']}; }}"
            f"QCheckBox::indicator:checked {{ background: {c['accent']}; border: 1px solid {c['accent']}; }}"
        )

    def task_detail_input_style(self) -> str:
        """상세 패널(D6)의 제목/마감일/메모/단계 입력 위젯 공통 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit, QDateEdit, QTextEdit {{ background: {c['panel']}; color: {c['text_soft']}; "
            f"border: 1px solid {c['border']}; border-radius: 9px; padding: 6px 8px; font-size: 10px; }}"
            f"QDateEdit::drop-down {{ border: none; width: 18px; }}"
        )
