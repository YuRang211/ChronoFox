from __future__ import annotations

from app_theme import resolve_note_theme, resolved_theme_mode


def test_note_theme_follows_light_global_theme() -> None:
    colors = resolve_note_theme({"theme_mode": "light"})

    assert resolved_theme_mode({"theme_mode": "light"}) == "light"
    assert colors["bg"] == colors["memo_bg"]
    assert colors["memo_bg"] == "#ffffff"


def test_note_theme_follows_dark_global_theme() -> None:
    colors = resolve_note_theme({"theme_mode": "dark"})

    assert resolved_theme_mode({"theme_mode": "dark"}) == "dark"
    assert colors["bg"] == colors["memo_bg"]
    assert colors["memo_bg"] == "#1d1f21"
