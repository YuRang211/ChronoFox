from __future__ import annotations

CHRONOFOX_PANEL_TOKENS: dict[str, str] = {
    "bg": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#f8f4f6",
    "border": "#eadfe5",
    "text": "#1f1018",
    "muted": "#7f5b6a",
    "accent": "#dc2626",
    "button_hover": "#f5e7eb",
    "settings_sidebar": "#fbf7f8",
    "settings_sidebar_selected": "#dc2626",
    "settings_sidebar_hover": "#f5e7eb",
    "settings_input": "#f9f5f7",
    "settings_input_hover": "#f4e8ed",
}

APPLE_SETTINGS_LIGHT_TOKENS: dict[str, str] = {
    "bg": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#f5f5f7",
    "border": "#e0e0e0",
    "text": "#1d1d1f",
    "muted": "#7a7a7a",
    "accent": "#0066cc",
    "accent_hover": "#0071e3",
    "button_hover": "#f0f0f0",
    "settings_sidebar": "#f5f5f7",
    "settings_sidebar_selected": "#0066cc",
    "settings_sidebar_hover": "#fafafc",
    "settings_input": "#ffffff",
    "settings_input_hover": "#fafafc",
}

APPLE_SETTINGS_DARK_TOKENS: dict[str, str] = {
    "bg": "#1c1c1e",
    "panel": "#1c1c1e",
    "panel2": "#2c2c2e",
    "border": "#3a3a3c",
    "text": "#f5f5f7",
    "muted": "#a1a1a6",
    "accent": "#0a84ff",
    "accent_hover": "#409cff",
    "button_hover": "#2c2c2e",
    "settings_sidebar": "#161617",
    "settings_sidebar_selected": "#0a84ff",
    "settings_sidebar_hover": "#242426",
    "settings_input": "#2c2c2e",
    "settings_input_hover": "#363638",
}


def chronofox_panel_colors(base: dict[str, str]) -> dict[str, str]:
    colors = dict(base)
    colors.update(CHRONOFOX_PANEL_TOKENS)
    return colors


def settings_panel_colors(base: dict[str, str]) -> dict[str, str]:
    colors = dict(base)
    bg = str(base.get("bg", "")).lstrip("#")
    try:
        red, green, blue = (int(bg[index : index + 2], 16) for index in (0, 2, 4))
        is_dark = (red * 299 + green * 587 + blue * 114) / 1000 < 128
    except ValueError:
        is_dark = False
    colors.update(APPLE_SETTINGS_DARK_TOKENS if is_dark else APPLE_SETTINGS_LIGHT_TOKENS)
    return colors
