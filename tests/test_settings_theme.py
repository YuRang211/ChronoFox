from __future__ import annotations

from app_design import settings_panel_colors
from app_theme import resolve_theme


def test_settings_panel_colors_follow_light_theme() -> None:
    colors = settings_panel_colors(resolve_theme({"theme_mode": "light"}))

    assert colors["bg"] == "#ffffff"
    assert colors["text"] == "#1d1d1f"
    assert colors["settings_sidebar"] == "#f5f5f7"


def test_settings_panel_colors_follow_dark_theme() -> None:
    colors = settings_panel_colors(resolve_theme({"theme_mode": "dark"}))

    assert colors["bg"] == "#1c1c1e"
    assert colors["text"] == "#f5f5f7"
    assert colors["settings_sidebar"] == "#161617"
