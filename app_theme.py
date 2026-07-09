from __future__ import annotations

import winreg

THEMES = {
    "dark": {
        "bg": "#131315",
        "panel": "#1b1b1d",
        "panel2": "#232326",
        "border": "#2f3035",
        "text": "#eef2f7",
        "muted": "#94a3b8",
        "accent": "#60a5fa",
        "grid": "#25272b",
        "weekday": "#151518",
        "cell": "#151a1d",
        "other": "#121619",
        "other_text": "#5f6875",
        "saturday": "#60a5fa",
        "sunday": "#f87171",
        "today_bg": "#182332",
        "today_text": "#dbeafe",
        "today_border": "#93c5fd",
        "selected_bg": "#1d2a34",
        "selected_text": "#effdff",
        "selected_border": "#60a5fa",
        "holiday": "#f87171",
        "header": "#1b1b1d",
        "input_bg": "#222225",
        "input_border": "#34363b",
        "button_hover": "#2a2b30",
        "memo_bg": "#fff7b8",
        "memo_bar": "#f5dc65",
        "memo_text": "#24210e",
    },
    "light": {
        "bg": "#f6f8fb",
        "panel": "#ffffff",
        "panel2": "#eef2f7",
        "border": "#d7dde7",
        "text": "#172033",
        "muted": "#64748b",
        "accent": "#2563eb",
        "grid": "#e4e8ef",
        "weekday": "#f2f5f9",
        "cell": "#fbfcfe",
        "other": "#f3f6fa",
        "other_text": "#9aa6b6",
        "saturday": "#2563eb",
        "sunday": "#dc2626",
        "today_bg": "#e8f1ff",
        "today_text": "#1d4ed8",
        "today_border": "#60a5fa",
        "selected_bg": "#eaf2ff",
        "selected_text": "#172033",
        "selected_border": "#2563eb",
        "holiday": "#dc2626",
        "header": "#ffffff",
        "input_bg": "#f5f7fb",
        "input_border": "#d7dde7",
        "button_hover": "#e8edf5",
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

# 테마와 무관하게 고정된 브랜드 색 토큰 (D6 ②: 팔레트 정의 파일 밖 리터럴 hex 금지).
# "중요" 별 표시는 다크/라이트 모드 모두에서 동일한 앰버색을 쓴다.
IMPORTANT_STAR_COLOR = "#d9a441"

# 계획(plan) 레인 배경색 팔레트. desktop_note_calendar.py의 달력 바 색상 순환과
# schedule_window.py의 사용자 선택용 색상 스와치가 이 다섯 색을 공유한다.
PLAN_LANE_COLORS: list[str] = ["#3abf7a", "#e47d7d", "#7d8bd9", IMPORTANT_STAR_COLOR, "#5aa7d9"]

# PlanWindow 색상 선택 버튼은 레인 팔레트에 보라색 한 가지를 더 얹은 6색 세트를 쓴다.
PLAN_COLOR_CHOICES: list[str] = [*PLAN_LANE_COLORS, "#9b7bd9"]


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
    mode = resolved_theme_mode(config)
    colors = dict(THEME_FALLBACK)
    colors.update(THEMES.get(mode, {}))
    return colors


def resolved_theme_mode(config: dict) -> str:
    mode = config.get("theme_mode", "system")
    if mode == "system":
        mode = "dark" if windows_prefers_dark() else "light"
    return mode if mode in THEMES else "dark"


def resolve_note_theme(config: dict) -> dict[str, str]:
    colors = resolve_theme(config)
    note_mode = resolved_theme_mode(config)
    colors.update(NOTE_THEMES[note_mode])
    colors["bg"] = colors["memo_bg"]
    return colors
