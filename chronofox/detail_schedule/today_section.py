"""Detail-schedule 창의 "Today" 섹션 믹스인 (R4-5 — PROJECT.md §3 H4 결정표 T-D1~T-D11 구현).

그룹 계산(오늘 일정/놓친 항목/오늘 마감/나의 하루)은 전부 `core/today_logic.py`(Qt-free)에
있다 — 이 믹스인은 `build_today_summary()`의 결과를 그리기만 한다(T-D1). 완료/나의 하루
판정을 이 파일에서 다시 계산하지 않는다.

읽기 전용(T-D7, H-D7): 체크박스·인라인 편집·삭제·완료 토글을 두지 않는다. 행 클릭은
`show_section(kind, target)` 한 경로만 쓴다(T-D6, H-D8) — 일정은 `("week", ISO날짜)`,
할 일은 `("tasks", task id)`. 할 일 행의 메타라인은 `RepeatWindow.task_meta_text()`
(tasks_section.py의 `make_task_row`가 쓰는 것과 동일한 포매터)를 재사용해 "지남/D-n" 같은
판정을 두 벌로 만들지 않는다.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어 + 다른 믹스인이 제공):
- `self.app`(FoxCalendarApp, `.store`/`.task_service` 보관), `self.colors`(dict), `self.section`(str)
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.task_controller()` (TasksSectionMixin — `task_meta_text()` 포매터 재사용용)
- `self.show_section(kind, target=None)` (window.py 코어, H-D8 단일 이동 경로)
- `self.icon_only_button(icon, handler)`, `self.scroll_style()`, `self.close()` (layout.py)
"""

from __future__ import annotations

from datetime import date, datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from chronofox.core.today_logic import TodayGroup, build_today_summary
from chronofox.ui.app_theme import DANGER_COLOR
from chronofox.ui.app_ui import app_font, clear_layout, meta_segments_html

# 그룹 순서(T-D2)와 각 그룹의 (헤더 번역 키/기본값, 딥링크 대상 섹션 kind, 행 빌더 이름).
# 행 빌더는 이 클래스의 메서드명 문자열로 둬서 getattr로 늦게 바인딩한다(모듈 상단에서는
# 아직 self가 없다).
_GROUP_SPECS: list[tuple[str, tuple[str, str], str, str]] = [
    ("today_events", ("detail.today.group.events", "오늘 일정"), "week", "make_today_plan_row"),
    ("missed", ("detail.today.group.missed", "놓친 항목"), "tasks", "make_today_task_row"),
    ("due_today", ("detail.today.group.due_today", "오늘 마감"), "tasks", "make_today_task_row"),
    ("my_day", ("detail.today.group.my_day", "나의 하루"), "tasks", "make_today_task_row"),
]


class TodaySectionMixin:
    """Today 섹션(읽기 전용 요약 + 이동)의 상단바/본문/행을 담당합니다."""

    def show_today_view(self) -> None:
        """호환 위임: 기존 호출부가 그대로 동작하도록 show_section("today")를 부른다."""
        self.show_section("today")

    # top bar ---------------------------------------------------------------
    def build_today_top_bar(self) -> QHBoxLayout:
        """Today 화면 상단 바(제목 + 닫기)를 구성합니다. T-D7: 편집 진입점이 없으므로
        추가 버튼을 두지 않는다."""
        c = self.colors
        self.view_buttons = {}
        bar = QHBoxLayout()
        bar.setSpacing(12)
        title = QLabel(self.tr("detail.nav.today", "Today"))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")
        close_button = self.icon_only_button("close", self.close)
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(close_button)
        return bar

    # main view ---------------------------------------------------------------
    def build_today_view(self) -> QWidget:
        """Today 화면(네 그룹 요약)을 구성합니다."""
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
        self.today_box = QVBoxLayout(inner)
        self.today_box.setContentsMargins(2, 2, 12, 2)
        self.today_box.setSpacing(8)
        scroll.setWidget(inner)
        layout.addWidget(scroll, 1)
        self.refresh_today_view()
        return container

    def today_summary(self):
        """T-D1: 순수 함수 결과를 계산합니다(그리기는 전부 이 값만 본다)."""
        return build_today_summary(
            plans=self.app.store.plans(),
            tasks=self.app.task_service.tasks(),
            today=date.today(),
        )

    def refresh_today_view(self) -> None:
        """네 그룹을 현재 데이터로 다시 그립니다(T-D8: 빈 그룹은 헤더까지 숨기고, 네 그룹이
        모두 비면 중앙 안내 한 줄만 그린다)."""
        if self.section != "today" or not hasattr(self, "today_box"):
            return
        clear_layout(self.today_box)
        summary = self.today_summary()
        groups: list[tuple[TodayGroup, tuple[str, str], str, str]] = [
            (getattr(summary, field), header, section_kind, row_builder)
            for field, header, section_kind, row_builder in _GROUP_SPECS
        ]
        if not any(group.total for group, *_ in groups):
            self.today_box.addWidget(self.make_today_empty_hint())
            self.today_box.addStretch()
            return
        for group, (label_key, label_fallback), section_kind, row_builder_name in groups:
            if not group.total:
                continue
            self.today_box.addWidget(self.make_today_group_header(self.tr(label_key, label_fallback)))
            row_builder = getattr(self, row_builder_name)
            for item in group.items:
                self.today_box.addWidget(row_builder(item))
            hidden = group.total - len(group.items)
            if hidden > 0:
                self.today_box.addWidget(self.make_today_more_row(hidden, section_kind))
        self.today_box.addStretch()

    # rows --------------------------------------------------------------
    def make_today_empty_hint(self) -> QWidget:
        """T-D8: 네 그룹이 모두 비었을 때의 중앙 안내 한 줄."""
        c = self.colors
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 24, 0, 24)
        hint = QLabel(self.tr("detail.today.empty", "오늘 표시할 항목이 없습니다."))
        hint.setAlignment(Qt.AlignCenter)
        hint.setFont(app_font(11))
        hint.setStyleSheet(f"color: {c['muted2']};")
        layout.addWidget(hint)
        return container

    def make_today_group_header(self, text: str) -> QWidget:
        """그룹 헤더 한 줄(할 일 섹션의 비-토글 헤더와 같은 톤, T-D9)."""
        c = self.colors
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(4, 2, 4, 2)
        label = QLabel(text)
        label.setStyleSheet(f"color: {c['muted']}; background: transparent; font-size: 11px; font-weight: 500;")
        layout.addWidget(label)
        layout.addStretch()
        return row

    def _today_row_frame(self) -> tuple[QFrame, QHBoxLayout]:
        """행 공통 골격(보관함 행과 동일한 톤 — 패널 배경 + 테두리 + hover accent, T-D9)."""
        c = self.colors
        row = QFrame()
        row.setObjectName("todayRow")
        row.setCursor(Qt.PointingHandCursor)
        row.setStyleSheet(
            f"QFrame#todayRow {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}"
            f"QFrame#todayRow:hover {{ border: 1px solid {c['accent']}; }}"
        )
        layout = QHBoxLayout(row)
        layout.setContentsMargins(13, 10, 12, 10)
        layout.setSpacing(10)
        return row, layout

    def make_today_plan_row(self, plan: dict) -> QFrame:
        """오늘 일정 한 줄. 클릭 → `show_section("week", <ISO날짜>)`(T-D6)."""
        c = self.colors
        row, layout = self._today_row_frame()
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title = QLabel(plan.get("title", "") or self.tr("detail.untitled", "(제목 없음)"))
        title.setFont(app_font(11, QFont.Bold))
        title.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        today = date.today()
        start_dt = _parse_iso(plan.get("start", ""))
        # 시각을 보여주는 건 "오늘 시작하는 단일 일정"일 때만이다 — 기간 일정(long)이나
        # 어제 이전에 시작해 오늘까지 이어지는 일정에 시작 시각을 붙이면 오늘 그 시각에
        # 뭔가 있는 것처럼 읽힌다.
        starts_today = start_dt is not None and start_dt.date() == today
        when_text = (
            f"{start_dt:%H:%M}"
            if starts_today and plan.get("kind") != "long"
            else self.tr("detail.when.today", "오늘")
        )
        when = QLabel(when_text)
        when.setFont(app_font(8))
        when.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title)
        texts.addWidget(when)
        layout.addLayout(texts, 1)
        # 이 그룹의 일정은 정의상 전부 오늘에 걸쳐 있으므로 이동 대상은 항상 오늘이다.
        # 시작일로 보내면 3일짜리 일정을 오늘 눌렀을 때 지난 주로 점프한다(T-D6).
        today_iso = today.isoformat()
        row.mousePressEvent = (  # type: ignore[assignment]
            lambda _event, iso=today_iso: self.show_section("week", iso)
        )
        return row

    def make_today_task_row(self, task: dict) -> QFrame:
        """놓친 항목/오늘 마감/나의 하루 한 줄. 클릭 → `show_section("tasks", <task id>)`
        (T-D6). 메타라인은 `RepeatWindow.task_meta_text()`(tasks_section.py의 make_task_row와
        동일 포매터)를 재사용한다 — "지남"/"D-n" 판정을 다시 만들지 않는다."""
        c = self.colors
        row, layout = self._today_row_frame()
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(2)
        title = QLabel(task.get("text", "") or self.tr("detail.untitled", "(제목 없음)"))
        title.setFont(app_font(11, QFont.Bold))
        title.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        segments = self.task_controller().task_meta_text(task)
        meta_html = meta_segments_html(segments, c["muted2"], DANGER_COLOR)
        meta = QLabel(meta_html)
        meta.setTextFormat(Qt.RichText)
        meta.setFont(app_font(8))
        meta.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title)
        texts.addWidget(meta)
        layout.addLayout(texts, 1)
        task_id = str(task.get("id", ""))
        row.mousePressEvent = (  # type: ignore[assignment]
            lambda _event, tid=task_id: self.show_section("tasks", tid)
        )
        return row

    def make_today_more_row(self, hidden_count: int, section_kind: str) -> QFrame:
        """T-D5: 상한 초과분을 접는 "+N개 더" 한 줄. 클릭 → 대상 없이 해당 섹션으로 이동."""
        c = self.colors
        row, layout = self._today_row_frame()
        label = QLabel(self.tr("detail.today.more", "+{count}개 더", count=hidden_count))
        label.setFont(app_font(9, QFont.Bold))
        label.setStyleSheet(f"color: {c['muted']}; background: transparent;")
        layout.addWidget(label)
        row.mousePressEvent = (  # type: ignore[assignment]
            lambda _event, kind=section_kind: self.show_section(kind)
        )
        return row


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
