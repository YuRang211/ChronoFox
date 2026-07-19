"""테마/폰트/언어/백업·복원 같은 사용자 설정을 편집하는 SettingsWindow를 구현하는 모듈."""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QByteArray, QProcess, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.app_constants import (
    APP_DIR,
    APP_NAME,
    APP_NAME_EN,
    APP_VERSION,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_LABEL,
    DEFAULT_SETTINGS_GEOMETRY,
    REPO_ROOT,
    SETTINGS_ICON_DIR,
)
from chronofox.core.app_hotkey import DEFAULT_QUICK_HOTKEY, format_hotkey_display
from chronofox.core.app_restore import BackupInfo, inspect_backup, restore_backup
from chronofox.ui.app_design import settings_panel_colors
from chronofox.ui.app_i18n import SUPPORTED_LANGUAGES, TrMixin, normalize_language
from chronofox.ui.app_styles import fancy_scrollbar_style
from chronofox.ui.app_ui import app_font, clear_layout, geometry_string, parse_geometry, system_font_families
from chronofox.ui.app_widgets import ArrowComboBox, CalendarStyleButton, IconButton, RoundedWindow, Switch, ThemeButton

if TYPE_CHECKING:
    from chronofox.windows.desktop_note_calendar import FoxCalendarApp


SETTINGS_NAV_ICON_FILES = {
    "program": SETTINGS_ICON_DIR / "program.svg",
    "theme": SETTINGS_ICON_DIR / "theme.svg",
    "integration": SETTINGS_ICON_DIR / "integration.svg",
    "info": SETTINGS_ICON_DIR / "info.svg",
}


class SettingCard(QFrame):
    """A reusable settings row that owns its title/description styling."""

    def __init__(self, title: str, desc: str, control: QWidget, colors: dict[str, str]) -> None:
        super().__init__()
        self.colors = colors
        self.title_label = QLabel(title)
        self.desc_label = QLabel(desc)
        self.setObjectName("settingCard")
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(20)
        texts = QVBoxLayout()
        texts.setSpacing(6)
        texts.addWidget(self.title_label)
        texts.addWidget(self.desc_label)
        layout.addLayout(texts, 1)
        layout.addWidget(control)
        self.setMinimumHeight(84)

        self.apply_font()
        self.apply_theme(colors)

    def apply_theme(self, colors: dict[str, str]) -> None:
        """현재 테마 색상을 위젯 스타일에 다시 적용합니다."""
        self.colors = colors
        self.setStyleSheet(
            "QFrame#settingCard { background: transparent; border: none; }"
            "QFrame#settingCard QLabel { border: none; background: transparent; }"
        )
        self.desc_label.setStyleSheet(f"color: {colors['muted']};")

    def apply_font(self) -> None:
        """현재 폰트 설정을 위젯에 적용합니다."""
        self.title_label.setFont(app_font(11, QFont.Bold))
        self.desc_label.setFont(app_font())


class SettingsNavButton(QPushButton):
    """Icon and label sidebar entry for the Stitch-style settings surface."""

    _svg_cache: dict[tuple[str, str], QSvgRenderer] = {}

    def __init__(self, row: int, kind: str, label: str, colors: dict[str, str]) -> None:
        super().__init__()
        self.row = row
        self.kind = kind
        self.label = label
        self.colors = colors
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)
        self.setStyleSheet("QPushButton { border: none; background: transparent; text-align: left; }")

    def set_colors(self, colors: dict[str, str]) -> None:
        """위젯이 사용할 색상 팔레트를 갱신합니다."""
        self.colors = colors
        self.update()

    def paintEvent(self, _event) -> None:
        c = self.colors
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        active = self.isChecked()
        rect = self.rect().adjusted(0, 1, -1, -1)
        if active or self.underMouse():
            bg = QColor(c["accent"] if active else c["settings_sidebar_hover"])
            if not active:
                bg.setAlpha(130)
            painter.setPen(Qt.NoPen)
            painter.setBrush(bg)
            painter.drawRoundedRect(rect, 10, 10)

        icon_color = QColor("white" if active else c["muted"])
        text_color = QColor("white" if active else c["text"])
        self.render_icon(painter, icon_color)
        painter.setPen(text_color)
        painter.setFont(app_font(8, QFont.Bold))
        painter.drawText(QRect(40, 0, self.width() - 44, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.label)

    def render_icon(self, painter: QPainter, color: QColor) -> None:
        """네비게이션 아이콘을 현재 테마 색상으로 그립니다."""
        renderer = self.svg_renderer(color)
        if renderer is None:
            return
        renderer.render(painter, QRectF(12, 9, 20, 20))

    def svg_renderer(self, color: QColor) -> QSvgRenderer | None:
        """아이콘 SVG 파일을 캐시된 QSvgRenderer로 반환합니다."""
        icon_path = SETTINGS_NAV_ICON_FILES.get(self.kind)
        if icon_path is None or not icon_path.exists():
            return None
        color_name = color.name()
        cache_key = (self.kind, color_name)
        renderer = self._svg_cache.get(cache_key)
        if renderer is not None:
            return renderer
        svg = icon_path.read_text(encoding="utf-8").replace("#ICON_COLOR#", color_name)
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        self._svg_cache[cache_key] = renderer
        return renderer


class SettingsWindow(TrMixin, RoundedWindow):
    """테마, 투명도, 자동실행 같은 사용자 설정을 바꾸는 창입니다."""

    PAGE_DESC_KEYS = (
        ("settings.page.program.desc", "크로노폭스가 바탕화면에서 동작하는 방식을 조정합니다."),
        ("settings.page.theme.desc", "색상, 메모 테마, 글꼴과 표시 언어를 조정합니다."),
        ("settings.page.integration.desc", "백업, 내보내기와 다음 단계의 연동 기능을 관리합니다."),
        ("settings.page.info.desc", "앱 버전과 로컬 데이터 위치를 확인합니다."),
    )

    def __init__(self, app: FoxCalendarApp) -> None:
        super().__init__(settings_panel_colors(app.dialog_colors()), radius=24)
        self.app = app
        self.current_page = 0
        self.font_combo_box: QComboBox | None = None
        self.setting_cards: list[SettingCard] = []
        self.info_labels: list[QLabel] = []
        self.theme_buttons: list[ThemeButton] = []
        self.calendar_style_buttons: list[CalendarStyleButton] = []
        self.combo_boxes: list[QComboBox] = []
        self.switches: list[Switch] = []
        self.scroll_areas: list[QScrollArea] = []
        self.scroll_contents: list[QWidget] = []
        self.opacity_widgets: list[QWidget] = []
        self.opacity_sliders: list[QSlider] = []
        self.opacity_spins: list[QSpinBox] = []
        self.sidebar_buttons: list[SettingsNavButton] = []
        self.language_combo_box: QComboBox | None = None
        self.setWindowTitle(self.tr("settings.window.title", f"{APP_NAME} 설정"))
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("settings_geometry", DEFAULT_SETTINGS_GEOMETRY), (860, 520, 260, 130))
        width = max(width, 900)
        height = max(height, 560)
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(860, 540)
        self.build_ui()

    def build_ui(self) -> None:
        """설정창을 왼쪽 사이드바와 오른쪽 설정 페이지로 구성합니다."""
        c = self.colors
        self.setting_cards.clear()
        self.info_labels.clear()
        self.theme_buttons.clear()
        self.calendar_style_buttons.clear()
        self.combo_boxes.clear()
        self.switches.clear()
        self.scroll_areas.clear()
        self.scroll_contents.clear()
        self.opacity_widgets.clear()
        self.opacity_sliders.clear()
        self.opacity_spins.clear()
        self.sidebar_buttons.clear()
        existing = self.layout()
        if existing is None:
            layout = QHBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(220)
        self.sidebar_frame.setStyleSheet(
            f"QFrame {{ background: {c['settings_sidebar']}; border: none; border-top-left-radius: {self.radius}px; "
            f"border-bottom-left-radius: {self.radius}px; }}"
        )
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(24, 26, 18, 22)
        sidebar_layout.setSpacing(10)
        self.side_title = QLabel(self.tr("settings.sidebar.title", "Settings"))
        self.side_title.setFont(app_font(14, QFont.Bold))
        self.side_title.setStyleSheet(f"color: {c['accent']};")
        nav_items = (
            ("program", self.tr("settings.page.program", "프로그램 설정")),
            ("theme", self.tr("settings.page.theme", "테마")),
            ("integration", self.tr("settings.page.integration", "연동")),
            ("info", self.tr("settings.page.info", "정보")),
        )
        for row, (kind, label) in enumerate(nav_items):
            button = SettingsNavButton(row, kind, label, c)
            button.clicked.connect(partial(self.switch_settings_page, row))
            self.sidebar_buttons.append(button)

        self.page_labels = [
            self.tr("settings.page.program", "프로그램 설정"),
            self.tr("settings.page.theme", "테마"),
            self.tr("settings.page.integration", "연동"),
            self.tr("settings.page.info", "정보"),
        ]
        version_label = QLabel(self.tr("settings.version.label", "현재 버전"))
        version_label.setFont(app_font(7, QFont.Bold))
        version_label.setStyleSheet(f"color: {c['muted']};")
        self.version_value = QLabel(f"{APP_NAME_EN} v{APP_VERSION}")
        self.version_value.setFont(app_font())
        self.version_value.setStyleSheet(f"color: {c['accent']};")
        sidebar_layout.addWidget(self.side_title)
        sidebar_layout.addSpacing(12)
        for button in self.sidebar_buttons:
            sidebar_layout.addWidget(button)
        sidebar_layout.addStretch()
        sidebar_layout.addWidget(version_label)
        sidebar_layout.addWidget(self.version_value)
        sidebar_layout.addSpacing(6)

        self.content_frame = QFrame()
        self.content_frame.setStyleSheet(
            f"QFrame {{ background: {c['bg']}; border: none; border-top-right-radius: {self.radius}px; "
            f"border-bottom-right-radius: {self.radius}px; }}"
        )
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(26, 26, 26, 24)
        content_layout.setSpacing(16)

        header = QHBoxLayout()
        title_stack = QVBoxLayout()
        title_stack.setSpacing(5)
        self.page_title = QLabel("")
        self.page_title.setFont(app_font(13, QFont.Bold))
        self.page_desc = QLabel("")
        self.page_desc.setFont(app_font())
        self.page_desc.setStyleSheet(f"color: {c['muted']};")
        title_stack.addWidget(self.page_title)
        title_stack.addWidget(self.page_desc)
        self.close_button = IconButton("close", c)
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.close)
        header.addLayout(title_stack)
        header.addStretch()
        header.setContentsMargins(0, -4, -6, 0)
        header.addWidget(self.close_button)
        content_layout.addLayout(header)

        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self.build_program_page())
        self.page_stack.addWidget(self.build_theme_page())
        self.page_stack.addWidget(self.build_integration_page())
        self.page_stack.addWidget(self.build_info_page())
        content_layout.addWidget(self.page_stack, 1)

        layout.addWidget(self.sidebar_frame)
        layout.addWidget(self.content_frame, 1)
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        self.switch_settings_page(min(self.current_page, len(self.sidebar_buttons) - 1))

    def build_program_page(self) -> QScrollArea:
        """program 페이지를 구성합니다."""
        return self.page(self.tr("settings.page.program", "프로그램 설정"), [
            self.setting_card(self.tr("settings.program.opacity.title", "투명도"), self.tr("settings.program.opacity.desc", "달력이 바탕화면에 보이는 정도를 조절합니다"), self.opacity_control()),
            self.setting_card(self.tr("settings.program.holiday.title", "공휴일 표시"), self.tr("settings.program.holiday.desc", "주요 공휴일과 대체공휴일을 달력에 표시합니다"), self.holiday_control()),
            self.setting_card(self.tr("settings.program.startup.title", "Windows 시작 시 자동 실행"), self.tr("settings.program.startup.desc", "컴퓨터를 켤 때 크로노폭스를 자동으로 엽니다"), self.startup_control()),
            self.setting_card(self.tr("settings.program.quick_hotkey.title", "빠른 입력 단축키"), self.tr("settings.program.quick_hotkey.desc", "어디서든 이 조합으로 빠른 입력 창을 엽니다"), self.quick_hotkey_control()),
        ])

    def build_theme_page(self) -> QScrollArea:
        """테마 페이지를 구성합니다."""
        return self.page(self.tr("settings.page.theme", "테마"), [
            self.setting_card(self.tr("settings.theme.mode.title", "테마"), self.tr("settings.theme.mode.desc", "크로노폭스의 색상 모드를 선택합니다"), self.theme_selector()),
            self.setting_card(self.tr("settings.theme.calendar_style.title", "달력 모양"), self.tr("settings.theme.calendar_style.desc", "메인 달력의 날짜 칸 디자인을 선택합니다"), self.calendar_style_selector()),
            self.setting_card(self.tr("settings.theme.font.title", "기본 폰트"), self.tr("settings.theme.font.desc", "앱에서 사용할 글꼴을 선택합니다"), self.font_combo()),
            self.setting_card(self.tr("settings.theme.language.title", "언어"), self.tr("settings.theme.language.desc", "앱에서 사용할 표시 언어를 선택합니다"), self.language_combo()),
            self.setting_card(self.tr("pin.settings.title", "핀 모드"), self.tr("pin.settings.desc", "달력의 위치와 크기를 고정하고 항상 다른 창 아래에 표시합니다"), self.pin_mode_control()),
        ])

    def build_integration_page(self) -> QScrollArea:
        """integration 페이지를 구성합니다."""
        return self.page(self.tr("settings.page.integration", "연동"), [
            self.setting_card(self.tr("settings.integration.backup.title", "로컬 백업"), self.tr("settings.integration.backup.desc", "설정, 일정, 계획, 해야 할 일, 메모를 zip 파일로 저장합니다"), self.action_button(self.tr("settings.action.backup", "백업 만들기"), self.create_backup)),
            self.setting_card(self.tr("settings.integration.restore.title", "백업 복원"), self.tr("settings.integration.restore.desc", "이전에 만든 zip 백업 파일에서 설정, 일정, 메모를 되돌립니다"), self.action_button(self.tr("settings.action.restore", "백업 복원"), self.restore_backup_from_file)),
            self.setting_card(self.tr("settings.integration.export.title", "캘린더 내보내기"), self.tr("settings.integration.export.desc", "Google Calendar와 Microsoft Outlook에서 가져올 수 있는 파일을 만듭니다"), self.action_button(self.tr("settings.action.ics", "ICS 만들기"), self.export_calendar_file)),
            self.setting_card(self.tr("settings.integration.cloud.title", "클라우드 연동"), self.tr("settings.integration.cloud.desc", "동기화와 가져오기 기능은 다음 단계에서 추가할 예정입니다"), self.info_label(self.tr("settings.info.pending", "준비 중"))),
        ])

    def build_info_page(self) -> QScrollArea:
        """info 페이지를 구성합니다."""
        return self.page(self.tr("settings.page.info", "정보"), [
            self.setting_card(self.tr("settings.info.program.title", "프로그램"), APP_NAME, self.info_label(f"{APP_NAME_EN} v{APP_VERSION}")),
            self.setting_card(self.tr("settings.info.data.title", "데이터 위치"), str(APP_DIR), self.info_label(self.tr("settings.info.local", "로컬 저장"))),
            self.setting_card(
                self.tr("settings.info.update.title", "업데이트"),
                self.tr("settings.info.update.desc", "새 버전 확인 기능은 다음 단계에서 추가할 예정입니다"),
                self.action_button(self.tr("settings.action.check_update", "업데이트 확인"), self.show_update_placeholder),
            ),
        ])

    def page(self, _title: str, widgets: list[QWidget]) -> QScrollArea:
        """설정 카드 목록을 스크롤 가능한 페이지 하나로 구성합니다."""
        c = self.colors
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {c['bg']}; border: none; }}"
            f"QScrollArea > QWidget > QWidget {{ background: {c['bg']}; }}"
            + self.scrollbar_style()
        )
        scroll.viewport().setStyleSheet(f"background: {c['bg']};")
        content = QWidget()
        content.setStyleSheet(f"background: {c['bg']};")
        self.scroll_areas.append(scroll)
        self.scroll_contents.append(content)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 20, 10, 0)
        content_layout.setSpacing(16)
        for widget in widgets:
            content_layout.addWidget(widget)
        content_layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def switch_settings_page(self, row: int, _checked: bool = False) -> None:
        """settings 페이지를 전환합니다."""
        if row < 0:
            return
        self.current_page = row
        self.page_stack.setCurrentIndex(row)
        self.page_title.setText(self.page_labels[row])
        desc_key, desc_fallback = self.PAGE_DESC_KEYS[row]
        self.page_desc.setText(self.tr(desc_key, desc_fallback))
        for button in self.sidebar_buttons:
            button.setChecked(button.row == row)
            button.update()
        if row == 1:
            self.populate_font_combo()

    def section(self, text: str) -> QLabel:
        """설정 페이지 내 섹션 제목 라벨을 만듭니다."""
        label = QLabel(text)
        label.setFont(app_font(11, QFont.Bold))
        return label

    def setting_card(self, title: str, desc: str, control: QWidget) -> SettingCard:
        """제목/설명/컨트롤 위젯으로 구성된 설정 카드를 만들고 목록에 등록합니다."""
        card = SettingCard(title, desc, control, self.colors)
        self.setting_cards.append(card)
        return card

    def startup_control(self) -> Switch:
        """Windows 자동 실행 여부를 켜고 끄는 스위치 컨트롤을 만듭니다."""
        control = Switch(self.app.startup_enabled(), self.colors)
        self.switches.append(control)
        control.toggled.connect(self.on_startup_toggled)
        return control

    def on_startup_toggled(self, enabled: bool) -> None:
        """자동 실행 스위치를 토글하면 시작 프로그램 등록을 갱신합니다."""
        self.app.set_startup(enabled, show_message=False)

    def holiday_control(self) -> Switch:
        """공휴일 표시 여부를 켜고 끄는 스위치 컨트롤을 만듭니다."""
        control = Switch(self.app.store.get("holiday_enabled", True), self.colors)
        self.switches.append(control)
        control.toggled.connect(self.toggle_holidays)
        return control

    def pin_mode_control(self) -> Switch:
        """P-D3: 핀 모드를 켜고 끄는 스위치 — app.set_pin_mode 공개 API만 호출한다."""
        control = Switch(bool(self.app.store.get("pin_mode", False)), self.colors)
        self.switches.append(control)
        control.toggled.connect(self.on_pin_mode_toggled)
        return control

    def on_pin_mode_toggled(self, enabled: bool) -> None:
        """핀 모드 스위치 콜백."""
        self.app.set_pin_mode(enabled)

    def quick_hotkey_control(self) -> QWidget:
        """Q3(U1): 전역 단축키 활성/비활성 스위치 + 현재 조합 표시 + 기본값 리셋 버튼.
        조합을 직접 바꾸는 입력 캡처 UI는 스펙상 비범위 — 표시+리셋만 제공한다."""
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        combo_text = format_hotkey_display(str(self.app.store.get("quick_hotkey", DEFAULT_QUICK_HOTKEY)))
        combo_label = self.info_label(combo_text)
        row.addWidget(combo_label)

        def on_reset() -> None:
            self.app.reset_quick_hotkey()
            combo_label.setText(format_hotkey_display(str(self.app.store.get("quick_hotkey", DEFAULT_QUICK_HOTKEY))))

        reset_button = self.action_button(self.tr("quick.hotkey.reset_button", "기본값"), on_reset)
        reset_button.setFixedWidth(84)
        row.addWidget(reset_button)

        switch = Switch(bool(self.app.store.get("quick_hotkey_enabled", True)), self.colors)
        self.switches.append(switch)
        # 핀 모드 스위치와 동일한 지연 디스패치 스타일 — app 메서드를 직접 connect하면
        # 빌드 시점에 속성을 즉시 조회해 최소 페이크로는 설정창을 못 만든다.
        switch.toggled.connect(self.on_quick_hotkey_toggled)
        self.quick_hotkey_switch = switch
        row.addWidget(switch)

        return wrapper

    def on_quick_hotkey_toggled(self, enabled: bool) -> None:
        self.app.set_quick_hotkey_enabled(enabled)

    def action_button(self, text: str, callback) -> QPushButton:
        """클릭 시 callback을 실행하는 설정 페이지용 액션 버튼을 만듭니다."""
        button = QPushButton(text)
        button.setObjectName("settingsActionButton")
        button.setStyleSheet(self.action_button_style())
        button.clicked.connect(callback)
        button.setFixedHeight(34)
        return button

    def create_backup(self) -> None:
        """현재 설정/데이터/메모를 zip 백업으로 만듭니다."""
        filename = f"ChronoFox-backup-{datetime.now():%Y%m%d-%H%M}.zip"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("settings.dialog.backup.title", "백업 저장"),
            str(APP_DIR / filename),
            self.tr("settings.dialog.backup.filter", "Zip 파일 (*.zip)"),
        )
        if not path:
            return
        try:
            backup_path = self.app.create_backup(Path(path))
        except Exception as exc:
            logging.getLogger(__name__).exception("backup archive creation failed")
            QMessageBox.warning(self, APP_NAME, self.tr("settings.dialog.backup.error", "백업을 만들지 못했습니다.\n\n{error}", error=str(exc)))
            return
        QMessageBox.information(
            self,
            APP_NAME,
            self.tr(
                "settings.dialog.backup.success",
                "백업을 저장했습니다.\n\n{path}\n\n백업 파일에는 일정·메모 등 개인 정보가 포함됩니다. 안전한 곳에 보관하세요.",
                path=str(backup_path),
            ),
        )

    def restore_backup_from_file(self) -> None:
        """사용자가 고른 zip 백업 파일로 복원을 진행합니다."""
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            self.tr("settings.dialog.restore.select.title", "백업 파일 선택"),
            str(APP_DIR),
            self.tr("settings.dialog.backup.filter", "Zip 파일 (*.zip)"),
        )
        if not path:
            return

        info = inspect_backup(Path(path))
        if not info.ok:
            QMessageBox.warning(self, APP_NAME, self._restore_error_message(info.error))
            return

        if not self._confirm_restore(info):
            return

        result = restore_backup(Path(path), self.app.store)
        if not result.ok:
            QMessageBox.warning(self, APP_NAME, self._restore_error_message(result.error))
            return

        # RESTORE1: 복원본은 이미 디스크에 쓰였다. 재시작 전에 종료/창 flush 경로가 옛
        # 메모리 상태로 그 위를 덮어쓰지 않도록 즉시 가드를 세운다.
        self.app.skip_exit_flush = True
        self._notify_restart_required()
        self._restart_app()

    def _restore_error_message(self, error: str) -> str:
        messages = {
            "missing_manifest": self.tr("settings.dialog.restore.error.invalid", "올바른 크로노폭스 백업 파일이 아닙니다."),
            "invalid_zip": self.tr("settings.dialog.restore.error.invalid", "올바른 크로노폭스 백업 파일이 아닙니다."),
            "rollback_failed": self.tr("settings.dialog.restore.error.rollback", "복원 전 자동 백업을 만들지 못해 복원을 중단했습니다."),
            "extract_failed": self.tr("settings.dialog.restore.error.extract", "백업 파일을 푸는 중 오류가 발생했습니다."),
        }
        return messages.get(error, self.tr("settings.dialog.restore.error.generic", "백업을 복원하지 못했습니다."))

    def _confirm_restore(self, info: BackupInfo) -> bool:
        summary = self.tr(
            "settings.dialog.restore.preview",
            "백업 생성 시각: {created_at}\n일정 {schedules}개 · 계획 {plans}개 · 반복 작업 {recurring}개 · 알람 {alarms}개 · 메모 {notes}개\n\n"
            "복원하면 현재 데이터를 덮어씁니다. 복원 전 현재 상태는 자동으로 백업됩니다.\n"
            "백업 파일에는 일정·메모 등 개인 정보가 포함됩니다.",
            created_at=info.created_at or "-",
            schedules=info.schedules_count,
            plans=info.plans_count,
            recurring=info.recurring_count,
            alarms=info.alarms_count,
            notes=info.notes_count,
        )
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(summary)
        box.setIcon(QMessageBox.Warning)
        confirm_button = box.addButton(self.tr("settings.dialog.restore.confirm", "복원"), QMessageBox.AcceptRole)
        box.addButton(self.tr("settings.dialog.restore.cancel", "취소"), QMessageBox.RejectRole)
        box.setDefaultButton(confirm_button)
        box.exec()
        return box.clickedButton() == confirm_button

    def _notify_restart_required(self) -> None:
        """RESTORE1: 복원 성공 후 재시작이 필수임을 알린다. 복원을 종료 시 저장이 무효화하지
        않도록 재시작을 미루는 선택지("나중에")는 제공하지 않는다 — 단일 버튼으로 확인 즉시
        재시작을 진행한다."""
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(self.tr("settings.dialog.restore.success", "백업을 복원했습니다.\n변경 사항을 적용하려면 크로노폭스를 다시 시작해야 합니다."))
        box.setIcon(QMessageBox.Information)
        restart_button = box.addButton(self.tr("settings.dialog.restore.restart_now", "지금 다시 시작"), QMessageBox.AcceptRole)
        box.setDefaultButton(restart_button)
        box.exec()

    def _restart_app(self) -> None:
        if getattr(sys, "frozen", False):
            QProcess.startDetached(sys.executable, [])
        else:
            # C3(repo-layout-v1): 이 모듈은 chronofox/windows/ 하위로 이동했으므로
            # Path(__file__).parent는 더 이상 진입점 디렉터리가 아니다 — 루트 shim
            # (REPO_ROOT의 desktop_note_calendar.py)을 가리켜야 재시작이 정상 동작한다.
            script = str(REPO_ROOT / "desktop_note_calendar.py")
            QProcess.startDetached(sys.executable, [script])
        instance = QApplication.instance()
        if instance is not None:
            instance.quit()

    def export_calendar_file(self) -> None:
        """일정을 ICS 캘린더 파일로 내보냅니다."""
        filename = f"ChronoFox-{datetime.now():%Y%m%d-%H%M}.ics"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            self.tr("settings.dialog.export.title", "캘린더 파일 저장"),
            str(APP_DIR / filename),
            self.tr("settings.dialog.export.filter", "Calendar 파일 (*.ics)"),
        )
        if not path:
            return
        try:
            export_path = self.app.export_calendar_file(Path(path))
        except Exception as exc:
            logging.getLogger(__name__).exception("ICS export failed")
            QMessageBox.warning(self, APP_NAME, self.tr("settings.dialog.export.error", "캘린더 파일을 만들지 못했습니다.\n\n{error}", error=str(exc)))
            return
        QMessageBox.information(self, APP_NAME, self.tr("settings.dialog.export.success", "캘린더 파일을 저장했습니다.\n\n{path}", path=str(export_path)))

    def show_update_placeholder(self) -> None:
        """update placeholder를 보여줍니다."""
        QMessageBox.information(
            self,
            APP_NAME,
            self.tr("settings.dialog.update.pending", "업데이트 확인 기능은 다음 단계에서 추가할 예정입니다."),
        )

    def info_label(self, text: str) -> QLabel:
        """info 라벨 문자열을 만듭니다."""
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"QLabel {{ background: {self.colors['panel2']}; color: {self.colors['muted']}; "
            "border-radius: 8px; padding: 7px 12px; font-weight: 600; }}"
        )
        self.info_labels.append(label)
        return label

    def theme_selector(self) -> QWidget:
        """라이트/다크/시스템 테마를 고르는 버튼 그룹을 만듭니다."""
        c = self.colors
        current = self.app.store.get("theme_mode", "system")
        widget = QWidget()
        widget.setObjectName("themeSelector")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet("QWidget#themeSelector { background: transparent; border: none; }")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        options = [
            ("light", self.tr("settings.theme.light", "라이트 모드")),
            ("dark", self.tr("settings.theme.dark", "다크 모드")),
            ("system", self.tr("settings.theme.system", "시스템")),
        ]
        for mode, label in options:
            button = ThemeButton(mode, label, c)
            button.setChecked(mode == current)
            button.clicked.connect(partial(self.set_theme, mode))
            self.theme_buttons.append(button)
            layout.addWidget(button)
        widget.setFixedWidth(292)
        return widget

    def calendar_style_selector(self) -> QWidget:
        """R16: 기본/미니멀/셀 카드 중 달력 날짜 칸 모양을 고르는 버튼 그룹을 만듭니다."""
        c = self.colors
        current = self.app.store.get("calendar_style", "grid")
        widget = QWidget()
        widget.setObjectName("calendarStyleSelector")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet("QWidget#calendarStyleSelector { background: transparent; border: none; }")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        options = [
            ("grid", self.tr("settings.theme.calendar_style.grid", "기본")),
            ("minimal", self.tr("settings.theme.calendar_style.minimal", "미니멀")),
            ("card", self.tr("settings.theme.calendar_style.card", "셀 카드")),
        ]
        for style, label in options:
            button = CalendarStyleButton(style, label, c)
            button.setChecked(style == current)
            button.clicked.connect(partial(self.set_calendar_style, style))
            self.calendar_style_buttons.append(button)
            layout.addWidget(button)
        widget.setFixedWidth(300)
        return widget

    def font_combo(self) -> QComboBox:
        """기본 폰트를 고르는 콤보박스를 만듭니다."""
        combo = ArrowComboBox(self.colors)
        current = self.app.store.get("font_family", DEFAULT_FONT_FAMILY)
        combo.addItem(self.font_label(current), current)
        combo.currentIndexChanged.connect(self.on_font_combo_changed)
        combo.setStyleSheet(self.input_style())
        combo.setFixedWidth(230)
        self.font_combo_box = combo
        self.combo_boxes.append(combo)
        return combo

    def on_font_combo_changed(self, _index: int) -> None:
        """폰트 콤보박스 선택이 바뀌면 새 폰트를 적용합니다."""
        combo = self.font_combo_box
        if combo is None:
            return
        self.set_font_family(combo.currentData())

    def language_combo(self) -> QComboBox:
        """표시 언어를 고르는 콤보박스를 만듭니다."""
        combo = ArrowComboBox(self.colors)
        current = normalize_language(self.app.store.get("language", "ko"))
        for code, label in SUPPORTED_LANGUAGES.items():
            combo.addItem(label, code)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(self.on_language_combo_changed)
        combo.setStyleSheet(self.input_style())
        combo.setFixedWidth(160)
        self.language_combo_box = combo
        self.combo_boxes.append(combo)
        return combo

    def on_language_combo_changed(self, _index: int) -> None:
        """언어 콤보박스 선택이 바뀌면 새 언어를 적용합니다."""
        combo = self.language_combo_box
        if combo is None:
            return
        self.set_language(combo.currentData())

    def font_label(self, family: str) -> str:
        """폰트 선택 콤보박스에 표시할 라벨 문자열을 만듭니다."""
        if family == DEFAULT_FONT_FAMILY:
            return self.tr("settings.font.default", "기본 폰트 ({font})", font=DEFAULT_FONT_LABEL)
        return family

    def populate_font_combo(self) -> None:
        """시스템 폰트 목록으로 폰트 콤보박스를 채웁니다."""
        combo = self.font_combo_box
        if combo is None or combo.property("fonts_populated"):
            return
        current = self.app.store.get("font_family", DEFAULT_FONT_FAMILY)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(self.tr("settings.font.default", "기본 폰트 ({font})", font=DEFAULT_FONT_LABEL), DEFAULT_FONT_FAMILY)
        for family in system_font_families():
            combo.addItem(family, family)
        index = combo.findData(current)
        combo.setCurrentIndex(max(0, index))
        combo.setProperty("fonts_populated", True)
        combo.blockSignals(False)

    def opacity_control(self) -> QWidget:
        """캘린더 창 투명도를 조절하는 슬라이더/스핀박스 컨트롤을 만듭니다."""
        c = self.colors
        widget = QWidget()
        widget.setObjectName("opacityControl")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet(f"QWidget#opacityControl {{ background: {c['panel']}; border: none; }}")
        self.opacity_widgets.append(widget)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(20, 100)
        slider.setValue(self.app.store.get("calendar_opacity", 56))
        spin = QSpinBox()
        spin.setRange(20, 100)
        spin.setButtonSymbols(QSpinBox.NoButtons)
        spin.setValue(slider.value())
        slider.valueChanged.connect(spin.setValue)
        spin.valueChanged.connect(slider.setValue)
        slider.valueChanged.connect(self.app.set_calendar_opacity)
        slider.setStyleSheet(self.opacity_slider_style())
        self.opacity_sliders.append(slider)
        spin.setStyleSheet(self.input_style())
        self.opacity_spins.append(spin)
        layout.addWidget(slider)
        layout.addWidget(spin)
        widget.setFixedWidth(220)
        return widget

    def input_style(self) -> str:
        """입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QComboBox, QSpinBox, QLineEdit {{ background: {c['settings_input']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 12px; padding: 7px 30px 7px 12px; }}"
            f"QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ background: {c['settings_input_hover']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: top right; }}"
            "QComboBox::down-arrow { image: none; width: 0; height: 0; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def opacity_slider_style(self) -> str:
        """투명도 슬라이더 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            "QSlider { background: transparent; border: none; }"
            f"QSlider::groove:horizontal {{ height: 3px; background: {c['settings_input']}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ background: white; border: 2px solid {c['accent']}; width: 16px; height: 16px; margin: -8px 0; border-radius: 9px; }}"
        )

    def scrollbar_style(self) -> str:
        """스크롤바 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return fancy_scrollbar_style(c["panel"], c["border"], c["muted"], c["border"])

    def button_style(self) -> str:
        """버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ color: {c['muted']}; background: transparent; border: none; font-size: 14px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel']}; color: {c['text']}; border-radius: 8px; }}"
        )

    def action_button_style(self) -> str:
        """설정 화면 액션 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['accent']}; color: white; border: none; "
            "border-radius: 12px; padding: 8px 16px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {c.get('accent_hover', c['accent'])}; }}"
        )

    def set_theme(self, mode: str, _checked: bool = False) -> None:
        """테마 모드를 바꾸고 화면에 반영합니다."""
        if self.app.store.get("theme_mode", "system") == mode:
            return
        self.app.store.set("theme_mode", mode)
        self.app.store.set("settings_geometry", geometry_string(self), notify_topic=None)
        self.app.save()
        self.app.apply_theme()

    def set_calendar_style(self, style: str, _checked: bool = False) -> None:
        """R16: 달력 모양(calendar_style)을 바꾸고 메인 달력에 즉시 반영합니다."""
        if self.app.store.get("calendar_style", "grid") == style:
            return
        self.app.store.set("calendar_style", style)
        self.app.store.set("settings_geometry", geometry_string(self), notify_topic=None)
        self.app.save()
        self.app.apply_theme()

    def apply_theme(self) -> None:
        """현재 테마 색상을 위젯 스타일에 다시 적용합니다."""
        self.colors = settings_panel_colors(self.app.dialog_colors())
        self.refresh_theme_styles()
        self.update()

    def set_language(self, language: str) -> None:
        """언어를 바꾸고 화면에 반영합니다."""
        normalized = normalize_language(language)
        if self.app.store.get("language", "ko") == normalized:
            return
        self.app.store.set("language", normalized)
        self.app.store.set("settings_geometry", geometry_string(self), notify_topic=None)
        self.app.save()
        self.setWindowTitle(self.tr("settings.window.title", f"{APP_NAME} 설정"))
        self.build_ui()
        if hasattr(self.app, "apply_language"):
            self.app.apply_language(source=self)

    def apply_language(self) -> None:
        """현재 언어 설정에 맞춰 화면 텍스트를 다시 그립니다."""
        self.setWindowTitle(self.tr("settings.window.title", f"{APP_NAME} 설정"))
        self.build_ui()

    def refresh_theme_styles(self) -> None:
        """테마가 바뀐 뒤 스타일시트를 다시 적용합니다."""
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "sidebar_frame"):
            self.sidebar_frame.setStyleSheet(
                f"QFrame {{ background: {c['settings_sidebar']}; border: none; border-top-left-radius: {self.radius}px; "
                f"border-bottom-left-radius: {self.radius}px; }}"
            )
        if hasattr(self, "side_title"):
            self.side_title.setStyleSheet(f"color: {c['accent']};")
        if hasattr(self, "page_desc"):
            self.page_desc.setStyleSheet(f"color: {c['muted']};")
        if hasattr(self, "version_value"):
            self.version_value.setStyleSheet(f"color: {c['accent']};")
        if hasattr(self, "content_frame"):
            self.content_frame.setStyleSheet(
                f"QFrame {{ background: {c['bg']}; border: none; border-top-right-radius: {self.radius}px; "
                f"border-bottom-right-radius: {self.radius}px; }}"
            )
        for button in self.sidebar_buttons:
            button.set_colors(c)
        if hasattr(self, "close_button"):
            self.close_button.colors = c
            self.close_button.refresh_style()
            self.close_button.update()
        for scroll in self.scroll_areas:
            scroll.setStyleSheet(
                f"QScrollArea {{ background: {c['bg']}; border: none; }}"
                f"QScrollArea > QWidget > QWidget {{ background: {c['bg']}; }}"
                + self.scrollbar_style()
            )
            scroll.viewport().setStyleSheet(f"background: {c['bg']};")
        for content in self.scroll_contents:
            content.setStyleSheet(f"background: {c['bg']};")
        for card in self.setting_cards:
            card.apply_theme(c)
        for button in self.findChildren(QPushButton, "settingsActionButton"):
            button.setStyleSheet(self.action_button_style())
        for label in self.info_labels:
            label.setStyleSheet(
                f"QLabel {{ background: {c['panel2']}; color: {c['muted']}; "
                "border-radius: 8px; padding: 7px 12px; font-weight: 600; }}"
            )
        current_theme = self.app.store.get("theme_mode", "system")
        for button in self.theme_buttons:
            button.colors = c
            button.setChecked(button.mode == current_theme)
            button.update()
        current_calendar_style = self.app.store.get("calendar_style", "grid")
        for button in self.calendar_style_buttons:
            button.colors = c
            button.setChecked(button.style_id == current_calendar_style)
            button.update()
        for combo in self.combo_boxes:
            if isinstance(combo, ArrowComboBox):
                combo.colors = c
            combo.setStyleSheet(self.input_style())
            combo.update()
        for switch in self.switches:
            switch.colors = c
            switch.update()
        for widget in self.opacity_widgets:
            widget.setStyleSheet(f"QWidget#opacityControl {{ background: {c['panel']}; border: none; }}")
        for slider in self.opacity_sliders:
            slider.setStyleSheet(self.opacity_slider_style())
        for spin in self.opacity_spins:
            spin.setStyleSheet(self.input_style())

    def set_font_family(self, family: str) -> None:
        """기본 폰트 패밀리를 바꾸고 화면에 반영합니다."""
        if not family or self.app.store.get("font_family", DEFAULT_FONT_FAMILY) == family:
            return
        self.app.store.set("font_family", family)
        self.app.save()
        self.app.apply_font_family(family)
        self.refresh_font_styles()

    def refresh_font_styles(self) -> None:
        """폰트가 바뀐 뒤 스타일시트를 다시 적용합니다."""
        if hasattr(self, "side_title"):
            self.side_title.setFont(app_font(14, QFont.Bold))
        if hasattr(self, "page_title"):
            self.page_title.setFont(app_font(13, QFont.Bold))
        if hasattr(self, "page_desc"):
            self.page_desc.setFont(app_font())
        for button in self.sidebar_buttons:
            button.update()
        for card in self.setting_cards:
            card.apply_font()
        for label in self.info_labels:
            label.setFont(app_font())
        for button in self.findChildren(QPushButton, "settingsActionButton"):
            button.setFont(app_font(9, QFont.Bold))
        for button in self.theme_buttons:
            button.update()
        for button in self.calendar_style_buttons:
            button.update()
        for combo in self.combo_boxes:
            combo.setFont(app_font())
            combo.update()
        for spin in self.opacity_spins:
            spin.setFont(app_font())

    def toggle_holidays(self, enabled: bool) -> None:
        """공휴일 표시 여부를 토글합니다."""
        self.app.store.set("holiday_enabled", enabled)
        self.app.save()
        self.app.render_calendar()

    def closeEvent(self, event) -> None:
        self.app.store.set("settings_geometry", geometry_string(self), notify_topic=None)
        self.app.save()
        self.app.settings_window = None
        super().closeEvent(event)

