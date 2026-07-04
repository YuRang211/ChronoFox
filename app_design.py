from __future__ import annotations

CHRONOFOX_PANEL_LIGHT_TOKENS: dict[str, str] = {
    "bg": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#f5f6f8",
    "border": "#e2e6ec",
    "text": "#171a20",
    "muted": "#64748b",
    "accent": "#2563eb",
    "button_hover": "#e8edf5",
    "settings_sidebar": "#f7f9fb",
    "settings_sidebar_selected": "#2563eb",
    "settings_sidebar_hover": "#e8edf5",
    "settings_input": "#f5f7fa",
    "settings_input_hover": "#eceff5",
}

CHRONOFOX_PANEL_DARK_TOKENS: dict[str, str] = {
    "bg": "#1c1c1e",
    "panel": "#1c1c1e",
    "panel2": "#2c2c2e",
    "border": "#3a3a3c",
    "text": "#f5f5f7",
    "muted": "#a1a1a6",
    "accent": "#60a5fa",
    "button_hover": "#2c2c2e",
    "settings_sidebar": "#161617",
    "settings_sidebar_selected": "#60a5fa",
    "settings_sidebar_hover": "#242426",
    "settings_input": "#2c2c2e",
    "settings_input_hover": "#363638",
}

APPLE_SETTINGS_LIGHT_TOKENS: dict[str, str] = {
    "bg": "#ffffff",
    "panel": "#ffffff",
    "panel2": "#f5f5f7",
    "border": "#e0e0e0",
    "text": "#1d1d1f",
    "muted": "#7a7a7a",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "button_hover": "#f0f0f0",
    "settings_sidebar": "#f5f5f7",
    "settings_sidebar_selected": "#2563eb",
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
    "accent": "#60a5fa",
    "accent_hover": "#3b82f6",
    "button_hover": "#2c2c2e",
    "settings_sidebar": "#161617",
    "settings_sidebar_selected": "#60a5fa",
    "settings_sidebar_hover": "#242426",
    "settings_input": "#2c2c2e",
    "settings_input_hover": "#363638",
}


def chronofox_panel_colors(base: dict[str, str]) -> dict[str, str]:
    colors = dict(base)
    colors.update(CHRONOFOX_PANEL_DARK_TOKENS if is_dark_palette(base) else CHRONOFOX_PANEL_LIGHT_TOKENS)
    return colors


def is_dark_palette(base: dict[str, str]) -> bool:
    bg = str(base.get("bg", "")).lstrip("#")
    try:
        red, green, blue = (int(bg[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return False
    return (red * 299 + green * 587 + blue * 114) / 1000 < 128


def settings_panel_colors(base: dict[str, str]) -> dict[str, str]:
    colors = dict(base)
    is_dark = is_dark_palette(base)
    colors.update(APPLE_SETTINGS_DARK_TOKENS if is_dark else APPLE_SETTINGS_LIGHT_TOKENS)
    return colors
