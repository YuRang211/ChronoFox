"""Detail-schedule 창의 "해야 할 일" 섹션 믹스인.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어가 제공):
- `self.app`(FoxCalendarApp, `.repeat_window` 보관), `self.colors`(dict), `self.section`(str)
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

from chronofox.core.todo_logic import classify_and_sort
from chronofox.ui.app_theme import DANGER_COLOR, IMPORTANT_STAR_COLOR
from chronofox.ui.app_ui import app_font, clear_layout, meta_segments_html
from chronofox.windows.todo_window import RepeatWindow, TaskNotesEdit

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
        """작업(할 일) 화면을 보여줍니다."""
        if self.section == "tasks":
            return
        self.section = "tasks"
        self.build_ui()

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

        # AUDIT-B D6: 무기능 벨 아이콘(DETAIL2 목업 잔재) 제거 — layout.py 상단 바와 통일.
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

        # D2: 인라인 빠른 추가 — tasks_box(스크롤 내부) 밖에 둬서 store "tasks" 알림으로
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
        """빠른 추가 입력창에서 Enter로 새 작업을 추가합니다(D2, 관리 탭).
        빈 입력은 무시하고, 추가에 성공하면 입력창을 비운 채 포커스를 유지한다."""
        text = self.tasks_quick_add_input.text().strip()
        if not text:
            return
        self.task_controller().add_task("daily", text)
        self.tasks_quick_add_input.clear()
        self.tasks_quick_add_input.setFocus()

    def task_visible(self, controller: RepeatWindow, period: str, task: dict) -> bool:
        """필터 조건에 따라 작업을 목록에 표시할지 판단합니다."""
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
        """작업 목록을 현재 데이터/필터로 다시 그립니다."""
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
        # D4: '완료됨' 필터는 단일 목록, 그 외는 미완료/완료됨(기본 접힘) 2섹션.
        pending, done = classify_and_sort(rows, controller.is_done)
        if self.task_filter == "completed":
            for period, task in done:
                self.tasks_box.addWidget(self.make_task_row(controller, period, task))
        else:
            if pending:
                self.tasks_box.addWidget(self.make_task_section_header(self.tr("todo.section.pending", "미완료")))
                for period, task in pending:
                    self.tasks_box.addWidget(self.make_task_row(controller, period, task))
            if done:
                label = self.tr("todo.section.done", "완료됨 {n}", n=len(done))
                self.tasks_box.addWidget(self.make_task_section_header(label, toggle=True))
                if not self.tasks_done_collapsed:
                    for period, task in done:
                        self.tasks_box.addWidget(self.make_task_row(controller, period, task))
        self.tasks_box.addStretch()

    def make_task_row(self, controller: RepeatWindow, period: str, task: dict) -> QFrame:
        """작업 목록의 한 줄 위젯을 만듭니다. 행(체크박스/별/버튼이 아닌 부분) 클릭으로
        우측 패널을 이 작업의 상세 편집 화면으로 전환한다(D6)."""
        c = self.colors
        done = controller.is_done(period, task)
        row = QFrame()
        row.setObjectName("taskRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QFrame#taskRow {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}"
        )
        row.mousePressEvent = (  # type: ignore[assignment]
            lambda _event, p=period, t=task: self.select_task_detail(p, t)
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
        # D3: RepeatWindow와 동일한 task_meta_text() 빌더를 공유해 두 화면의 메타라인이
        # 어긋나지 않게 한다(공통 note).
        segments = controller.task_meta_text(period, task)
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
        """작업 목록 필터(전체/오늘/중요 등)를 설정합니다."""
        self.task_filter = mode
        for key, button in getattr(self, "task_filter_buttons", {}).items():
            button.setStyleSheet(self.task_filter_style(key == mode))
        self.refresh_tasks_view()

    def toggle_task_done(self, period: str, task: dict, checked: bool) -> None:
        """작업의 완료 여부를 토글합니다."""
        self.task_controller().set_done(period, task, checked)
        self.refresh_tasks_view()

    def toggle_task_important(self, task: dict) -> None:
        """작업의 중요 표시를 토글합니다."""
        self.task_controller().toggle_important(task)
        self.refresh_tasks_view()

    def toggle_task_my_day(self, task: dict) -> None:
        """작업의 '내 하루' 포함 여부를 토글합니다."""
        self.task_controller().toggle_my_day(task)
        self.refresh_tasks_view()

    def add_task_item(self) -> None:
        """새 작업을 추가합니다."""
        self.task_controller().open_add_task()

    def edit_task_item(self, period: str, task: dict) -> None:
        """기존 작업을 편집합니다."""
        self.task_controller().open_edit_task(period, task)

    # D6 — 상세 패널 -----------------------------------------------------
    def select_task_detail(self, period: str, task: dict) -> None:
        """작업 행을 클릭하면 우측 "한눈에 보기" 패널을 상세 편집 화면으로 전환합니다(D6)."""
        self.selected_task = (period, task)
        self.refresh_side_panel()

    def close_task_detail(self) -> None:
        """상세 패널의 뒤로가기 — 한눈에 보기 패널로 복귀합니다(D6)."""
        self.selected_task = None
        self.refresh_side_panel()

    def sync_after_task_edit(self) -> None:
        """상세 패널에서 편집한 뒤 작업 목록과 패널(통계 등)을 함께 갱신합니다(D6).

        task_controller()의 편집 메서드(set_task_field/add_step/toggle_step 등)는
        이미 store.notify("tasks")로 알리지만, 이 창 자체가 그 편집을 발생시킨
        발신자이므로(구독 콜백이 자기 자신을 다시 부르는 형태를 피해) 여기서
        명시적으로 두 화면을 갱신한다 — toggle_task_important 등 기존 D2/D4 패턴과 동일."""
        self.refresh_tasks_view()
        self.refresh_side_panel()

    def build_task_detail_panel(self, layout: QVBoxLayout) -> None:
        """우측 패널을 작업 상세 편집 화면으로 채웁니다(D6).

        RepeatWindow의 TaskAccordion과 같은 컨트롤러 메서드(set_task_field/add_step/
        toggle_step/delete_step)를 공유하지만, 위젯 자체는 detail_schedule 전용 팔레트
        (c['muted2']/c['text_soft'] 등)와 240px 고정 폭에 맞춰 따로 구성한다 — 두 창의
        colors dict 스키마가 달라 위젯까지 통합하면 더 위험하다는 판단(Phase1의
        task_meta_text 공유 방식과 같은 절충).
        """
        if self.selected_task is None:
            return
        period, task = self.selected_task
        controller = self.task_controller()
        controller.normalize_task(task)
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
        title_input.editingFinished.connect(lambda: self._commit_detail_field(controller, period, task, "text", title_input.text()))
        layout.addWidget(title_input)

        period_label = QLabel(controller.period_label(period))
        period_label.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px; font-weight: 700;")
        layout.addWidget(period_label)

        important_check = QCheckBox(self.tr("todo.filter.important", "중요"))
        important_check.setStyleSheet(self.task_checkbox_label_style())
        important_check.setChecked(bool(task.get("important")))
        important_check.toggled.connect(lambda _checked: self._toggle_detail_important(controller, task))
        layout.addWidget(important_check)
        my_day_check = QCheckBox(self.tr("todo.editor.myday", "나의 하루에 추가"))
        my_day_check.setStyleSheet(self.task_checkbox_label_style())
        my_day_check.setChecked(task.get("my_day") == date.today().isoformat())
        my_day_check.toggled.connect(lambda _checked: self._toggle_detail_my_day(controller, task))
        layout.addWidget(my_day_check)

        due_row = QHBoxLayout()
        due_check = QCheckBox(self.tr("todo.editor.due", "마감일"))
        due_check.setStyleSheet(self.task_checkbox_label_style())
        due_date = QDateEdit()
        due_date.setCalendarPopup(True)
        due_date.setDisplayFormat("yyyy-MM-dd")
        due_date.setStyleSheet(self.task_detail_input_style())
        due_value = str(task.get("due", "") or "")
        if due_value:
            parsed = QDate.fromString(due_value, "yyyy-MM-dd")
            due_date.setDate(parsed if parsed.isValid() else QDate.currentDate())
            due_check.setChecked(True)
        else:
            due_date.setDate(QDate.currentDate())
        due_date.setEnabled(due_check.isChecked())
        due_check.toggled.connect(due_date.setEnabled)
        due_check.toggled.connect(lambda _checked: self._commit_detail_due(controller, period, task, due_check, due_date))
        due_date.dateChanged.connect(
            lambda _value: self._commit_detail_due(controller, period, task, due_check, due_date) if due_check.isChecked() else None
        )
        due_row.addWidget(due_check)
        due_row.addWidget(due_date, 1)
        layout.addLayout(due_row)

        notes_input = TaskNotesEdit(
            str(task.get("notes", "")),
            lambda text: self._commit_detail_field(controller, period, task, "notes", text),
        )
        notes_input.setFixedHeight(64)
        notes_input.setStyleSheet(self.task_detail_input_style())
        notes_input.setPlaceholderText(self.tr("todo.editor.memo.placeholder", "메모"))
        layout.addWidget(notes_input)

        steps_label = QLabel(self.tr("todo.steps.label", "단계"))
        steps_label.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px; font-weight: 700;")
        layout.addWidget(steps_label)
        for step in task.get("steps", []):
            layout.addWidget(self._build_detail_step_row(controller, task, step))

        step_input = QLineEdit()
        step_input.setPlaceholderText(self.tr("todo.steps.add_placeholder", "단계 추가 — Enter로 저장"))
        step_input.setStyleSheet(self.task_detail_input_style())
        step_input.returnPressed.connect(lambda: self._add_detail_step(controller, task, step_input))
        layout.addWidget(step_input)

        stats_label = QLabel(self.tr("detail.tasks.stats", "통계"))
        stats_label.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px; font-weight: 700;")
        layout.addWidget(stats_label)
        for stat_text in controller.task_stats_text(period, task):
            stat_line = QLabel(stat_text)
            stat_line.setWordWrap(True)
            stat_line.setStyleSheet(f"color: {c['muted2']}; background: transparent; font-size: 10px;")
            layout.addWidget(stat_line)

        layout.addStretch()

    def _build_detail_step_row(self, controller: RepeatWindow, task: dict, step: dict) -> QWidget:
        """상세 패널의 단계 한 줄(체크 + 텍스트 + 삭제)을 만듭니다(D7)."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(6)
        check = QCheckBox(step.get("text", ""))
        check.setStyleSheet(self.task_checkbox_label_style())
        check.setChecked(bool(step.get("done")))
        step_id = str(step.get("id", ""))
        check.toggled.connect(partial(self._toggle_detail_step, controller, task, step_id))
        delete = QPushButton("×")
        delete.setFixedSize(20, 20)
        delete.setCursor(Qt.PointingHandCursor)
        delete.setStyleSheet(self.task_edit_style())
        delete.clicked.connect(partial(self._delete_detail_step, controller, task, step_id))
        row_layout.addWidget(check, 1)
        row_layout.addWidget(delete)
        return row

    def _commit_detail_field(self, controller: RepeatWindow, period: str, task: dict, field: str, value: str) -> None:
        """제목(text)/메모(notes) 필드 편집을 커밋합니다(공백 트림 후 비교, 무변경이면 무시)."""
        value = value.strip()
        if not value and field == "text":
            return
        if value == str(task.get(field, "")).strip():
            return
        controller.set_task_field(period, task, **{field: value})
        self.sync_after_task_edit()

    def _commit_detail_due(self, controller: RepeatWindow, period: str, task: dict, due_check: QCheckBox, due_date: QDateEdit) -> None:
        due = due_date.date().toString("yyyy-MM-dd") if due_check.isChecked() else ""
        if due == task.get("due", ""):
            return
        controller.set_task_field(period, task, due=due)
        self.sync_after_task_edit()

    def _toggle_detail_important(self, controller: RepeatWindow, task: dict) -> None:
        controller.toggle_important(task)
        self.sync_after_task_edit()

    def _toggle_detail_my_day(self, controller: RepeatWindow, task: dict) -> None:
        controller.toggle_my_day(task)
        self.sync_after_task_edit()

    def _toggle_detail_step(self, controller: RepeatWindow, task: dict, step_id: str, checked: bool) -> None:
        controller.toggle_step(task, step_id, checked)
        self.sync_after_task_edit()

    def _delete_detail_step(self, controller: RepeatWindow, task: dict, step_id: str) -> None:
        controller.delete_step(task, step_id)
        self.sync_after_task_edit()

    def _add_detail_step(self, controller: RepeatWindow, task: dict, step_input: QLineEdit) -> None:
        if controller.add_step(task, step_input.text()):
            step_input.clear()
            self.sync_after_task_edit()

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
