"""Detail-schedule 창의 "설정" 섹션 믹스인 (R4-4a — SettingsWindow의 4페이지 이식).

허브 설정 섹션 = `SettingsWindow`의 프로그램/테마/연동/정보 4페이지를 그대로 옮긴 것이다.
컨트롤 위젯 빌더(스위치/콤보/슬라이더/카드/액션 버튼)와 저장 콜백의 실제 로직(백업/복원/
내보내기, 테마·언어·폰트·투명도·달력 모양·핀 모드·단축키·공휴일·자동 실행)은
`chronofox.windows.settings_window.SettingsControlsMixin`/`SettingsActionsMixin`을 그대로
상속해 재사용한다(H-D3) — `AlarmsSectionMixin`이 `ClockAlarmMixin`을 그대로 상속한 것과
같은 패턴이다. 이 섹션이 새로 정의하는 것은 딱 두 가지뿐이다:

1. **위젯 배치**: `SettingsWindow`의 독립 사이드바(4개 아이콘 버튼) 대신, 알람 섹션의
   보조 탭(시간/스톱워치/타이머)과 동일한 패턴으로 본문 안에 작은 탭 바 + `QStackedWidget`
   4페이지를 둔다(H1 각주: "허브 사이드바 안에 또 사이드바를 두지 않는다").
2. **저장 콜백의 host 전용 부분**: `set_theme`/`set_calendar_style`/`set_language`/
   `set_font_family`는 `SettingsWindow`처럼 `settings_geometry`를 저장하거나 자신의 창
   제목을 다시 그리지 않는다 — 허브는 그 대신 `self.app.apply_theme()`/`apply_language()`
   /`apply_font_family()`가 `self.app.detail_window`(이 허브 자신)를 포함해 전체를
   재적용하므로(desktop_note_calendar.py), 그 fan-out 한 호출로 이 섹션도 함께
   재빌드된다. 이것이 "테마 전환 시 섹션이 죽지 않는지" 요건의 실제 메커니즘이다 —
   `DetailScheduleWindow.apply_theme()`가 `self.build_ui()`로 허브 전체를 새로 그리므로,
   이 섹션은 자체 `apply_theme()`/`refresh_theme_styles()`가 필요 없다(다른 섹션들과 동일).

QSS 색상은 `SettingsWindow`(별도 `settings_panel_colors` 팔레트, `settings_input`/
`settings_sidebar` 같은 전용 키를 가진다)와 허브(`detail_schedule.palette.design_palette`,
그런 키가 없다)가 서로 다르므로, `settings_input_style()`/`settings_opacity_slider_style()`/
`settings_action_button_style()` 세 QSS 훅만 이 섹션이 따로 구현한다 — 공유 믹스인의
위젯 빌더들은 이 훅을 이름으로만 호출하므로(다형성) 값을 몰라도 된다. 메서드 이름은
`clock/styles.py ClockStyleMixin.input_style()`과 겹치지 않도록 `settings_` 접두를 쓴다
(AlarmsSectionMixin이 이미 `input_style`을 쓰고 있어 그 이름을 그대로 재사용하면 두
섹션 중 하나의 스타일이 다른 쪽에 가려진다 — MRO에서 동일 이름 메서드는 하나만 남는다).

REQUIRED attributes/메서드 (DetailScheduleWindow 코어 + 다른 믹스인이 제공):
- `self.app`, `self.colors`(dict), `self.section`(str), `self.pending_target`
- `self.tr(key, fallback, **kwargs)` (TrMixin)
- `self.icon_only_button(icon, handler)`, `self.close()`, `self.scroll_style()`,
  `self.build_ui()`, `self.window_title_text()` (layout.py/window.py 코어)
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.app_constants import APP_DIR, APP_NAME, APP_NAME_EN, APP_VERSION, DEFAULT_FONT_FAMILY
from chronofox.ui.app_i18n import normalize_language
from chronofox.ui.app_styles import normalized_calendar_style
from chronofox.ui.app_ui import app_font
from chronofox.windows.settings_window import SettingCard, SettingsActionsMixin, SettingsControlsMixin

# 본문 안 탭 4개. kind는 show_section("settings", "page:<kind>")의 target 어휘와 같다(H-D8).
# 라벨 키는 SettingsWindow의 기존 settings.page.* 키를 그대로 재사용한다(locale 신규 추가 0).
SETTINGS_TAB_ITEMS: list[tuple[str, str, str]] = [
    ("program", "settings.page.program", "프로그램 설정"),
    ("theme", "settings.page.theme", "테마"),
    ("integration", "settings.page.integration", "연동"),
    ("info", "settings.page.info", "정보"),
]


class SettingsSectionMixin(SettingsControlsMixin, SettingsActionsMixin):
    """설정 4페이지(프로그램/테마/연동/정보)를 본문 내부 탭으로 담당합니다."""

    def show_settings_view(self) -> None:
        """호환 위임: 기존 호출부가 그대로 동작하도록 show_section("settings")를 부른다."""
        self.show_section("settings")

    # top bar ---------------------------------------------------------------
    def build_settings_top_bar(self) -> QHBoxLayout:
        """설정 화면 상단 바(제목 + 닫기)를 구성합니다."""
        c = self.colors
        self.view_buttons = {}
        bar = QHBoxLayout()
        bar.setSpacing(12)
        title = QLabel(self.tr("detail.nav.settings", "설정"))
        title.setFont(app_font(15, QFont.Bold))
        title.setStyleSheet(f"color: {c['text']};")
        close_button = self.icon_only_button("close", self.close)
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(close_button)
        return bar

    # main view ---------------------------------------------------------------
    def build_settings_view(self) -> QWidget:
        """탭 바(프로그램/테마/연동/정보) + 각 페이지를 구성합니다."""
        self._reset_settings_control_state()

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        nav_row = QHBoxLayout()
        nav_row.setSpacing(6)
        self.settings_tab_buttons: dict[str, QPushButton] = {}
        for key, label_key, fallback in SETTINGS_TAB_ITEMS:
            button = QPushButton(self.tr(label_key, fallback))
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedHeight(30)
            button.clicked.connect(lambda _checked=False, k=key: self.switch_settings_tab(k))
            self.settings_tab_buttons[key] = button
            nav_row.addWidget(button)
        nav_row.addStretch()
        layout.addLayout(nav_row)

        self.settings_tab_stack = QStackedWidget()
        self.settings_tab_stack.addWidget(self._build_settings_program_page())
        self.settings_tab_stack.addWidget(self._build_settings_theme_page())
        self.settings_tab_stack.addWidget(self._build_settings_integration_page())
        self.settings_tab_stack.addWidget(self._build_settings_info_page())
        layout.addWidget(self.settings_tab_stack, 1)

        self.switch_settings_tab(getattr(self, "_settings_tab", "program"))
        self.consume_settings_target()
        return container

    def _reset_settings_control_state(self) -> None:
        """설정 섹션이 재빌드될 때마다(테마/언어 전환 등) 이전 위젯 참조가 남지 않도록
        컨트롤 추적 목록을 새로 만든다 — SettingsWindow.build_ui()의 clear()와 달리 이
        섹션은 build_ui() 자체가 매번 새 위젯 트리를 만들므로(layout.py), 목록도 통째로
        새로 시작하는 편이 더 단순하고 안전하다."""
        self.setting_cards: list[SettingCard] = []
        self.info_labels: list[QLabel] = []
        self.theme_buttons: list = []
        self.calendar_style_combo: QComboBox | None = None
        self.combo_boxes: list[QComboBox] = []
        self.switches: list = []
        self.opacity_widgets: list[QWidget] = []
        self.opacity_sliders: list[QSlider] = []
        self.opacity_spins: list[QSpinBox] = []
        self.font_combo_box: QComboBox | None = None
        self.language_combo_box: QComboBox | None = None

    def consume_settings_target(self) -> None:
        """`show_section("settings", target)`로 넘어온 대상을 처리합니다(H-D8).

        target이 `"page:program"`/`"page:theme"`/`"page:integration"`/`"page:info"`면
        해당 탭으로 전환한다. 그 밖의 값은 무시한다(설정 항목 단위 딥링크는 비범위)."""
        target = self.pending_target
        if not target:
            return
        target = str(target)
        if target.startswith("page:"):
            self.switch_settings_tab(target.removeprefix("page:"))

    def switch_settings_tab(self, key: str) -> None:
        """본문 내부 탭(프로그램/테마/연동/정보)을 전환합니다."""
        names = [name for name, _label_key, _fallback in SETTINGS_TAB_ITEMS]
        index = names.index(key) if key in names else 0
        self._settings_tab = names[index]
        if hasattr(self, "settings_tab_stack"):
            self.settings_tab_stack.setCurrentIndex(index)
        for name, button in getattr(self, "settings_tab_buttons", {}).items():
            button.setStyleSheet(self.settings_tab_style(name == self._settings_tab))
        if self._settings_tab == "theme":
            # SettingsWindow.switch_settings_page()의 지연 폰트 목록 채움과 동일한 관용구
            # (populate_font_combo()는 이미 채워졌으면 아무 것도 하지 않는다).
            self.populate_font_combo()

    def settings_tab_style(self, active: bool) -> str:
        """본문 내부 탭 버튼 QSS 스타일 문자열을 만듭니다(알람 섹션 보조 탭과 동일한 톤)."""
        c = self.colors
        # padding이 없으면 QPushButton의 sizeHint가 글자 폭과 같아져 알약 배경이 글자에
        # 딱 붙고 마지막 글자가 잘려 보인다("테마" → "테ㅁ"). 알람 섹션의 보조 탭은
        # 균등 폭으로 늘어나 이 문제가 없지만 이쪽은 sizeHint 폭이라 패딩이 필요하다.
        if active:
            return (
                f"QPushButton {{ background: {c['accent']}; color: #ffffff; border: none; "
                "border-radius: 8px; padding: 0 12px; font-weight: 700; }}"
            )
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 8px; padding: 0 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {c['text']}; }}"
        )

    # pages -------------------------------------------------------------
    def _settings_page(self, widgets: list[QWidget]) -> QScrollArea:
        """설정 카드 목록을 스크롤 가능한 탭 페이지 하나로 구성합니다(허브 공용
        `self.scroll_style()` 재사용 — SettingsWindow.page()와 같은 구조, 스크롤바
        QSS만 허브 것을 쓴다)."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(self.scroll_style())
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 4, 4, 0)
        content_layout.setSpacing(14)
        for widget in widgets:
            content_layout.addWidget(widget)
        content_layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def _build_settings_program_page(self) -> QScrollArea:
        """프로그램 설정 탭: 투명도/공휴일 표시/자동 실행/빠른 입력 단축키."""
        return self._settings_page([
            self.setting_card(self.tr("settings.program.opacity.title", "투명도"), self.tr("settings.program.opacity.desc", "달력이 바탕화면에 보이는 정도를 조절합니다"), self.opacity_control()),
            self.setting_card(self.tr("settings.program.holiday.title", "공휴일 표시"), self.tr("settings.program.holiday.desc", "주요 공휴일과 대체공휴일을 달력에 표시합니다"), self.holiday_control()),
            self.setting_card(self.tr("settings.program.startup.title", "Windows 시작 시 자동 실행"), self.tr("settings.program.startup.desc", "컴퓨터를 켤 때 크로노폭스를 자동으로 엽니다"), self.startup_control()),
            self.setting_card(self.tr("settings.program.quick_hotkey.title", "빠른 입력 단축키"), self.tr("settings.program.quick_hotkey.desc", "어디서든 이 조합으로 빠른 입력 창을 엽니다"), self.quick_hotkey_control()),
        ])

    def _build_settings_theme_page(self) -> QScrollArea:
        """테마 탭: 테마 모드/달력 모양/기본 폰트/언어/핀 모드."""
        return self._settings_page([
            self.setting_card(self.tr("settings.theme.mode.title", "테마"), self.tr("settings.theme.mode.desc", "크로노폭스의 색상 모드를 선택합니다"), self.theme_selector()),
            self.setting_card(self.tr("settings.theme.calendar_style.title", "달력 모양"), self.tr("settings.theme.calendar_style.desc", "메인 달력의 날짜 칸 디자인을 선택합니다"), self.calendar_style_selector()),
            self.setting_card(self.tr("settings.theme.font.title", "기본 폰트"), self.tr("settings.theme.font.desc", "앱에서 사용할 글꼴을 선택합니다"), self.font_combo()),
            self.setting_card(self.tr("settings.theme.language.title", "언어"), self.tr("settings.theme.language.desc", "앱에서 사용할 표시 언어를 선택합니다"), self.language_combo()),
            self.setting_card(self.tr("pin.settings.title", "핀 모드"), self.tr("pin.settings.desc", "달력의 위치와 크기를 고정하고 항상 다른 창 아래에 표시합니다"), self.pin_mode_control()),
        ])

    def _build_settings_integration_page(self) -> QScrollArea:
        """연동 탭: 로컬 백업/백업 복원/캘린더 내보내기/클라우드 연동(준비 중)."""
        return self._settings_page([
            self.setting_card(self.tr("settings.integration.backup.title", "로컬 백업"), self.tr("settings.integration.backup.desc", "설정, 일정, 계획, 해야 할 일, 메모를 zip 파일로 저장합니다"), self.action_button(self.tr("settings.action.backup", "백업 만들기"), self.create_backup)),
            self.setting_card(self.tr("settings.integration.restore.title", "백업 복원"), self.tr("settings.integration.restore.desc", "이전에 만든 zip 백업 파일에서 설정, 일정, 메모를 되돌립니다"), self.action_button(self.tr("settings.action.restore", "백업 복원"), self.restore_backup_from_file)),
            self.setting_card(self.tr("settings.integration.export.title", "캘린더 내보내기"), self.tr("settings.integration.export.desc", "Google Calendar와 Microsoft Outlook에서 가져올 수 있는 파일을 만듭니다"), self.action_button(self.tr("settings.action.ics", "ICS 만들기"), self.export_calendar_file)),
            self.setting_card(self.tr("settings.integration.cloud.title", "클라우드 연동"), self.tr("settings.integration.cloud.desc", "동기화와 가져오기 기능은 다음 단계에서 추가할 예정입니다"), self.info_label(self.tr("settings.info.pending", "준비 중"))),
        ])

    def _build_settings_info_page(self) -> QScrollArea:
        """정보 탭: 프로그램/데이터 위치/업데이트 확인(준비 중)."""
        return self._settings_page([
            self.setting_card(self.tr("settings.info.program.title", "프로그램"), APP_NAME, self.info_label(f"{APP_NAME_EN} v{APP_VERSION}")),
            self.setting_card(self.tr("settings.info.data.title", "데이터 위치"), str(APP_DIR), self.info_label(self.tr("settings.info.local", "로컬 저장"))),
            self.setting_card(
                self.tr("settings.info.update.title", "업데이트"),
                self.tr("settings.info.update.desc", "새 버전 확인 기능은 다음 단계에서 추가할 예정입니다"),
                self.action_button(self.tr("settings.action.check_update", "업데이트 확인"), self.show_update_placeholder),
            ),
        ])

    # save callbacks (host-specific: 지오메트리 키/창 제목이 SettingsWindow와 다르다) -----
    def set_theme(self, mode: str, _checked: bool = False) -> None:
        """테마 모드를 바꾸고 앱 전역에 반영합니다. `app.apply_theme()`가
        `self.app.detail_window`(이 허브 자신)를 포함해 재적용하므로 이 섹션은 별도
        재빌드를 직접 호출하지 않는다."""
        if self.app.store.get("theme_mode", "system") == mode:
            return
        self.app.store.set("theme_mode", mode)
        self.app.save()
        self.app.apply_theme()

    def set_calendar_style(self, style: str, _checked: bool = False) -> None:
        """메인 달력 디자인을 바꾸고 앱 전역에 반영합니다."""
        if normalized_calendar_style(self.app.store) == normalized_calendar_style({"calendar_style": style}):
            return
        if hasattr(self.app, "set_calendar_style"):
            self.app.set_calendar_style(style)
        else:
            self.app.store.set("calendar_style", style)
            self.app.save()
            self.app.apply_theme()

    def set_language(self, language: str) -> None:
        """언어를 바꾸고 화면에 반영합니다. 허브 자신은 즉시 다시 그리고(다른 섹션들과
        동일하게 build_ui()가 창 제목도 함께 갱신한다), 나머지 열린 창은 app.apply_language()
        fan-out이 처리한다(source=self로 이 창의 중복 재적용을 막는다)."""
        normalized = normalize_language(language)
        if self.app.store.get("language", "ko") == normalized:
            return
        self.app.store.set("language", normalized)
        self.app.save()
        self.setWindowTitle(self.window_title_text())
        self.build_ui()
        if hasattr(self.app, "apply_language"):
            self.app.apply_language(source=self)

    def set_font_family(self, family: str) -> None:
        """기본 폰트 패밀리를 바꾸고 앱 전역에 반영합니다. `app.apply_font_family()`가
        `self.app.detail_window.apply_theme()`를 호출해 이 섹션도 함께 재빌드된다."""
        if not family or self.app.store.get("font_family", DEFAULT_FONT_FAMILY) == family:
            return
        self.app.store.set("font_family", family)
        self.app.save()
        self.app.apply_font_family(family)

    # QSS 훅(host별 팔레트가 달라 이 섹션만의 구현을 둔다) -------------------------
    def settings_input_style(self) -> str:
        """콤보/스핀박스 QSS 스타일 문자열을 만듭니다(허브 팔레트 키 기준)."""
        c = self.colors
        return (
            f"QComboBox, QSpinBox, QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 10px; padding: 6px 26px 6px 10px; }}"
            f"QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            "QComboBox::drop-down { border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: top right; }"
            "QComboBox::down-arrow { image: none; width: 0; height: 0; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def settings_opacity_slider_style(self) -> str:
        """투명도 슬라이더 QSS 스타일 문자열을 만듭니다(허브 팔레트 키 기준)."""
        c = self.colors
        return (
            "QSlider { background: transparent; border: none; }"
            f"QSlider::groove:horizontal {{ height: 3px; background: {c['panel2']}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: white; border: 2px solid {c['accent']}; width: 16px; height: 16px; margin: -8px 0; border-radius: 9px; }}"
        )

    def settings_action_button_style(self) -> str:
        """설정 화면 액션 버튼 QSS 스타일 문자열을 만듭니다(허브 팔레트 키 기준)."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['accent']}; color: white; border: none; "
            "border-radius: 10px; padding: 8px 16px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c.get('accent_hover', c['accent'])}; }}"
        )
