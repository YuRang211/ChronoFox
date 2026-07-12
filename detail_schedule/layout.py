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
  `self.add_plan`, `self.edit_plan`, `self.show_calendar_view` (window.py 코어)
- 스타일: `self.scroll_style`, `self.view_button_style` (window.py 코어)
- 섹션 믹스인: `self.show_tasks_view`/`self.build_tasks_view`/`self.build_tasks_top_bar`
  (TasksSectionMixin), `self.show_archive_view`/`self.build_archive_view`/
  `self.build_archive_top_bar`/`self.show_coming_soon`/`self.show_suggest`
  (ArchiveSectionMixin), `self.build_month_view` (MonthViewMixin)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app_constants import APP_NAME_EN
from app_ui import app_font, clear_layout

from .widgets import GUTTER, HOUR_HEIGHT, DayHeader, MiniCalendar, TimeGrid, _hex_to_rgb, _parse_dt, stroke_icon


class DetailLayoutMixin:
    """사이드바/탑바/시간뷰/사이드패널 위젯 구성과 그 새로고침을 담당합니다."""

    # build ------------------------------------------------------------
    def build_ui(self) -> None:
        """창/페이지의 위젯 레이아웃을 구성합니다."""
        existing = self.layout()
        if existing is None:
            root = QHBoxLayout(self)
        else:
            clear_layout(existing)
            root = existing
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # 이전 빌드의 위젯 참조를 비워 삭제된 위젯을 다시 건드리지 않도록 한다.
        for attr in ("grid", "day_header", "all_day_row", "all_day_layout", "empty_hint", "scroll_area", "tasks_box", "archive_box"):
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
        frame.setFixedWidth(174)
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

        actions = {
            "calendar": self.show_calendar_view,
            "tasks": self.show_tasks_view,
            "archive": self.show_archive_view,
            "focus": self.show_coming_soon,
            "analytics": self.show_coming_soon,
        }
        active_kind = self.section if self.section in {"calendar", "tasks", "archive"} else "calendar"
        for kind, label_key, fallback, icon in self.NAV_ITEMS:
            disabled = kind in self.DISABLED_NAV
            active = (kind == active_kind) and not disabled
            button = self.make_nav_button(self.tr(label_key, fallback), icon, active, disabled=disabled)
            handler = actions.get(kind)
            if handler is not None:
                button.clicked.connect(lambda _checked=False, fn=handler: fn())
            layout.addWidget(button)

        layout.addStretch()
        suggest = QPushButton(self.tr("detail.suggest", "건의하기"))
        suggest.setCursor(Qt.PointingHandCursor)
        suggest.setFixedHeight(34)
        suggest.clicked.connect(self.show_suggest)
        suggest.setStyleSheet(
            f"QPushButton {{ background: {c['upgrade']}; color: #1a1a22; border: none; border-radius: 9px; "
            "font-weight: 700; }}"
        )
        layout.addWidget(suggest)
        layout.addSpacing(8)
        for label_key, fallback, icon, handler in (
            ("detail.nav.help", "도움말", "help", None),
            ("detail.nav.settings", "설정", "settings", getattr(self.app, "open_settings", None)),
        ):
            button = self.make_nav_button(self.tr(label_key, fallback), icon, False)
            if handler is not None:
                button.clicked.connect(lambda _checked=False, fn=handler: fn())
            layout.addWidget(button)
        return frame

    def make_nav_button(self, label: str, icon: str, active: bool, disabled: bool = False) -> QPushButton:
        """사이드바 내비게이션 버튼을 만듭니다."""
        c = self.colors
        button = QPushButton(f"  {label}")
        button.setCursor(Qt.PointingHandCursor)
        button.setFixedHeight(36)
        if disabled:
            color = c["fainter"]
            button.setIcon(QIcon(stroke_icon(icon, color, 16)))
            button.setIconSize(QSize(16, 16))
            button.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {color}; border: none; border-radius: 9px; "
                "text-align: left; padding: 0 11px; font-size: 12px; font-weight: 500; }}"
            )
            return button
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
        layout.addLayout(self.build_top_bar())
        if self.section == "tasks":
            layout.addWidget(self.build_tasks_view(), 1)
        elif self.section == "archive":
            layout.addWidget(self.build_archive_view(), 1)
        elif self.view_mode == "month":
            layout.addWidget(self.build_month_view(), 1)
        else:
            layout.addWidget(self.build_time_view(), 1)
        return frame

    def build_time_view(self) -> QWidget:
        """시간대별(주간) 캘린더 뷰를 구성합니다."""
        c = self.colors
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
        self.empty_hint = QLabel(self.tr("detail.empty", "이 기간에 시간 일정이 없습니다."), self.grid)
        self.empty_hint.setFont(app_font(10))
        self.empty_hint.setStyleSheet(f"color: {c['muted2']}; background: transparent;")
        self.empty_hint.move(GUTTER + 18, int(8 * HOUR_HEIGHT))
        self.empty_hint.adjustSize()
        self.empty_hint.hide()
        self.scroll_area.setWidget(self.grid)
        layout.addWidget(self.scroll_area, 1)
        return container

    def build_top_bar(self) -> QHBoxLayout:
        """메인 영역 상단 바를 구성합니다."""
        if self.section == "tasks":
            return self.build_tasks_top_bar()
        if self.section == "archive":
            return self.build_archive_top_bar()
        c = self.colors
        bar = QHBoxLayout()
        bar.setSpacing(12)

        search = QPushButton(f"   {self.tr('detail.search', '일정 검색...')}")
        search.setCursor(Qt.PointingHandCursor)
        search.setIcon(QIcon(stroke_icon("search", c["muted"], 15)))
        search.setIconSize(QSize(15, 15))
        search.setFixedHeight(30)
        search.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {c['muted2']}; border: none; "
            "text-align: left; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )
        search.clicked.connect(lambda: self.app.open_search())

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

        bell = QLabel()
        bell.setPixmap(stroke_icon("bell", c["muted"], 17))
        close_button = self.icon_only_button("close", self.close)

        bar.addWidget(search, 1)
        bar.addLayout(view_row)
        bar.addWidget(prev_button)
        bar.addWidget(today_button)
        bar.addWidget(next_button)
        bar.addWidget(add_button)
        bar.addWidget(bell)
        bar.addWidget(close_button)
        return bar

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
        # — 예전에는 mini_calendar.sync_anchor()/refresh_upcoming()/trend_value 갱신이
        # 여기 흩어져 있었는데, build_glance_panel()이 그 내용을 모두 흡수했다.
        self.refresh_side_panel()

    def refresh_grid_blocks(self) -> None:
        """시간대 그리드의 일정 블록들을 다시 그립니다."""
        self.grid.clear_blocks()
        has_event = False
        for day in self.days:
            for plan, start_dt, end_dt in self.timed_plans_for_day(day):
                self.grid.add_block(plan, start_dt, end_dt)
                has_event = True
        self.grid.position_blocks()
        if hasattr(self, "empty_hint"):
            self.empty_hint.setVisible(not has_event)

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
