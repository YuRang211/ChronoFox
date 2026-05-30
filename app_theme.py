from __future__ import annotations

import winreg


THEMES = {
    "dark": {
        "bg": "#101416",
        "panel": "#171d20",
        "panel2": "#20292d",
        "border": "#2e3a40",
        "text": "#e8f0f2",
        "muted": "#95a5aa",
        "accent": "#77c7d4",
        "grid": "#1d383e",
        "weekday": "#183238",
        "cell": "#132428",
        "other": "#172125",
        "other_text": "#62777d",
        "saturday": "#8fb8d8",
        "sunday": "#d9969c",
        "today_bg": "#203235",
        "today_text": "#c7f1d4",
        "today_border": "#c7f1d4",
        "selected_bg": "#1f4952",
        "selected_text": "#effdff",
        "selected_border": "#77c7d4",
        "holiday": "#ff9fa8",
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
    },
    "light": {
        "bg": "#edf4f6",
        "panel": "#ffffff",
        "panel2": "#dce8eb",
        "border": "#b9ced5",
        "text": "#122a31",
        "muted": "#5c737a",
        "accent": "#2f8fe8",
        "grid": "#a9dce1",
        "weekday": "#9adce2",
        "cell": "#eafafb",
        "other": "#cfe3e6",
        "other_text": "#6f8b90",
        "saturday": "#3477aa",
        "sunday": "#b94e5a",
        "today_bg": "#fff6d6",
        "today_text": "#5d4a13",
        "today_border": "#d2ad3f",
        "selected_bg": "#d2f2ee",
        "selected_text": "#14383d",
        "selected_border": "#4aa8b2",
        "holiday": "#b12633",
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
    },
}

THEME_FALLBACK = dict(THEMES["dark"])

NOTE_THEMES = {
    "light": {
        "memo_bg": "#ffffff",
        "memo_bar": "#dce8eb",
        "memo_text": "#122a31",
        "memo_hover": "#c9dce1",
        "memo_scroll_track": "#eef5f7",
        "memo_scroll_handle": "#a9bdc4",
        "memo_scroll_handle_hover": "#7f98a0",
    },
    "default": {
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
        "memo_hover": "#ead157",
        "memo_scroll_track": "#f7e99a",
        "memo_scroll_handle": "#c7ac36",
        "memo_scroll_handle_hover": "#9d821d",
    },
    "dark": {
        "memo_bg": "#1d1f21",
        "memo_bar": "#2c2c2c",
        "memo_text": "#f2f2f2",
        "memo_hover": "#3a3a3a",
        "memo_scroll_track": "#151719",
        "memo_scroll_handle": "#3b3f42",
        "memo_scroll_handle_hover": "#c8d0d4",
    },
}

HOLIDAY_NAME_REPLACEMENTS = {
    "부처님오신날 대체 휴일": "대체공휴일",
    "신정연휴": "신정",
    "기독탄신일": "성탄절",
    " 대체 휴일": " 대체공휴일",
}


def windows_prefers_dark() -> bool:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return True


def prettify_holiday_name(name: str) -> str:
    """외부 휴일 데이터의 표현을 달력에 어울리는 짧은 한국어 이름으로 정리합니다."""
    if "대체" in name:
        return "대체공휴일"
    for source, replacement in HOLIDAY_NAME_REPLACEMENTS.items():
        name = name.replace(source, replacement)
    return name


def resolve_theme(config: dict) -> dict[str, str]:
    mode = config.get("theme_mode", "system")
    if mode == "system":
        mode = "dark" if windows_prefers_dark() else "light"
    colors = dict(THEME_FALLBACK)
    colors.update(THEMES.get(mode, {}))
    return colors


def resolve_note_theme(config: dict) -> dict[str, str]:
    colors = resolve_theme(config)
    colors.update(NOTE_THEMES.get(config.get("note_theme", "default"), NOTE_THEMES["default"]))
    colors["bg"] = colors["memo_bg"]
    return colors
