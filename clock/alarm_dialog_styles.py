from __future__ import annotations


class AlarmDialogStyleMixin:
    """QSS style fragments for the alarm editor dialog."""

    def ghost_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; "
            "border-radius: 16px; font-size: 24px; }}"
            f"QPushButton:hover {{ background: {c['panel2']}; color: {c['text']}; }}"
        )

    def time_box_style(self) -> str:
        c = self.colors
        return (
            f"QTimeEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 16px; font-size: 29px; font-weight: 800; padding: 8px 14px; }}"
            f"QTimeEdit:hover, QTimeEdit:focus {{ border-color: {c['accent']}; }}"
            "QTimeEdit::up-button, QTimeEdit::down-button { width: 0; height: 0; border: none; }"
        )

    def line_input_style(self) -> str:
        c = self.colors
        return (
            f"QLineEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 12px; padding: 0 13px; font-size: 14px; }}"
            f"QLineEdit:hover, QLineEdit:focus {{ border-color: {c['accent']}; }}"
        )

    def combo_style(self) -> str:
        c = self.colors
        return (
            f"QComboBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 11px; padding: 0 12px; font-size: 13px; }}"
            f"QComboBox:hover, QComboBox:focus {{ border-color: {c['accent']}; }}"
            "QComboBox::drop-down { border: none; width: 26px; }"
            "QComboBox::down-arrow { image: none; width: 0; height: 0; }"
            f"QAbstractItemView {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; selection-background-color: {c['accent']}; }}"
        )

    def date_input_style(self) -> str:
        c = self.colors
        return (
            f"QDateEdit {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 11px; padding: 0 12px; font-size: 13px; }}"
            f"QDateEdit:hover, QDateEdit:focus {{ border-color: {c['accent']}; }}"
            "QDateEdit::drop-down { border: none; width: 0; }"
        )

    def day_check_style(self) -> str:
        c = self.colors
        return (
            f"QCheckBox {{ background: {c['panel2']}; color: {c['muted']}; border: 1px solid {c['border']}; "
            "border-radius: 15px; padding: 6px 0; min-width: 32px; max-width: 32px; font-weight: 800; }}"
            f"QCheckBox:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}"
            f"QCheckBox:checked {{ background: {c['accent']}; border-color: {c['accent']}; color: white; }}"
            "QCheckBox::indicator { width: 0; height: 0; margin: 0; padding: 0; }"
        )

    def spin_style(self) -> str:
        c = self.colors
        return (
            f"QSpinBox {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 11px; padding: 0 12px; font-size: 13px; }}"
            f"QSpinBox:hover, QSpinBox:focus {{ border-color: {c['accent']}; }}"
            "QSpinBox::up-button, QSpinBox::down-button { width: 0; height: 0; border: none; }"
        )

    def primary_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['accent']}; color: white; border: none; border-radius: 12px; "
            "padding: 0 24px; font-size: 15px; font-weight: 800; }}"
            f"QPushButton:hover {{ background: {c['accent']}; }}"
        )

    def secondary_button_style(self) -> str:
        c = self.colors
        return (
            f"QPushButton {{ background: {c['panel']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 12px; padding: 0 24px; font-size: 15px; font-weight: 600; }}"
            f"QPushButton:hover {{ border-color: {c['accent']}; color: {c['accent']}; }}"
        )
