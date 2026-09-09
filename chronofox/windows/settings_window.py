"""설정 컨트롤, 저장 콜백, 백업·복원 액션을 제공하는 host 독립 믹스인입니다.

허브가 QSS 훅과 ``self.app``·``self.tr()`` 계약을 제공하며 데이터 안전 로직은 이
모듈에서 공유합니다.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from functools import partial
from pathlib import Path

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QCompleter,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from chronofox.core.app_constants import (
    APP_DIR,
    APP_NAME,
    DEFAULT_FONT_FAMILY,
    DEFAULT_FONT_LABEL,
    REPO_ROOT,
)
from chronofox.core.app_hotkey import DEFAULT_QUICK_HOTKEY, format_hotkey_display
from chronofox.core.app_restore import BackupInfo, inspect_backup, restore_backup
from chronofox.core.calendar_arrangement import normalized_calendar_arrangement
from chronofox.core.holiday_country import (
    AUTO_COUNTRY_SETTING,
    detect_country_windows,
    supported_country_rows,
)
from chronofox.ui.app_i18n import SUPPORTED_LANGUAGES, normalize_language
from chronofox.ui.app_styles import normalized_calendar_style
from chronofox.ui.app_theme import resolve_theme
from chronofox.ui.app_ui import app_font, system_font_families
from chronofox.ui.app_widgets import ArrowComboBox, Switch, ThemeButton


class SettingCard(QFrame):
    """A reusable settings row that owns its title/description styling."""

    def __init__(self, title: str, desc: str, control: QWidget, colors: dict[str, str]) -> None:
        super().__init__()
        self.colors = colors
        self.title_label = QLabel(title)
        self.desc_label = QLabel(desc)
        control.setAccessibleName(title)
        control.setAccessibleDescription(desc)
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


class SettingsActionsMixin:
    """백업·복원·내보내기·업데이트 확인 액션을 제공합니다."""

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
            self._show_restore_warning(info.error)
            return

        if not self._confirm_restore(info):
            return

        # 자동 사전 백업이 열린 창의 디바운스 대기 중 초안까지 포함하도록 먼저 반영한다.
        try:
            self.app.persist_open_windows()
        except OSError:
            self._show_restore_warning("flush_failed")
            return

        result = restore_backup(Path(path), self.app.store)
        if not result.ok:
            if result.error == "recovery_failed":
                # 경고 대화상자의 중첩 이벤트 루프에서도 늦은 메모 저장이 실행될 수 있으므로
                # 사용자에게 알리기 전에 모든 런타임 저장 경로를 먼저 차단한다.
                self.app.skip_exit_flush = True
                self._show_restore_warning(result.error, result.rollback_path)
                instance = QApplication.instance()
                if instance is not None:
                    instance.quit()
                return
            self._show_restore_warning(result.error, result.rollback_path)
            return

        # 재시작 전 종료 경로가 옛 메모리로 복원본을 덮지 않게 즉시 가드를 세운다.
        self.app.skip_exit_flush = True
        self._notify_restart_required()
        self._restart_app()

    def _style_restore_message_box(self, box: QMessageBox) -> None:
        # 네이티브 밝은 배경에 부모의 다크 글자색만 상속되는 조합을 막는다.
        colors = resolve_theme(self.app.store)
        box.setStyleSheet(
            f"QMessageBox {{ background: {colors['panel']}; color: {colors['text']}; }}"
            f"QMessageBox QLabel {{ background: transparent; color: {colors['text']}; border: none; }}"
            f"QMessageBox QPushButton {{ background: {colors['panel2']}; color: {colors['text']}; "
            f"border: 1px solid {colors['border']}; border-radius: 4px; padding: 6px 12px; min-width: 64px; }}"
            f"QMessageBox QPushButton:hover {{ background: {colors['button_hover']}; }}"
        )
        box.setTextFormat(Qt.PlainText)
        box.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)

    def _show_restore_warning(self, error: str, rollback_path: str = "") -> None:
        box = QMessageBox(self)
        try:
            self._style_restore_message_box(box)
            box.setWindowTitle(APP_NAME)
            box.setIcon(QMessageBox.Warning)
            box.setText(self._restore_error_message(error, rollback_path))
            box.setStandardButtons(QMessageBox.Ok)
            box.exec()
        finally:
            box.deleteLater()

    def _restore_error_message(self, error: str, rollback_path: str = "") -> str:
        if error == "recovery_failed":
            return self.tr(
                "settings.dialog.restore.error.recovery_failed",
                "백업 복원과 자동 복구에 모두 실패했습니다. 데이터 보호를 위해 저장을 중단했으며, "
                "크로노폭스를 다시 시작하지 않고 종료합니다.\n\n복원 전 백업:\n{path}",
                path=rollback_path or "-",
            )
        messages = {
            "missing_manifest": self.tr("settings.dialog.restore.error.invalid", "올바른 크로노폭스 백업 파일이 아닙니다."),
            "invalid_zip": self.tr("settings.dialog.restore.error.invalid", "올바른 크로노폭스 백업 파일이 아닙니다."),
            "flush_failed": self.tr("settings.dialog.restore.error.flush", "현재 편집 내용을 저장하지 못해 복원을 중단했습니다."),
            "rollback_failed": self.tr("settings.dialog.restore.error.rollback", "복원 전 자동 백업을 만들지 못해 복원을 중단했습니다."),
            "extract_failed": self.tr("settings.dialog.restore.error.extract", "백업을 복원하지 못했지만 기존 데이터는 자동으로 복구했습니다."),
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
        self._style_restore_message_box(box)
        box.setWindowTitle(APP_NAME)
        box.setText(summary)
        box.setIcon(QMessageBox.Warning)
        confirm_button = box.addButton(self.tr("settings.dialog.restore.confirm", "복원"), QMessageBox.AcceptRole)
        box.addButton(self.tr("settings.dialog.restore.cancel", "취소"), QMessageBox.RejectRole)
        box.setDefaultButton(confirm_button)
        box.exec()
        return box.clickedButton() == confirm_button

    def _notify_restart_required(self) -> None:
        """복원본을 다시 읽도록 즉시 재시작이 필요함을 알립니다."""
        box = QMessageBox(self)
        self._style_restore_message_box(box)
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
            # 소스 실행은 패키지 파일이 아니라 저장소 루트 진입점을 다시 연다.
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

    def check_for_updates(self) -> None:
        """업데이트 검사를 controller에 위임한다. 이 클릭 전에는 네트워크를 쓰지 않는다."""
        controller = getattr(self.app, "update_controller", None)
        if controller is not None:
            controller.check_for_updates()

    def start_update(self) -> None:
        """확인된 업데이트의 설치/공식 페이지 열기를 controller에 위임한다."""
        controller = getattr(self.app, "update_controller", None)
        if controller is not None:
            controller.start_update()


class SettingsControlsMixin:
    """설정 컨트롤 위젯 빌더(스위치/콤보/슬라이더/카드/액션 버튼)와 그 저장 콜백.
    허브 설정 섹션이 그대로 상속해 쓴다(R4-4a/R4-4b, H-D3) — 테마 전환·언어·폰트·투명도·
    달력 모양·핀 모드·단축키·공휴일·자동 실행 로직을 두 번 구현하지 않는다.

    REQUIRED (host가 제공):
    - `self.app`(FoxCalendarApp), `self.colors`(dict), `self.tr()`(TrMixin)
    - 목록: `self.setting_cards`, `self.info_labels`, `self.theme_buttons`,
      `self.combo_boxes`, `self.switches`, `self.opacity_widgets`,
      `self.opacity_sliders`, `self.opacity_spins`(list)
    - 단일 값: `self.calendar_style_combo`, `self.calendar_arrangement_combo`, `self.font_combo_box`,
      `self.language_combo_box`(초기값 None, 위젯 생성 시 이 믹스인이 채운다)
    - 저장 콜백(host별 지오메트리/제목/리빌드가 다르므로 host가 직접 구현):
      `self.set_theme(mode)`, `self.set_calendar_style(style)`,
      `self.set_language(language)`, `self.set_font_family(family)`
    - QSS 훅(팔레트가 host마다 달라 이 믹스인은 값을 몰라도 되게 위임):
      `self.settings_input_style()`, `self.settings_opacity_slider_style()`,
      `self.settings_action_button_style()`
    """

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

    def toggle_holidays(self, enabled: bool) -> None:
        """공휴일 표시 여부를 토글합니다."""
        self.app.store.set("holiday_enabled", enabled)
        self.app.save()
        self.app.render_calendar()

    def holiday_country_control(self) -> QComboBox:
        """공휴일 계산에 쓸 국가를 고르는 콤보박스를 만듭니다(P-2, HL-D4/D5/D9).

        250개국이라 편집 가능 콤보 + `QCompleter`(부분 문자열·대소문자 무관)로 입력한
        글자가 포함된 국가를 바로 찾을 수 있게 한다. 첫 항목은 "자동 감지"(현재 감지된
        코드를 괄호로 보여준다), 나머지는 `supported_country_rows()`가 만든
        `이름 (코드)` 형태를 그대로 쓴다 — 하위 지역(주/도)은 다루지 않는다(HL-D9)."""
        combo = ArrowComboBox(self.colors)
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.NoInsert)

        detected = detect_country_windows()
        detected_label = detected or self.tr("settings.program.holiday_country.unknown", "알 수 없음")
        combo.addItem(
            self.tr("settings.program.holiday_country.auto", "자동 감지 (현재: {country})", country=detected_label),
            AUTO_COUNTRY_SETTING,
        )
        for code, label in supported_country_rows():
            combo.addItem(label, code)

        completer = combo.completer()
        if completer is not None:
            completer.setCompletionMode(QCompleter.PopupCompletion)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)

        raw_current = str(self.app.store.get("holiday_country", "auto") or "auto")
        current = raw_current if raw_current.strip().lower() == AUTO_COUNTRY_SETTING else raw_current.upper()
        index = combo.findData(current)
        combo.setCurrentIndex(max(0, index))
        combo.currentIndexChanged.connect(lambda _index, box=combo: self.on_holiday_country_combo_changed(box))
        combo.setStyleSheet(self.settings_input_style())
        combo.setFixedWidth(230)
        self.combo_boxes.append(combo)
        return combo

    def on_holiday_country_combo_changed(self, combo: QComboBox) -> None:
        """공휴일 국가 콤보박스 선택이 바뀌면 새 국가를 적용합니다."""
        code = combo.currentData()
        if code is None:
            return
        if hasattr(self.app, "set_holiday_country"):
            self.app.set_holiday_country(str(code))
        else:
            self.app.store.set("holiday_country", str(code))
            self.app.save()
            self.app.render_calendar()

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
        button.setStyleSheet(self.settings_action_button_style())
        button.clicked.connect(callback)
        button.setFixedHeight(34)
        return button

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
        """메인 달력의 공개 프리셋 다섯 가지를 고르는 드롭다운(W-D1: immersive 추가,
        S-D1: P-3c에서 fullmonth 추가)."""
        combo = ArrowComboBox(self.colors)
        options = [
            ("desktop", self.tr("settings.theme.calendar_style.desktop", "데스크톱 작업판")),
            ("minimal", self.tr("settings.theme.calendar_style.minimal", "미니멀")),
            ("card", self.tr("settings.theme.calendar_style.card", "셀 카드")),
            ("immersive", self.tr("settings.theme.calendar_style.immersive", "이머시브")),
            ("fullmonth", self.tr("settings.theme.calendar_style.fullmonth", "전체 월 시트")),
        ]
        for style, label in options:
            combo.addItem(label, style)
        current = normalized_calendar_style(self.app.store)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(self.on_calendar_style_combo_changed)
        combo.setStyleSheet(self.settings_input_style())
        combo.setFixedWidth(230)
        self.calendar_style_combo = combo
        self.combo_boxes.append(combo)
        return combo

    def on_calendar_style_combo_changed(self, _index: int) -> None:
        combo = self.calendar_style_combo
        if combo is None:
            return
        self.set_calendar_style(str(combo.currentData()))

    def calendar_arrangement_selector(self) -> QWidget:
        """디자인과 독립적인 날짜 배치 방식 세 가지를 고르는 드롭다운."""
        combo = ArrowComboBox(self.colors)
        options = [
            (
                "center_week",
                self.tr("settings.theme.calendar_arrangement.center_week", "금주 중앙"),
            ),
            (
                "top_week",
                self.tr("settings.theme.calendar_arrangement.top_week", "금주 상단"),
            ),
            (
                "month",
                self.tr("settings.theme.calendar_arrangement.month", "달마다"),
            ),
        ]
        for arrangement, label in options:
            combo.addItem(label, arrangement)
        current = normalized_calendar_arrangement(self.app.store)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(self.on_calendar_arrangement_combo_changed)
        combo.setStyleSheet(self.settings_input_style())
        combo.setFixedWidth(230)
        self.calendar_arrangement_combo = combo
        self.combo_boxes.append(combo)
        return combo

    def on_calendar_arrangement_combo_changed(self, _index: int) -> None:
        combo = self.calendar_arrangement_combo
        if combo is None:
            return
        self.app.set_calendar_arrangement(str(combo.currentData()))

    def immersive_scrim_control(self) -> Switch:
        """P-3b W-D8: 이머시브 프리셋의 혼합 밝기 스크림 토글 — 기본 OFF(순수 v1)."""
        control = Switch(bool(self.app.store.get("immersive_scrim_enabled", False)), self.colors)
        self.switches.append(control)
        control.toggled.connect(self.on_immersive_scrim_toggled)
        return control

    def on_immersive_scrim_toggled(self, enabled: bool) -> None:
        """스크림 스위치 콜백 — store 저장 후 (이머시브가 활성이면) 즉시 재판정한다."""
        self.app.store.set("immersive_scrim_enabled", enabled)
        self.app.save()
        if hasattr(self.app, "apply_immersive_scrim_setting"):
            self.app.apply_immersive_scrim_setting()

    def font_combo(self) -> QComboBox:
        """기본 폰트를 고르는 콤보박스를 만듭니다."""
        combo = ArrowComboBox(self.colors)
        current = self.app.store.get("font_family", DEFAULT_FONT_FAMILY)
        combo.addItem(self.font_label(current), current)
        combo.currentIndexChanged.connect(self.on_font_combo_changed)
        combo.setStyleSheet(self.settings_input_style())
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

    def language_combo(self) -> QComboBox:
        """표시 언어를 고르는 콤보박스를 만듭니다."""
        combo = ArrowComboBox(self.colors)
        current = normalize_language(self.app.store.get("language", "ko"))
        for code, label in SUPPORTED_LANGUAGES.items():
            combo.addItem(label, code)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.currentIndexChanged.connect(self.on_language_combo_changed)
        combo.setStyleSheet(self.settings_input_style())
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
        slider.setStyleSheet(self.settings_opacity_slider_style())
        self.opacity_sliders.append(slider)
        spin.setStyleSheet(self.settings_input_style())
        self.opacity_spins.append(spin)
        layout.addWidget(slider)
        layout.addWidget(spin)
        widget.setFixedWidth(220)
        return widget
