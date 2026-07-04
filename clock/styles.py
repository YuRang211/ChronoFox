from __future__ import annotations


class ClockStyleMixin:
    """QSS style fragments for the clock window."""

    def tab_style(self) -> str:
        c = self.colors
        return (
            f"QTabWidget::pane {{ border: 1px solid {c['border']}; border-radius: 9px; background: {c['panel']}; }}"
            f"QTabBar::tab {{ color: {c['muted']}; padding: 7px 12px; border: 1px solid transparent; border-radius: 7px; }}"
            f"QTabBar::tab:selected {{ color: {c['text']}; background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 7px; }}"
        )

    def header_frame_style(self) -> str:
        return "QFrame#clockHeader { background: transparent; border: none; }"

    def panel_style(self) -> str:
        return "QFrame#clockPanel { background: transparent; border: none; }"

    def footer_nav_style(self) -> str:
        c = self.colors
        return (
            f"QFrame#clockFooterNav {{ background: {c['panel']}; border-top: 1px solid {c['border']}; "
            "border-bottom-left-radius: 14px; border-bottom-right-radius: 14px; }}"
        )

    def input_style(self) -> str:
        c = self.colors
        return (
            f"QSpinBox {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 9px; padding: 8px 10px; font-size: 18px; font-weight: 700; }}"
            f"QSpinBox:hover {{ background: {c['panel']}; border: 1px solid {c['border']}; }}"
            "QSpinBox::up-button, QSpinBox::down-button { width: 0; height: 0; border: none; }"
        )

    def time_input_style(self) -> str:
        c = self.colors
        return (
            f"QTimeEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 18px 7px 8px; }}"
            f"QTimeEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            f"QTimeEdit::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 16px; border-left: 1px solid {c['border']}; border-bottom: 1px solid {c['border']}; border-top-right-radius: 8px; }}"
            f"QTimeEdit::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 16px; border-left: 1px solid {c['border']}; border-bottom-right-radius: 8px; }}"
        )

    def date_input_style(self) -> str:
        c = self.colors
        return (
            f"QDateEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QDateEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            "QDateEdit::drop-down { border: none; width: 18px; }"
        )

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QComboBox:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
            "QComboBox::drop-down { border: none; width: 20px; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; selection-background-color: {c['accent']}; }}"
        )

    def line_input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 8px; padding: 7px 10px; }}"
            f"QLineEdit:hover {{ background: {c['panel']}; border-color: {c['accent']}; }}"
        )

    def checkbox_style(self) -> str:
        c = self.colors
        return f"QCheckBox {{ color: {c['text']}; spacing: 5px; padding: 4px; }}"

    def alarm_list_style(self) -> str:
        c = self.colors
        return (
            f"QListWidget {{ background: transparent; color: {c['text']}; border: none; "
            "padding: 0; outline: none; }}"
            "QListWidget::item { padding: 6px 0; border: none; background: transparent; }"
            "QListWidget::item:selected { background: transparent; }"
            # UX15: 기본 굵은 스크롤바가 행 위를 덮어 보이던 것을 얇은 테마 스크롤바로 교체.
            "QScrollBar:vertical { background: transparent; width: 8px; margin: 2px 0; }"
            f"QScrollBar::handle:vertical {{ background: {c['border']}; min-height: 30px; border-radius: 4px; }}"
            f"QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

    def editor_style(self) -> str:
        c = self.colors
        return f"QFrame#alarmEditor {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 12px; }}"

    def button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['text']}; border: none; "
            "border-radius: 7px; padding: 7px 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ background: {c['border']}; }}"
        )

    def close_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel2']}; color: {c['muted']}; border: none; "
            "border-radius: 16px; font-size: 20px; font-weight: 500; padding-bottom: 2px; }}"
            f"QPushButton:hover {{ background: {c['border']}; color: {c['text']}; }}"
        )

    def round_button_style(self, primary: bool) -> str:
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
        c = self.colors
        return (
            f"QPushButton {{ background: {c['accent']}; color: white; border: none; border-radius: 26px; "
            "font-size: 30px; font-weight: 300; padding-bottom: 4px; }}"
            f"QPushButton:hover {{ background: {c['accent']}; }}"
        )
