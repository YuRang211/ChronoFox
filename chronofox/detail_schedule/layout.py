"""Detail-schedule 창의 위젯 조립 믹스인 (사이드바/탑바/시간뷰/사이드패널 + 새로고침).

clock/layout.py(ClockLayoutMixin)와 같은 패턴 — window.py의 코어(초기화/데이터 계산/
네비게이션/테마)와 실제 Qt 위젯 생성을 분리해 두 파일 모두 600줄 아래로 유지한다.

REQUIRED attributes/메서드 (DetailScheduleWindow 코어 + 다른 믹스인이 제공):
- `self.app`, `self.colors`(dict), `self.radius`(int), `self.section`(str), `self.view_mode`(str)
- `self.days`(list[date]), `self.mini_calendar`
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- 데이터: `self.timed_plans_for_day`, `self.all_day_plans_for_day`, `self.upcoming_plans`,
  `self.view_event_count`, `self.compute_days`, `self.compute_lanes` (window.py 코어)
- 네비게이션/편집: `self.set_view_mode`, `self.go_previous`, `self.go_next`, `self.go_today`,
  `self.add_plan`, `self.edit_plan`, `self.show_section`/`self.show_calendar_view`(위임)
  (window.py 코어, H-D8 — 사이드바는 show_section(kind)만 직접 호출한다)
- 스타일: `self.scroll_style`, `self.view_button_style` (window.py 코어)
- 검색(R4-2, H1): `self.search_timer`(window.py 코어, QTimer 재사용), `self._search_query`
  (window.py 코어, 섹션 전환 시 검색어 보존용 문자열 상태)
- 섹션 믹스인: `self.show_tasks_view`/`self.build_tasks_view`/`self.build_tasks_top_bar`
  (TasksSectionMixin), `self.show_archive_view`/`self.build_archive_view`/
  `self.build_archive_top_bar` (ArchiveSectionMixin), `self.build_month_view`
  (MonthViewMixin), `self.build_alarms_view`/`self.build_alarms_top_bar`/
  `self.stop_alarms_display_timer` (AlarmsSectionMixin — 알람 목록 + 하단 시계·스톱워치·
  타이머 보조 영역, R4-3a), `self.build_settings_view`/`self.build_settings_top_bar`
  (SettingsSectionMixin — 프로그램/테마/연동/정보 4탭, R4-4a), `self.build_today_view`/
  `self.build_today_top_bar`/`self.refresh_today_view` (TodaySectionMixin — Today 네 그룹
  요약, R4-5. R4-1의 HubPlaceholderMixin은 이 섹션이 실이식되면서 삭제됐다)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.app_constants import APP_NAME_EN
from chronofox.core.search_logic import SearchResult, search_all
from chronofox.ui.app_ui import app_font, clear_layout

from .widgets import HOUR_HEIGHT, DayHeader, MiniCalendar, SearchResultWidget, TimeGrid, _hex_to_rgb, _parse_dt, stroke_icon

# 검색 결과 kind -> (배지 번역 키, 기본값). search_logic.SearchResult.kind와 동일한 어휘
# (H-D8 이동표는 open_search_result()가 담당).
SEARCH_KIND_LABELS: dict[str, tuple[str, str]] = {
    "note": ("search.kind.schedule", "노트"),
    "plan": ("search.kind.plan", "일정"),
    "task": ("search.kind.task", "할 일"),
    "memo": ("search.kind.memo", "메모"),
}


class DetailLayoutMixin:
    """사이드바/탑바/시간뷰/사이드패널 위젯 구성과 그 새로고침을 담당합니다."""

    # build ------------------------------------------------------------
    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
        # R4-3a(H-D9): 알람 섹션을 벗어나는 모든 재빌드(다른 섹션 전환, 테마/언어 갱신
        # 포함) 전에 표시 갱신 타이머를 먼저 멈춘다 — 이 섹션이 아니면 타이머가 죽은
        # 위젯을 계속 건드리게 된다.
        self.stop_alarms_display_timer()
        # 업데이트 controller는 앱 수명 동안 살아 있으므로 설정 섹션의 자식 위젯을
        # 지우기 전에 상태 신호를 끊는다. 설정을 다시 열면 새 위젯에 재연결된다.
        self.disconnect_update_controller()
        existing = self.layout()
        if existing is None:
            root = QHBoxLayout(self)
        else:
            clear_layout(existing)
            root = existing
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 이전 빌드의 위젯 참조를 비워 삭제된 위젯을 다시 건드리지 않도록 한다.
        # R4-1(H-D12): today_box도 여기 포함해, 지금 표시 중인 섹션이 아니면
        # 속성 자체가 존재하지 않게 한다(지연 생성 검증 포인트).
        for attr in (
            "grid",
            "day_header",
            "all_day_row",
            "all_day_layout",
            "scroll_area",
            "tasks_box",
            "archive_box",
            "today_box",
            "alarm_list",
            "next_alarm_label",
            "alarms_aux_stack",
            "alarms_aux_buttons",
            "alarms_clock_time",
            "alarms_clock_date",
            "stopwatch_label",
            "stopwatch_start_button",
            "timer_label",
            "timer_hours",
            "timer_minutes",
            "timer_seconds",
            "settings_tab_stack",
            "settings_tab_buttons",
        ):
            self.__dict__.pop(attr, None)
        self.mini_calendar = None
        self.compute_days()
        self.compute_lanes()

        root.addWidget(self.build_sidebar())
        root.addWidget(self.build_main(), 1)
        root.addWidget(self.build_side_panel())
        self.setStyleSheet(f"QLabel {{ color: {self.colors['text']}; }}")
        self.refresh_events()
        if self.view_mode != "month" and hasattr(self, "scroll_area"):
            self.scroll_area.verticalScrollBar().setValue(int(7.5 * HOUR_HEIGHT))

    def build_sidebar(self) -> QFrame:
        """세부 일정 창 좌측 사이드바를 구성합니다."""
        c = self.colors
        frame = QFrame()
        frame.setObjectName("detailSidebar")
        # AUDIT-B D4: 174px에서는 "PROFESSIONAL SUITE" 부제(letter-spacing 1px 포함
        # sizeHint 109px)가 브랜드 열 가용 폭(146-42=104px)을 5px 초과해 "E"가 잘렸다.
        # 184px로 넓혀 여유를 둔다(실측: python -c로 QLabel.sizeHint() 확인).
        frame.setFixedWidth(184)
        frame.setStyleSheet(
            f"QFrame#detailSidebar {{ background: {c['sidebar']}; border: none; border-right: 1px solid {c['border_soft']}; "
            f"border-top-left-radius: {self.radius}px; border-bottom-left-radius: {self.radius}px; }}"
        )
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 20, 14, 18)
        layout.setSpacing(3)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(32, 32)
        logo.setAlignment(Qt.AlignCenter)
        logo.setStyleSheet(f"background: {c['accent']}; border-radius: 9px;")
        logo.setPixmap(stroke_icon("logo", "#ffffff", 18, 2.2))
        brand_text = QVBoxLayout()
        brand_text.setSpacing(2)
        name = QLabel(APP_NAME_EN)
        name.setFont(app_font(12, QFont.Bold))
        name.setStyleSheet(f"color: {c['text']};")
        suite = QLabel(self.tr("detail.suite", "PROFESSIONAL SUITE"))
        suite.setFont(app_font(6, QFont.Bold))
        suite.setStyleSheet(f"color: {c['muted2']}; letter-spacing: 1px;")
        brand_text.addWidget(name)
        brand_text.addWidget(suite)
        brand.addWidget(logo)
        brand.addLayout(brand_text)
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(18)

        # R4-1(H-D8): 6개 섹션 전환은 모두 show_section(kind) 한 경로를 거친다 — 트레이·
        # 딥링크·검색 결과 클릭도 이후 단계에서 이 경로에 합류한다.
        active_kind = self.section
        for kind, label_key, fallback, icon in self.NAV_ITEMS:
            active = kind == active_kind
            button = self.make_nav_button(self.tr(label_key, fallback), icon, active)
            button.clicked.connect(lambda _checked=False, k=kind: self.show_section(k))
            layout.addWidget(button)

        layout.addStretch()
        return frame

    def make_nav_button(self, label: str, icon: str, active: bool) -> QPushButton:
        """사이드바 내비게이션 버튼을 만듭니다."""
        c = self.colors
        button = QPushButton(f"  {label}")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(36)
        color = c["text"] if active else c["muted"]
        button.setIcon(QIcon(stroke_icon(icon, color, 16)))
        button.setIconSize(QSize(16, 16))
        bg = c["panel2"] if active else "transparent"
        weight = "600" if active else "500"
        button.setStyleSheet(
            f"QPushButton {{ background: {bg}; color: {color}; border: none; border-radius: 9px; "
            f"text-align: left; padding: 0 11px; font-size: 12px; font-weight: {weight}; }}"
            f"QPushButton:hover {{ background: {c['hover']}; color: {c['text']}; }}"
        )
        return button

    def build_main(self) -> QFrame:
        """세부 일정 창의 메인 영역을 구성합니다."""
        c = self.colors
        frame = QFrame()
        frame.setObjectName("detailMain")
        frame.setStyleSheet(f"QFrame#detailMain {{ background: {c['bg']}; border: none; }}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 14)
        layout.setSpacing(14)
        # R4-2(H1): "본문 상단 상시 검색바" — 섹션 전용 상단 바(build_top_bar())와 별개로
        # 6개 섹션 전부에서 항상 그린다(H-D6: 섹션을 옮겨도 검색어를 잃지 않는다).
        layout.addWidget(self.build_search_bar())
        layout.addLayout(self.build_top_bar())
        if self.section == "tasks":
            layout.addWidget(self.build_tasks_view(), 1)
        elif self.section == "archive":
            layout.addWidget(self.build_archive_view(), 1)
        elif self.section == "alarms":
            layout.addWidget(self.build_alarms_view(), 1)
        elif self.section == "settings":
            layout.addWidget(self.build_settings_view(), 1)
        elif self.section == "today":
            layout.addWidget(self.build_today_view(), 1)
        elif self.view_mode == "month":
            layout.addWidget(self.build_month_view(), 1)
        else:
            layout.addWidget(self.build_time_view(), 1)
        return frame

    def build_time_view(self) -> QWidget:
        """시간대별(주간) 캘린더 뷰를 구성합니다."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.all_day_row = QWidget()
        self.all_day_layout = QHBoxLayout(self.all_day_row)
        self.all_day_layout.setContentsMargins(0, 0, 0, 0)
        self.all_day_layout.setSpacing(6)
        layout.addWidget(self.all_day_row)

        self.day_header = DayHeader(self)
        layout.addWidget(self.day_header)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setStyleSheet(self.scroll_style())
        self.grid = TimeGrid(self)
        self.scroll_area.setWidget(self.grid)
        layout.addWidget(self.scroll_area, 1)
        return container

    def build_top_bar(self) -> QHBoxLayout:
        """메인 영역 상단 바를 구성합니다."""
        if self.section == "tasks":
            return self.build_tasks_top_bar()
        if self.section == "archive":
            return self.build_archive_top_bar()
        if self.section == "alarms":
            return self.build_alarms_top_bar()
        if self.section == "settings":
            return self.build_settings_top_bar()
        if self.section == "today":
            return self.build_today_top_bar()
        c = self.colors
        bar = QHBoxLayout()
        bar.setSpacing(12)

        # R4-2: 예전엔 여기 검색 창(SearchWindow)을 여는 버튼이 있었다 — 이제 실제 입력
        # 필드가 build_search_bar()로 상시 표시되므로(build_main()에서 이 상단 바보다
        # 먼저 그려진다), 그 자리는 나머지 버튼들을 원래처럼 오른쪽으로 미는 스트레치만
        # 남긴다.
        self.view_buttons: dict[str, QPushButton] = {}
        view_row = QHBoxLayout()
        view_row.setSpacing(14)
        for mode, label_key, fallback in (
            ("day", "detail.view.day", "일"),
            ("week", "detail.view.week", "주"),
            ("month", "detail.view.month", "월"),
        ):
            button = QPushButton(self.tr(label_key, fallback))
            button.setCursor(Qt.PointingHandCursor)
            button.setFlat(True)
            button.clicked.connect(lambda _checked=False, selected=mode: self.set_view_mode(selected))
            button.setStyleSheet(self.view_button_style(mode == self.view_mode))
            self.view_buttons[mode] = button
            view_row.addWidget(button)

        add_button = QPushButton(self.tr("detail.add_event", "일정 추가"))
        add_button.setCursor(Qt.PointingHandCursor)
        add_button.setFixedHeight(32)
        add_button.clicked.connect(self.add_plan)
        add_button.setStyleSheet(
            f"QPushButton {{ background: {c['pill']}; color: {c['pill_text']}; border: none; "
            "border-radius: 9px; padding: 0 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['accent']}; color: #ffffff; }}"
        )

        prev_button = self.icon_only_button("chevron_left", self.go_previous)
        next_button = self.icon_only_button("chevron_right", self.go_next)
        today_button = QPushButton(self.tr("detail.today", "오늘"))
        today_button.setCursor(Qt.PointingHandCursor)
        today_button.setFixedHeight(28)
        today_button.clicked.connect(self.go_today)
        today_button.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 0 10px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

        # AUDIT-B D6: 무기능 벨 아이콘(DETAIL2 목업 잔재) 제거.
        close_button = self.icon_only_button("close", self.close)

        bar.addStretch(1)
        bar.addLayout(view_row)
        bar.addWidget(prev_button)
        bar.addWidget(today_button)
        bar.addWidget(next_button)
        bar.addWidget(add_button)
        bar.addWidget(close_button)
        return bar

    # search bar (R4-2, H1) ------------------------------------------------
    def build_search_bar(self) -> QWidget:
        """본문 상단 상시 검색바를 구성합니다 — 6개 섹션 모두에서 build_main()이 항상
        먼저 그린다. 노트・일정・할 일・메모를 `search_logic.search_all()`(SearchWindow와
        공유하는 Qt-free 순수 함수, 두 벌 구현 금지)로 찾는다.

        섹션 전환 때마다 build_ui()가 이 위젯 자체를 새로 만들지만(D6 재빌드 관용구),
        입력 문자열은 `self._search_query`에 별도로 남아 있어 검색어를 잃지 않는다
        (SearchWindow.build_ui()의 `current_query` 관용구와 동일).
        """
        c = self.colors
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self.tr("detail.search", "일정 검색..."))
        self.search_input.setFixedHeight(32)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.addAction(QIcon(stroke_icon("search", c["muted"], 14)), QLineEdit.LeadingPosition)
        self.search_input.setStyleSheet(self.search_input_style())
        self.search_input.setText(self._search_query)
        self.search_input.textChanged.connect(self.queue_search_refresh)
        self.search_input.returnPressed.connect(self.refresh_search_results)
        layout.addWidget(self.search_input)

        self.search_results_box = QVBoxLayout()
        self.search_results_box.setContentsMargins(2, 0, 2, 0)
        self.search_results_box.setSpacing(4)
        layout.addLayout(self.search_results_box)

        self.refresh_search_results()
        return container

    def search_input_style(self) -> str:
        """검색바 입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 9px; padding: 6px 10px; font-size: 12px; }}"
            f"QLineEdit:focus {{ border-color: {c['accent']}; }}"
        )

    def queue_search_refresh(self, text: str) -> None:
        """검색어가 바뀌면 짧은 디바운스 후 결과를 갱신하도록 예약합니다
        (SEARCH_DEBOUNCE_MS 재사용, SearchWindow와 동일한 관용구)."""
        self._search_query = text
        self.search_timer.start()

    def refresh_search_results(self) -> None:
        """현재 검색어로 검색 결과를 다시 계산해 그립니다. 빈 질의면 결과 영역을 비워
        둔다(입력창 하나만 상시 보이고, 결과 패널은 입력이 있을 때만 나타난다)."""
        if self.search_timer.isActive():
            self.search_timer.stop()
        if not hasattr(self, "search_results_box"):
            return
        clear_layout(self.search_results_box)
        query = self.search_input.text() if hasattr(self, "search_input") else self._search_query
        self._search_query = query
        if not query.strip():
            return
        results = search_all(
            query,
            schedules=self.app.store.schedules(),
            plans=self.app.store.plans(),
            tasks=self.app.task_service.tasks(),
            memos=self.hub_search_memo_rows(),
        )
        if not results:
            empty = QLabel(self.tr("search.empty.none", "검색 결과가 없습니다."))
            empty.setStyleSheet(f"color: {self.colors['muted2']}; font-size: 11px; padding: 6px 4px;")
            self.search_results_box.addWidget(empty)
            return
        for result in results:
            self.search_results_box.addWidget(self.make_search_result_row(result))

    def hub_search_memo_rows(self) -> list[dict]:
        """`search_logic.search_memos`에 넘길 메모 원본 목록을 만듭니다(SearchWindow의
        `memo_search_rows()`와 같은 모양 — 두 화면이 같은 store/memo_store를 읽는다)."""
        titles = self.app.store.get("memo_titles", {})
        return [
            {"id": memo_id, "title": titles.get(memo_id, ""), "content": self.app.memo_store.load(memo_id)}
            for memo_id in self.app.memo_store.memo_ids()
        ]

    def make_search_result_row(self, result: SearchResult) -> QWidget:
        """검색 결과 한 줄을 만듭니다. 그리기는 SearchWindow의 `SearchResultWidget`을
        그대로 재사용한다(같은 배지+제목+미리보기 레이아웃을 두 번 그리지 않는다)."""
        label_key, label_fallback = SEARCH_KIND_LABELS.get(result.kind, ("search.kind.schedule", "노트"))
        label = result.label
        if result.kind == "memo" and not label:
            label = self.tr("search.memo.untitled", "제목 없는 메모")
        preview = result.preview or label
        row = SearchResultWidget(self.tr(label_key, label_fallback), label, preview, self.colors)
        row.setFixedHeight(48)
        row.setCursor(Qt.PointingHandCursor)
        row.mousePressEvent = lambda _event, r=result: self.open_search_result(r)  # type: ignore[assignment]
        return row

    def open_search_result(self, result: SearchResult) -> None:
        """검색 결과 클릭 → `show_section(kind, target)`으로 이동합니다(H-D8).

        매핑: 노트/일정(``note``/``plan``) → week 섹션 + 날짜, 할 일(``task``) → tasks
        섹션 + task id, 메모(``memo``) → archive 섹션 + memo id. `result.target`은
        `search_logic`이 이미 그 섹션이 받는 모양으로 만들어 두므로 그대로 전달한다.
        """
        section_kind = {"note": "week", "plan": "week", "task": "tasks", "memo": "archive"}.get(result.kind, "week")
        self.show_section(section_kind, result.target)

    def icon_only_button(self, icon: str, handler) -> QPushButton:
        """아이콘만 있는 버튼을 만듭니다."""
        c = self.colors
        button = QPushButton()
        button.setCursor(Qt.PointingHandCursor)
        button.setIcon(QIcon(stroke_icon(icon, c["muted"], 16, 2.0)))
        button.setIconSize(QSize(16, 16))
        button.setFixedSize(28, 28)
        button.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 7px; }"
            f"QPushButton:hover {{ background: {c['panel2']}; }}"
        )
        button.clicked.connect(handler)
        return button

    def build_side_panel(self) -> QFrame:
        """우측 보조 패널(한눈에 보기/할 일 상세) 컨테이너를 구성합니다.

        내용물은 이 프레임 생성 직후 build_ui()가 호출하는 refresh_events() ->
        refresh_side_panel()이 채운다(D6 — 한눈에 보기 ↔ 할 일 상세 전환이 이 안에서
        일어나므로, 내용 빌드는 refresh_side_panel()로 분리했다)."""
        c = self.colors
        panel = QFrame()
        panel.setObjectName("detailSide")
        panel.setFixedWidth(240)
        panel.setStyleSheet(
            f"QFrame#detailSide {{ background: {c['bg']}; border: none; border-left: 1px solid {c['border_soft']}; "
            f"border-top-right-radius: {self.radius}px; border-bottom-right-radius: {self.radius}px; }}"
        )
        self.side_panel_layout = QVBoxLayout(panel)
        self.side_panel_layout.setContentsMargins(18, 18, 18, 18)
        self.side_panel_layout.setSpacing(16)
        return panel

    def refresh_side_panel(self) -> None:
        """우측 보조 패널 내용을 현재 상태(한눈에 보기 vs 할 일 상세, D6)에 맞게 다시 그립니다."""
        if not hasattr(self, "side_panel_layout"):
            return
        clear_layout(self.side_panel_layout)
        self.mini_calendar = None
        if self.section == "tasks" and self.selected_task is not None:
            self.build_task_detail_panel(self.side_panel_layout)
        else:
            self.build_glance_panel(self.side_panel_layout)

    def build_glance_panel(self, layout: QVBoxLayout) -> None:
        """"한눈에 보기" 패널 내용(미니 달력/다가오는 일정/요약 카드)을 채웁니다."""
        c = self.colors
        glance = QLabel(self.tr("detail.quick_glance", "한눈에 보기"))
        glance.setFont(app_font(14, QFont.Bold))
        layout.addWidget(glance)

        self.mini_calendar = MiniCalendar(self)
        layout.addWidget(self.mini_calendar)

        upcoming_head = QHBoxLayout()
        upcoming_label = QLabel(self.tr("detail.upcoming", "다가오는 일정"))
        upcoming_label.setFont(app_font(7, QFont.Bold))
        upcoming_label.setStyleSheet(f"color: {c['muted2']}; letter-spacing: 1px;")
        self.upcoming_badge = QLabel("")
        self.upcoming_badge.setFont(app_font(7, QFont.Bold))
        self.upcoming_badge.setStyleSheet(
            f"QLabel {{ background: {c['panel2']}; color: {c['muted']}; border-radius: 5px; padding: 2px 7px; }}"
        )
        upcoming_head.addWidget(upcoming_label)
        upcoming_head.addStretch()
        upcoming_head.addWidget(self.upcoming_badge)
        layout.addLayout(upcoming_head)

        self.upcoming_box = QVBoxLayout()
        self.upcoming_box.setSpacing(13)
        layout.addLayout(self.upcoming_box)
        self.refresh_upcoming()

        layout.addStretch()
        layout.addWidget(self.build_trend_card())
        count = self.view_event_count()
        self.trend_value.setText(self.tr("detail.trend.count", "{count}건", count=count))

    def build_trend_card(self) -> QFrame:
        """요약 통계 카드를 구성합니다."""
        c = self.colors
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {c['card']}; border: 1px solid {c['card_border']}; border-radius: 12px; }}"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 13, 14, 13)
        layout.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(7)
        icon = QLabel()
        icon.setPixmap(stroke_icon("trend", c["accent"], 14, 2.0))
        title = QLabel(self.tr("detail.trend.label", "표시 중 일정"))
        title.setFont(app_font(7, QFont.Bold))
        title.setStyleSheet(f"color: {c['muted2']}; letter-spacing: 1px;")
        head.addWidget(icon)
        head.addWidget(title)
        head.addStretch()
        self.trend_value = QLabel("")
        self.trend_value.setFont(app_font(20, QFont.Bold))
        self.trend_value.setStyleSheet(f"color: {c['accent']};")
        self.trend_caption = QLabel(self.tr("detail.trend.caption", "현재 보기 기준 시간 일정 수입니다."))
        self.trend_caption.setWordWrap(True)
        self.trend_caption.setFont(app_font(8))
        self.trend_caption.setStyleSheet(f"color: {c['muted2']};")
        layout.addLayout(head)
        layout.addWidget(self.trend_value)
        layout.addWidget(self.trend_caption)
        return card

    # refresh ------------------------------------------------------------
    def refresh_events(self) -> None:
        """현재 뷰의 일정 표시를 다시 그립니다."""
        self.compute_days()
        self.compute_lanes()
        if self.section == "today":
            self.refresh_today_view()
        if self.section == "tasks":
            self.refresh_tasks_view()
        if self.section == "archive":
            self.refresh_archive_view()
        if hasattr(self, "day_header"):
            self.day_header.update()
        if hasattr(self, "all_day_layout"):
            self.refresh_all_day_row()
        if hasattr(self, "grid"):
            self.refresh_grid_blocks()
        # D6: 우측 패널은 상태(한눈에 보기 vs 할 일 상세)에 따라 이 한 곳에서 다시 그린다
        # — 예전에는 (지금은 제거된) MiniCalendar.sync_anchor()/refresh_upcoming()/
        # trend_value 갱신이 여기 흩어져 있었는데, build_glance_panel()이 그 내용을
        # 모두 흡수했다(AUDIT-B Q2: sync_anchor는 참조가 이 주석뿐이라 데드코드로 삭제).
        self.refresh_side_panel()

    def refresh_grid_blocks(self) -> None:
        """시간대 그리드의 일정 블록들을 다시 그립니다."""
        self.grid.clear_blocks()
        for day in self.days:
            for plan, start_dt, end_dt in self.timed_plans_for_day(day):
                self.grid.add_block(plan, start_dt, end_dt)
        self.grid.position_blocks()

    def refresh_all_day_row(self) -> None:
        """종일 일정 표시 행을 다시 그립니다."""
        clear_layout(self.all_day_layout)
        seen: set[str] = set()
        chips: list[dict] = []
        for day in self.days:
            for plan in self.all_day_plans_for_day(day):
                key = str(plan.get("id", ""))
                if key in seen:
                    continue
                seen.add(key)
                chips.append(plan)
        if not chips:
            self.all_day_row.setVisible(False)
            return
        self.all_day_row.setVisible(True)
        label = QLabel(self.tr("plan.all_day", "종일"))
        label.setFont(app_font(7, QFont.Bold))
        label.setStyleSheet(f"color: {self.colors['muted2']};")
        self.all_day_layout.addWidget(label)
        for plan in chips[:6]:
            self.all_day_layout.addWidget(self.make_all_day_chip(plan))
        self.all_day_layout.addStretch()

    def make_all_day_chip(self, plan: dict) -> QPushButton:
        """종일 일정 칩(chip) 위젯을 만듭니다."""
        c = self.colors
        red, green, blue = _hex_to_rgb(plan.get("color", c["accent"]))
        chip = QPushButton(plan.get("title", "") or self.tr("detail.untitled", "(제목 없음)"))
        chip.setCursor(Qt.PointingHandCursor)
        chip.setFixedHeight(24)
        chip.setStyleSheet(
            f"QPushButton {{ background: rgba({red},{green},{blue},0.18); color: {c['text']}; "
            f"border: none; border-left: 3px solid rgb({red},{green},{blue}); border-radius: 6px; "
            "padding: 2px 10px; font-weight: 600; }}"
        )
        start_day = (_parse_dt(plan.get("start", "")) or datetime.now()).date()
        chip.clicked.connect(lambda _checked=False, p=plan, d=start_day: self.edit_plan(p, d))
        return chip

    def refresh_upcoming(self) -> None:
        """다가오는 일정 목록을 다시 그립니다."""
        if not hasattr(self, "upcoming_box"):
            return
        clear_layout(self.upcoming_box)
        rows = self.upcoming_plans()
        if hasattr(self, "upcoming_badge"):
            self.upcoming_badge.setText(self.tr("detail.upcoming.count", "{count}건", count=len(rows)))
        if not rows:
            empty = QLabel(self.tr("detail.upcoming.empty", "예정된 일정이 없습니다."))
            empty.setWordWrap(True)
            empty.setStyleSheet(f"color: {self.colors['muted2']};")
            self.upcoming_box.addWidget(empty)
            return
        for plan, start_dt in rows:
            self.upcoming_box.addWidget(self.make_upcoming_row(plan, start_dt))

    def make_upcoming_row(self, plan: dict, start_dt: datetime) -> QWidget:
        """다가오는 일정 목록의 한 줄 위젯을 만듭니다."""
        c = self.colors
        red, green, blue = _hex_to_rgb(plan.get("color", c["accent"]))
        row = QWidget()
        row.setCursor(Qt.PointingHandCursor)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        dot = QLabel()
        dot.setFixedSize(7, 7)
        dot.setStyleSheet(f"background: rgb({red},{green},{blue}); border-radius: 3px;")
        wrapper = QVBoxLayout()
        wrapper.setContentsMargins(0, 4, 0, 0)
        wrapper.addWidget(dot)
        wrapper.addStretch()
        texts = QVBoxLayout()
        texts.setContentsMargins(0, 0, 0, 0)
        texts.setSpacing(1)
        title = QLabel(plan.get("title", "") or self.tr("detail.untitled", "(제목 없음)"))
        title.setFont(app_font(10, QFont.Bold))
        title.setStyleSheet(f"color: {c['text_soft']}; background: transparent;")
        when = QLabel(self.upcoming_when_text(start_dt, plan.get("kind") == "long"))
        when.setFont(app_font(8))
        when.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        texts.addWidget(title)
        texts.addWidget(when)
        layout.addLayout(wrapper)
        layout.addLayout(texts, 1)
        start_day = start_dt.date()
        row.mousePressEvent = lambda _event, p=plan, d=start_day: self.edit_plan(p, d)  # type: ignore[assignment]
        return row

    def upcoming_when_text(self, start_dt: datetime, all_day: bool) -> str:
        """다가오는 일정의 상대적 시점 문자열을 만듭니다."""
        day = start_dt.date()
        today = date.today()
        if day == today:
            day_text = self.tr("detail.when.today", "오늘")
        elif day == today + timedelta(days=1):
            day_text = self.tr("detail.when.tomorrow", "내일")
        else:
            day_text = self.tr("detail.when.date", "{month:02}.{day:02}", month=day.month, day=day.day)
        if all_day:
            return day_text
        return self.tr("detail.when.format", "{day} · {time}", day=day_text, time=f"{start_dt:%H:%M}")
