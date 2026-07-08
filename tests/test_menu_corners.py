from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from desktop_note_calendar import FoxCalendarApp


def test_tray_menu_has_frameless_and_no_drop_shadow_flags(qtbot) -> None:
    """UX17: 트레이 메뉴는 네이티브 드롭섀도가 라운드 모서리 밖을 검게 칠하지 않도록
    FramelessWindowHint + NoDropShadowWindowHint를 WA_TranslucentBackground와 함께 가져야 한다."""
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    flags = app.tray_menu.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.NoDropShadowWindowHint
    assert app.tray_menu.testAttribute(Qt.WA_TranslucentBackground)


def test_tray_menu_style_uses_integer_alpha_rgba(qtbot) -> None:
    """UX17: QSS rgba() alpha는 Qt 파서가 오해석하지 않도록 0~255 정수여야 한다(0.94/0.96 같은 float 금지)."""
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    style = app.tray_menu_style()
    assert ", 0.9" not in style
    assert "rgba(" in style
