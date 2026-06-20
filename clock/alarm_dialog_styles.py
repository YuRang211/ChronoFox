from __future__ import annotations


class AlarmDialogStyleMixin:
    """QSS style fragments for the alarm editor dialog."""

    def ghost_button_style(self) -> str:
        c = self.colors
        return f"QPushButton {{ background: transparent; color: {c['muted']}; border: none; font-size: 24px; }}"

    def time_box_style(self) -> str:
        c = self.colors
        return (
            f"QTimeEdit {{ background: {c['panel2']}; color: {c['text']}; border: 1px solid {c['border']}; "
            "border-radius: 16px; font-size: 29px; font-weight: 800; padding: 8px 24px 8px 10px; }}"
            f"QTimeEdit:hover, QTimeEdit:focus {{ border-color: {c['accent']}; }}"
            f"QTimeEdit::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 20px; border-left: 1px solid {c['border']}; border-bottom: 1px solid {c['border']}; border-top-right-radius: 16px; background: {c['panel']}; }}"
            f"QTimeEdit::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border-left: 1px solid {c['border']}; border-bottom-right-radius: 16px; background: {c['panel']}; }}"
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
            "QDateEdit::drop-down { border: none; width: 24px; }"
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
            "border-radius: 11px; padding: 0 20px 0 10px; font-size: 13px; }}"
            f"QSpinBox:hover, QSpinBox:focus {{ border-color: {c['accent']}; }}"
            f"QSpinBox::up-button {{ subcontrol-origin: border; subcontrol-position: top right; width: 18px; border-left: 1px solid {c['border']}; border-bottom: 1px solid {c['border']}; border-top-right-radius: 11px; background: {c['panel2']}; }}"
            f"QSpinBox::down-button {{ subcontrol-origin: border; subcontrol-position: bottom right; width: 18px; border-left: 1px solid {c['border']}; border-bottom-right-radius: 11px; background: {c['panel2']}; }}"
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
