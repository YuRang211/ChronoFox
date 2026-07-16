"""ClockWindow 전용 QSS 스타일 문자열들을 모아 둔 ClockStyleMixin."""

from __future__ import annotations

from chronofox.ui.app_styles import thin_scrollbar_style


class ClockStyleMixin:
    """QSS style fragments for the clock window."""

    def tab_style(self) -> str:
        """탭 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 9px; background: {c['panel']}; }}"
            f"QTabBar::tab {{ color: {c['muted']}; padding: 7px 12px; border: 1px solid transparent; border-radius: 7px; }}"
            f"QTabBar::tab:selected {{ color: {c['text']}; background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 7px; }}"
        )

    def header_frame_style(self) -> str:
        """헤더 영역 QSS 스타일 문자열을 만듭니다."""
        return "QFrame#clockHeader { background: transparent; border: none; }"

    def panel_style(self) -> str:
        """패널 QSS 스타일 문자열을 만듭니다."""
        return "QFrame#clockPanel { background: transparent; border: none; }"

    def footer_nav_style(self) -> str:
        """하단 탭 내비게이션 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QFrame#clockFooterNav {{ background: {c['panel']}; border-top: 1px solid {c['border']}; "
            "border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }}"
        )

    def input_style(self) -> str:
        """입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QSpinBox {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 9px; padding: 8px 10px; font-size: 18px; font-weight: 700; }}"
            f"QSpinBox:hover {{ background: {c['panel']}; border: 1px solid {c['border']}; }}"
            "QSpinBox::up-button, QSpinBox::down-button { width: 0; height: 0; border: none; }"
        )

    def time_input_style(self) -> str:
        """시간 입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QTimeEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 18px 7px 8px; }}"
            f"QTimeEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            f"QTimeEdit::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 16px; border-left: 1px solid {c['border']}; border-bottom: 1px solid {c['border']}; border-top-right-radius: 8px; }}"
            f"QTimeEdit::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 16px; border-left: 1px solid {c['border']}; border-bottom-right-radius: 8px; }}"
        )

    def date_input_style(self) -> str:
        """날짜 입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QDateEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QDateEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            "QDateEdit::drop-down { border: none; width: 18px; }"
        )

    def combo_style(self) -> str:
        """콤보박스 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            "QComboBox::drop-down { border: none; width: 20px; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def line_input_style(self) -> str:
        """한 줄 입력창 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QLineEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
        )

    def checkbox_style(self) -> str:
        """체크박스 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return f"QCheckBox {{ color: {c['text']}; spacing: 5px; padding: 4px; }}"

    def alarm_list_style(self) -> str:
        """알람 목록 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QListWidget {{ background: transparent; color: {c['text']}; border: none; "
            "padding: 0; outline: none; }}"
            "QListWidget::item { padding: 6px 0; border: none; background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
            # UX15: 기본 굵은 스크롤바가 행 위를 덮어 보이던 것을 얇은 테마 스크롤바로 교체.
            + thin_scrollbar_style(c["border"], c["muted"])
        )

    def editor_style(self) -> str:
        """편집기 영역 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return f"QFrame#alarmEditor {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}"

    def button_style(self) -> str:
        """버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def close_button_style(self) -> str:
        """닫기 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 16px; font-size: 20px; font-weight: 500; padding-bottom: 2px; }}"
            f"QPushButton:hover {{ background: {c['border']}; color: {c['text']}; }}"
        )

    def round_button_style(self, primary: bool) -> str:
        """원형 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        if primary:
            return (
                f"QPushButton {{ background: {c['accent']}; color: white; border: none; border-radius: 39px; "
                "font-size: 16px; font-weight: 700; }}"
                f"QPushButton:hover {{ background: {c['primary'] if 'primary' in c else c['accent']}; }}"
            )
        return (
            f"QPushButton {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 39px; font-size: 15px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['panel2']}; }}"
        )

    def timer_button_style(self, primary: bool) -> str:
        """타이머 조작 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        if primary:
            return (
                f"QPushButton {{ background: {c['accent']}; color: white; border: none; "
                "border-radius: 10px; font-size: 16px; font-weight: 700; }}"
                f"QPushButton:hover {{ background: {c['accent']}; }}"
            )
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 10px; font-size: 15px; font-weight: 700; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def floating_add_button_style(self) -> str:
        """떠 있는 추가(+) 버튼 QSS 스타일 문자열을 만듭니다."""
        c = self.colors
        return (
            f"QPushButton {{ background: {c['accent']}; color: white; border: none; border-radius: 26px; "
            "font-size: 30px; font-weight: 300; padding-bottom: 4px; }}"
            f"QPushButton:hover {{ background: {c['accent']}; }}"
        )
