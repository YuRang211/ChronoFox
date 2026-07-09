from __future__ import annotations

from datetime import date

from PySide6.QtGui import QIcon

from app_theme import resolve_theme
from schedule_window import PlanWindow


class PlanApp:
    def __init__(self) -> None:
        self.config = {"theme_mode": "light", "language": "ko", "font_family": ""}
        self.icon = QIcon()
        self.added: list[dict] = []

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def add_plan(self, plan: dict) -> None:
        self.added.append(plan)

    def update_plan(self, plan: dict) -> None:
        self.added.append(plan)


def test_clicking_second_color_button_selects_that_color(qtbot) -> None:
    app = PlanApp()
    today = date.today()
    window = PlanWindow(app, today)
    qtbot.addWidget(window)

    assert window.selected_color == PlanWindow.COLORS[0]

    window.color_buttons[1].click()

    assert window.selected_color == PlanWindow.COLORS[1]


def test_selected_color_is_saved_in_plan_payload(qtbot) -> None:
    app = PlanApp()
    today = date.today()
    window = PlanWindow(app, today)
    qtbot.addWidget(window)

    window.color_buttons[2].click()
    window.title_input.setText("Color test event")
    window.save_plan()

    assert len(app.added) == 1
    assert app.added[0]["color"] == PlanWindow.COLORS[2]
