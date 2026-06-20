from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import QFileDialog, QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSlider, QSpinBox, QStackedWidget, QVBoxLayout, QWidget

from app_constants import APP_DIR, APP_NAME, DEFAULT_FONT_FAMILY, DEFAULT_FONT_LABEL, DEFAULT_SETTINGS_GEOMETRY, STARTUP_PATH
from app_ui import add_soft_shadow, app_font, clear_layout, geometry_string, parse_geometry, system_font_families
from app_widgets import ArrowComboBox, IconButton, RoundedWindow, Switch, ThemeButton

if TYPE_CHECKING:
    from desktop_note_calendar import FoxCalendarApp


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
        layout.setContentsMargins(14, 12, 14, 12)
        texts = QVBoxLayout()
        texts.addWidget(self.title_label)
        texts.addWidget(self.desc_label)
        layout.addLayout(texts, 1)
        layout.addWidget(control)

        self.apply_font()
        self.apply_theme(colors)

    def apply_theme(self, colors: dict[str, str]) -> None:
        self.colors = colors
        self.setStyleSheet(
            f"QFrame#settingCard {{ background: {colors['panel']}; border: 1px solid {colors['border']}; border-radius: 9px; }}"
            "QFrame#settingCard QLabel { border: none; background: transparent; }"
        )
        self.desc_label.setStyleSheet(f"color: {colors['muted']};")
        add_soft_shadow(self, colors, blur=12, alpha=22)

    def apply_font(self) -> None:
        self.title_label.setFont(app_font(10, QFont.Bold))
        self.desc_label.setFont(app_font())


class SettingsWindow(RoundedWindow):
    """테마, 투명도, 자동실행 같은 사용자 설정을 바꾸는 창입니다."""

    def __init__(self, app: "FoxCalendarApp") -> None:
        super().__init__(app.dialog_colors())
        self.app = app
        self.current_page = 0
        self.font_combo_box: QComboBox | None = None
        self.setting_cards: list[SettingCard] = []
        self.info_labels: list[QLabel] = []
        self.theme_buttons: list[ThemeButton] = []
        self.combo_boxes: list[QComboBox] = []
        self.switches: list[Switch] = []
        self.scroll_areas: list[QScrollArea] = []
        self.scroll_contents: list[QWidget] = []
        self.opacity_widgets: list[QWidget] = []
        self.opacity_sliders: list[QSlider] = []
        self.opacity_spins: list[QSpinBox] = []
        self.alert_sound_detail_widgets: list[QWidget] = []
        self.alert_sound_file_labels: list[QLabel] = []
        self.alert_sound_url_inputs: list[QLineEdit] = []
        self.alert_sound_url_full_text = ""
        self.setWindowTitle(f"{APP_NAME} 설정")
        self.setWindowIcon(app.icon)
        width, height, x, y = parse_geometry(app.config.get("settings_geometry", DEFAULT_SETTINGS_GEOMETRY), (860, 520, 260, 130))
        width = max(width, 860)
        self.setGeometry(x, y, width, height)
        self.setMinimumSize(820, 500)
        self.build_ui()

    def build_ui(self) -> None:
        """설정창을 왼쪽 사이드바와 오른쪽 설정 페이지로 구성합니다."""
        c = self.colors
        self.setting_cards.clear()
        self.info_labels.clear()
        self.theme_buttons.clear()
        self.combo_boxes.clear()
        self.switches.clear()
        self.scroll_areas.clear()
        self.scroll_contents.clear()
        self.opacity_widgets.clear()
        self.opacity_sliders.clear()
        self.opacity_spins.clear()
        self.alert_sound_detail_widgets.clear()
        self.alert_sound_file_labels.clear()
        self.alert_sound_url_inputs.clear()
        existing = self.layout()
        if existing is None:
            layout = QHBoxLayout(self)
        else:
            clear_layout(existing)
            layout = existing
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar_frame = QFrame()
        self.sidebar_frame.setFixedWidth(178)
        self.sidebar_frame.setStyleSheet(
            f"QFrame {{ background: {c['panel2']}; border: none; border-top-left-radius: {self.radius}px; "
            f"border-bottom-left-radius: {self.radius}px; }}"
        )
        sidebar_layout = QVBoxLayout(self.sidebar_frame)
        sidebar_layout.setContentsMargins(20, 20, 14, 18)
        sidebar_layout.setSpacing(10)
        self.side_title = QLabel("Settings")
        self.side_title.setFont(app_font(13, QFont.Bold))
        self.sidebar_list = QListWidget()
        self.sidebar_list.setStyleSheet(self.sidebar_style())
        self.sidebar_list.setFrameShape(QFrame.NoFrame)
        for label in ("프로그램 설정", "테마", "연동", "정보"):
            self.sidebar_list.addItem(label)
        self.sidebar_list.currentRowChanged.connect(self.switch_settings_page)
        sidebar_layout.addWidget(self.side_title)
        sidebar_layout.addSpacing(10)
        sidebar_layout.addWidget(self.sidebar_list, 1)

        self.content_frame = QFrame()
        self.content_frame.setStyleSheet(
            f"QFrame {{ background: {c['bg']}; border: none; border-top-right-radius: {self.radius}px; "
            f"border-bottom-right-radius: {self.radius}px; }}"
        )
        content_layout = QVBoxLayout(self.content_frame)
        content_layout.setContentsMargins(20, 20, 22, 20)
        content_layout.setSpacing(12)

        header = QHBoxLayout()
        self.page_title = QLabel("")
        self.page_title.setFont(app_font(15, QFont.Bold))
        self.close_button = IconButton("close", c)
        self.close_button.setFixedSize(30, 30)
        self.close_button.clicked.connect(self.close)
        header.addWidget(self.page_title)
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
        self.sidebar_list.setCurrentRow(min(self.current_page, self.sidebar_list.count() - 1))

    def build_program_page(self) -> QScrollArea:
        return self.page("프로그램 설정", [
            self.setting_card("투명도", "달력이 바탕화면에 보이는 정도를 조절합니다", self.opacity_control()),
            self.setting_card("공휴일 표시", "주요 공휴일과 대체공휴일을 달력에 표시합니다", self.holiday_control()),
            self.setting_card("Windows 시작 시 자동 실행", "컴퓨터를 켤 때 Fox Calendar를 자동으로 엽니다", self.startup_control()),
            self.setting_card("알림음", "타이머와 알람 완료 시 사용할 소리를 선택합니다", self.alert_sound_control()),
        ])

    def build_theme_page(self) -> QScrollArea:
        return self.page("테마", [
            self.setting_card("테마", "Fox Calendar의 색상 모드를 선택합니다", self.theme_selector()),
            self.setting_card("노트 테마", "메모 창의 색상 모드를 선택합니다", self.note_theme_combo()),
            self.setting_card("기본 폰트", "앱에서 사용할 글꼴을 선택합니다", self.font_combo()),
        ])

    def build_integration_page(self) -> QScrollArea:
        return self.page("연동", [
            self.setting_card("로컬 백업", "설정, 일정, 계획, 해야 할 일, 메모를 zip 파일로 저장합니다", self.action_button("백업 만들기", self.create_backup)),
            self.setting_card("캘린더 내보내기", "Google Calendar와 Microsoft Outlook에서 가져올 수 있는 파일을 만듭니다", self.action_button("ICS 만들기", self.export_calendar_file)),
            self.setting_card("클라우드 연동", "동기화와 가져오기 기능은 다음 단계에서 추가할 예정입니다", self.info_label("준비 중")),
        ])

    def build_info_page(self) -> QScrollArea:
        return self.page("정보", [
            self.setting_card("프로그램", APP_NAME, self.info_label("Fox Calendar")),
            self.setting_card("데이터 위치", str(APP_DIR), self.info_label("로컬 저장")),
        ])

    def page(self, _title: str, widgets: list[QWidget]) -> QScrollArea:
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
        content_layout.setContentsMargins(0, 0, 12, 0)
        content_layout.setSpacing(12)
        for widget in widgets:
            content_layout.addWidget(widget)
        content_layout.addStretch()
        scroll.setWidget(content)
        return scroll

    def switch_settings_page(self, row: int) -> None:
        if row < 0:
            return
        self.current_page = row
        self.page_stack.setCurrentIndex(row)
        self.page_title.setText(self.sidebar_list.item(row).text())
        if row == 1:
            self.populate_font_combo()

    def section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(app_font(11, QFont.Bold))
        return label

    def sidebar_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: transparent; color: {c['muted']}; border: none; outline: none; }}"
            "QListWidget::item { padding: 9px 10px; border-radius: 8px; border: 1px solid transparent; }"
            f"QListWidget::item:selected {{ background: {c['panel']}; color: {c['text']}; font-weight: 700; border: 1px solid {c['border']}; }}"
            f"QListWidget::item:hover {{ background: {c['border']}; color: {c['text']}; border: 1px solid {c['border']}; }}"
        )

    def setting_card(self, title: str, desc: str, control: QWidget) -> SettingCard:
        card = SettingCard(title, desc, control, self.colors)
        self.setting_cards.append(card)
        return card

    def startup_control(self) -> Switch:
        control = Switch(STARTUP_PATH.exists(), self.colors)
        self.switches.append(control)
        control.toggled.connect(lambda enabled: self.app.set_startup(enabled, show_message=False))
        return control

    def holiday_control(self) -> Switch:
        control = Switch(self.app.config.get("holiday_enabled", True), self.colors)
        self.switches.append(control)
        control.toggled.connect(self.toggle_holidays)
        return control

    def action_button(self, text: str, callback) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("settingsActionButton")
        button.setStyleSheet(self.action_button_style())
        button.clicked.connect(callback)
        button.setFixedHeight(34)
        return button

    def alert_sound_control(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("alertSoundControl")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet("QWidget#alertSoundControl { background: transparent; border: none; }")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        combo = ArrowComboBox(self.colors)
        combo.addItem("기본 알림음", "default")
        combo.addItem("로컬 파일", "local")
        combo.addItem("외부 링크", "url")
        current = self.normalized_alert_sound_mode()
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(lambda _i: self.set_alert_sound_mode(combo.currentData()))
        combo.setStyleSheet(self.input_style())
        combo.setFixedWidth(220)
        self.combo_boxes.append(combo)
        layout.addWidget(combo)

        file_row = QWidget()
        file_row.setObjectName("alertSoundDetail")
        file_row.setAttribute(Qt.WA_StyledBackground, True)
        file_row.setStyleSheet("QWidget#alertSoundDetail { background: transparent; border: none; }")
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)
        file_label = QLabel(self.alert_sound_file_text())
        file_label.setFixedWidth(220)
        file_label.setStyleSheet(f"color: {self.colors['muted']};")
        self.alert_sound_file_labels.append(file_label)
        file_button = self.action_button("파일 선택", self.select_local_alert_sound)
        file_layout.addWidget(file_label, 1)
        file_layout.addWidget(file_button)
        layout.addWidget(file_row)
        self.alert_sound_detail_widgets.append(file_row)

        url_input = QLineEdit()
        url_input.setPlaceholderText("https://example.com/audio")
        self.alert_sound_url_full_text = self.app.config.get("alert_sound_url", "")
        url_input.setText(self.elided_alert_text(self.alert_sound_url_full_text, 280))
        url_input.setStyleSheet(self.input_style())
        url_input.setToolTip(self.alert_sound_url_full_text)
        url_input.setFixedWidth(300)
        url_input.installEventFilter(self)
        url_input.textEdited.connect(self.on_alert_sound_url_edited)
        url_input.editingFinished.connect(self.save_alert_sound_url)
        layout.addWidget(url_input)
        self.alert_sound_url_inputs.append(url_input)

        self.refresh_alert_sound_detail_visibility()
        return widget

    def normalized_alert_sound_mode(self) -> str:
        mode = self.app.config.get("alert_sound_mode", "default")
        if mode == "youtube":
            return "url"
        return mode if mode in {"default", "local", "url"} else "default"

    def alert_sound_file_text(self) -> str:
        path = Path(self.app.config.get("alert_sound_path", ""))
        return path.name if path.name else "선택된 파일 없음"

    def elided_alert_text(self, text: str, width: int = 260) -> str:
        if not text:
            return ""
        metrics = QFontMetrics(app_font())
        return metrics.elidedText(text, Qt.ElideMiddle, width)

    def refresh_alert_sound_detail_visibility(self) -> None:
        mode = self.normalized_alert_sound_mode()
        for widget in self.alert_sound_detail_widgets:
            widget.setVisible(mode == "local")
        for input_widget in self.alert_sound_url_inputs:
            input_widget.setVisible(mode == "url")
            self.alert_sound_url_full_text = self.app.config.get("alert_sound_url", "")
            input_widget.setText(self.elided_alert_text(self.alert_sound_url_full_text, 280))
            input_widget.setToolTip(self.alert_sound_url_full_text)
        for label in self.alert_sound_file_labels:
            full_text = self.alert_sound_file_text()
            label.setText(self.elided_alert_text(full_text, 220))
            label.setToolTip(full_text)

    def set_alert_sound_mode(self, mode: str) -> None:
        mode = mode or "default"
        self.app.config["alert_sound_mode"] = mode
        if mode == "default":
            self.app.config["alert_sound_path"] = ""
            self.app.config["alert_sound_url"] = ""
        self.app.save()
        self.refresh_alert_sound_detail_visibility()

    def select_local_alert_sound(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "알림음 선택",
            str(Path.home()),
            "Audio 파일 (*.mp3 *.wav *.m4a *.aac *.ogg);;모든 파일 (*.*)",
        )
        if not path:
            return
        self.app.config["alert_sound_mode"] = "local"
        self.app.config["alert_sound_path"] = path
        self.app.save()
        self.refresh_alert_sound_detail_visibility()

    def save_alert_sound_url(self) -> None:
        if not self.alert_sound_url_inputs:
            return
        input_widget = self.alert_sound_url_inputs[-1]
        url = input_widget.text().strip()
        if url == self.elided_alert_text(self.alert_sound_url_full_text, 280):
            url = self.alert_sound_url_full_text.strip()
        if not url:
            self.app.config["alert_sound_url"] = ""
            self.app.save()
            self.alert_sound_url_full_text = ""
            self.refresh_alert_sound_detail_visibility()
            return
        if not self.is_supported_external_url(url):
            QMessageBox.warning(self, APP_NAME, "https:// 로 시작하는 외부 링크를 입력해 주세요.")
            input_widget.setText(self.elided_alert_text(self.alert_sound_url_full_text, 280))
            return
        self.app.config["alert_sound_mode"] = "url"
        self.app.config["alert_sound_url"] = url
        self.alert_sound_url_full_text = url
        self.app.save()
        self.refresh_alert_sound_detail_visibility()

    def on_alert_sound_url_edited(self, text: str) -> None:
        self.alert_sound_url_full_text = text.strip()

    def eventFilter(self, watched, event) -> bool:
        if watched in self.alert_sound_url_inputs:
            if event.type() == QEvent.FocusIn:
                watched.setText(self.alert_sound_url_full_text)
            elif event.type() == QEvent.FocusOut:
                self.save_alert_sound_url()
        return super().eventFilter(watched, event)

    def is_supported_external_url(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and bool(host)

    def create_backup(self) -> None:
        filename = f"FoxCalendar-backup-{datetime.now():%Y%m%d-%H%M}.zip"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "백업 저장",
            str(APP_DIR / filename),
            "Zip 파일 (*.zip)",
        )
        if not path:
            return
        try:
            backup_path = self.app.create_backup(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"백업을 만들지 못했습니다.\n\n{exc}")
            return
        QMessageBox.information(self, APP_NAME, f"백업을 저장했습니다.\n\n{backup_path}")

    def export_calendar_file(self) -> None:
        filename = f"FoxCalendar-{datetime.now():%Y%m%d-%H%M}.ics"
        path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "캘린더 파일 저장",
            str(APP_DIR / filename),
            "Calendar 파일 (*.ics)",
        )
        if not path:
            return
        try:
            export_path = self.app.export_calendar_file(Path(path))
        except Exception as exc:
            QMessageBox.warning(self, APP_NAME, f"캘린더 파일을 만들지 못했습니다.\n\n{exc}")
            return
        QMessageBox.information(self, APP_NAME, f"캘린더 파일을 저장했습니다.\n\n{export_path}")

    def info_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"QLabel {{ background: {self.colors['panel2']}; color: {self.colors['muted']}; "
            "border-radius: 8px; padding: 7px 12px; font-weight: 600; }}"
        )
        self.info_labels.append(label)
        return label

    def theme_selector(self) -> QWidget:
        c = self.colors
        current = self.app.config.get("theme_mode", "system")
        widget = QWidget()
        widget.setObjectName("themeSelector")
        widget.setAttribute(Qt.WA_StyledBackground, True)
        widget.setStyleSheet("QWidget#themeSelector { background: transparent; border: none; }")
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        options = [
            ("light", "라이트 모드"),
            ("dark", "다크 모드"),
            ("system", "시스템"),
        ]
        for mode, label in options:
            button = ThemeButton(mode, label, c)
            button.setChecked(mode == current)
            button.clicked.connect(lambda _checked=False, selected=mode: self.set_theme(selected))
            self.theme_buttons.append(button)
            layout.addWidget(button)
        widget.setFixedWidth(292)
        return widget

    def note_theme_combo(self) -> QComboBox:
        combo = ArrowComboBox(self.colors)
        combo.addItem("라이트", "light")
        combo.addItem("기본", "default")
        combo.addItem("다크", "dark")
        index = combo.findData(self.app.config.get("note_theme", "default"))
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _i: self.set_note_theme(combo.currentData()))
        combo.setStyleSheet(self.input_style())
        combo.setFixedWidth(140)
        self.combo_boxes.append(combo)
        return combo

    def font_combo(self) -> QComboBox:
        combo = ArrowComboBox(self.colors)
        current = self.app.config.get("font_family", DEFAULT_FONT_FAMILY)
        combo.addItem(self.font_label(current), current)
        combo.currentIndexChanged.connect(lambda _i: self.set_font_family(combo.currentData()))
        combo.setStyleSheet(self.input_style())
        combo.setFixedWidth(230)
        self.font_combo_box = combo
        self.combo_boxes.append(combo)
        return combo

    def font_label(self, family: str) -> str:
        if family == DEFAULT_FONT_FAMILY:
            return f"기본 폰트 ({DEFAULT_FONT_LABEL})"
        return family

    def populate_font_combo(self) -> None:
        combo = self.font_combo_box
        if combo is None or combo.property("fonts_populated"):
            return
        current = self.app.config.get("font_family", DEFAULT_FONT_FAMILY)
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(f"기본 폰트 ({DEFAULT_FONT_LABEL})", DEFAULT_FONT_FAMILY)
        for family in system_font_families():
            combo.addItem(family, family)
        index = combo.findData(current)
        combo.setCurrentIndex(max(0, index))
        combo.setProperty("fonts_populated", True)
        combo.blockSignals(False)

    def opacity_control(self) -> QWidget:
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
        slider.setValue(self.app.config.get("calendar_opacity", 56))
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
        c = self.colors
        return (
            f"QComboBox, QSpinBox, QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 6px 28px 6px 10px; }}"
            f"QComboBox:hover, QSpinBox:hover, QLineEdit:hover {{ background: {c['border']}; }}"
            f"QComboBox::drop-down {{ border: none; width: 28px; subcontrol-origin: padding; subcontrol-position: top right; }}"
            "QComboBox::down-arrow { image: none; width: 0; height: 0; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def opacity_slider_style(self) -> str:
        c = self.colors
        return (
            "QSlider { background: transparent; border: none; }"
            f"QSlider::groove:horizontal {{ height: 3px; background: {c['panel2']}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {c['accent']}; border-radius: 2px; }}"
            "QSlider::handle:horizontal { background: white; border: 1px solid #6f858c; width: 18px; height: 18px; margin: -8px 0; border-radius: 9px; }"
        )

    def scrollbar_style(self) -> str:
        c = self.colors
        return (
            f"QScrollBar:vertical {{ background: {c['panel']}; width: 12px; margin: 13px 0 13px 0; }}"
            f"QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 28px; border-radius: 5px; margin: 1px 3px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ background: {c['panel']}; height: 13px; subcontrol-origin: margin; }}"
            f"QScrollBar::sub-line:vertical {{ subcontrol-position: top; }}"
            f"QScrollBar::add-line:vertical {{ subcontrol-position: bottom; }}"
            f"QScrollBar::up-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid {c['border']}; width: 0; height: 0; }}"
            f"QScrollBar::down-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {c['border']}; width: 0; height: 0; }}"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ color: {c['muted']}; background: transparent; border: none; font-size: 14px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel']}; color: {c['text']}; border-radius: 8px; }}"
        )

    def action_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 8px; padding: 7px 14px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def set_theme(self, mode: str) -> None:
        if self.app.config.get("theme_mode", "system") == mode:
            return
        self.app.config["theme_mode"] = mode
        self.app.config["settings_geometry"] = geometry_string(self)
        self.app.save()
        self.app.apply_theme()

    def apply_theme(self) -> None:
        self.colors = self.app.dialog_colors()
        self.refresh_theme_styles()
        self.update()

    def refresh_theme_styles(self) -> None:
        c = self.colors
        self.setStyleSheet(f"QLabel {{ color: {c['text']}; }}")
        if hasattr(self, "sidebar_frame"):
            self.sidebar_frame.setStyleSheet(
                f"QFrame {{ background: {c['panel2']}; border: none; border-top-left-radius: {self.radius}px; "
                f"border-bottom-left-radius: {self.radius}px; }}"
            )
        if hasattr(self, "content_frame"):
            self.content_frame.setStyleSheet(
                f"QFrame {{ background: {c['bg']}; border: none; border-top-right-radius: {self.radius}px; "
                f"border-bottom-right-radius: {self.radius}px; }}"
            )
        if hasattr(self, "sidebar_list"):
            self.sidebar_list.setStyleSheet(self.sidebar_style())
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
        for label in self.alert_sound_file_labels:
            label.setStyleSheet(f"color: {c['muted']};")
        for input_widget in self.alert_sound_url_inputs:
            input_widget.setStyleSheet(self.input_style())
        self.refresh_alert_sound_detail_visibility()
        current_theme = self.app.config.get("theme_mode", "system")
        for button in self.theme_buttons:
            button.colors = c
            button.setChecked(button.mode == current_theme)
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

    def set_note_theme(self, mode: str) -> None:
        if self.app.config.get("note_theme", "default") == mode:
            return
        self.app.config["note_theme"] = mode
        self.app.save()
        self.app.apply_note_theme()

    def set_font_family(self, family: str) -> None:
        if not family or self.app.config.get("font_family", DEFAULT_FONT_FAMILY) == family:
            return
        self.app.config["font_family"] = family
        self.app.save()
        self.app.apply_font_family(family)
        self.refresh_font_styles()

    def refresh_font_styles(self) -> None:
        if hasattr(self, "side_title"):
            self.side_title.setFont(app_font(13, QFont.Bold))
        if hasattr(self, "page_title"):
            self.page_title.setFont(app_font(15, QFont.Bold))
        if hasattr(self, "sidebar_list"):
            self.sidebar_list.setFont(app_font())
        for card in self.setting_cards:
            card.apply_font()
        for label in self.info_labels:
            label.setFont(app_font())
        for label in self.alert_sound_file_labels:
            label.setFont(app_font())
        for input_widget in self.alert_sound_url_inputs:
            input_widget.setFont(app_font())
        for button in self.findChildren(QPushButton, "settingsActionButton"):
            button.setFont(app_font(9, QFont.Bold))
        for button in self.theme_buttons:
            button.update()
        for combo in self.combo_boxes:
            combo.setFont(app_font())
            combo.update()
        for spin in self.opacity_spins:
            spin.setFont(app_font())

    def toggle_holidays(self, enabled: bool) -> None:
        self.app.config["holiday_enabled"] = enabled
        self.app.save()
        self.app.render_calendar()

    def closeEvent(self, event) -> None:
        self.app.config["settings_geometry"] = geometry_string(self)
        self.app.save()
        self.app.settings_window = None
        super().closeEvent(event)

