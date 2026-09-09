"""라이트/다크/시스템 테마 색상 팔레트를 정의하고, config로부터 현재 테마 색상을 계산하는 모듈."""

from __future__ import annotations

import winreg

from chronofox.core.wallpaper_luma import FALLBACK_INK, relative_luminance

PLAN_TEXT_DARK = "#000000"
PLAN_TEXT_LIGHT = "#ffffff"


def contrast_text_color(background: tuple[float, float, float]) -> str:
    """합성된 sRGB 배경(0~255)에 더 높은 대비를 주는 잉크색을 고른다."""
    luminance = relative_luminance(background)
    black_contrast = (luminance + 0.05) / 0.05
    white_contrast = 1.05 / (luminance + 0.05)
    return PLAN_TEXT_DARK if black_contrast >= white_contrast else PLAN_TEXT_LIGHT

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

# 테마와 무관한 브랜드 색과 상태 색도 이 팔레트에서만 정의한다.
IMPORTANT_STAR_COLOR = "#d9a441"

# 할 일의 경고 상태와 삭제 계열 액션은 같은 색을 공유한다.
DANGER_COLOR = "#d96f78"

# 계획(plan) 레인 배경색 팔레트. desktop_note_calendar.py의 달력 바 색상 순환과
# schedule_window.py의 사용자 선택용 색상 스와치가 이 다섯 색을 공유한다.
PLAN_LANE_COLORS: list[str] = ["#3abf7a", "#e47d7d", "#7d8bd9", IMPORTANT_STAR_COLOR, "#5aa7d9"]

# PlanWindow 색상 선택 버튼은 레인 팔레트에 보라색 한 가지를 더 얹은 6색 세트를 쓴다.
PLAN_COLOR_CHOICES: list[str] = [*PLAN_LANE_COLORS, "#9b7bd9"]

# 이머시브 잉크는 앱 테마와 별개로 벽지 밝기에 따라 선택한다.
# 알파가 있는 값은 QColor가 읽는 8자리 ARGB 형식이다.
IMMERSIVE_INK: dict[str, dict[str, str]] = {
    "light": {  # 어두운 벽지 위에 쓰는 밝은 잉크 (wallpaper_luma.INK_LIGHT)
        "ink": "#ffffff",
        "ink_soft": "#d1ffffff",  # 흰색 82% — 일정 문장
        "ink_faint": "#6bffffff",  # 흰색 42% — 흐린 보조 텍스트(인접 월 등)
        "ink_accent": "#ff9a8f",  # 공휴일·일요일
        "veil": "#db000000",  # 검정 86% — 스크림/헤일로
        "chip": "#29ffffff",  # 흰색 16% — 기간 막대 배경
    },
    "dark": {  # 밝은 벽지 위에 쓰는 어두운 잉크 (wallpaper_luma.INK_DARK)
        "ink": "#16191d",
        "ink_soft": "#d616191d",
        "ink_faint": "#6616191d",
        "ink_accent": "#b23a2e",
        "veil": "#e6ffffff",  # 흰색 90% — 스크림/헤일로
        "chip": "#1a16191d",
    },
}


def resolve_immersive_ink(kind: str) -> dict[str, str]:
    """`kind`(`wallpaper_luma.INK_LIGHT`/`INK_DARK`)에 대응하는 이머시브 잉크 토큰
    쌍을 반환합니다. 알 수 없는 kind는 `FALLBACK_INK`로 폴백합니다."""
    return dict(IMMERSIVE_INK.get(kind, IMMERSIVE_INK[FALLBACK_INK]))


def windows_prefers_dark() -> bool:
    """Windows 레지스트리를 조회해 시스템이 다크 모드를 쓰는지 확인합니다."""
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
    """config의 theme_mode에 맞는 색상 팔레트를 계산합니다."""
    mode = resolved_theme_mode(config)
    colors = dict(THEME_FALLBACK)
    colors.update(THEMES.get(mode, {}))
    return colors


def resolved_theme_mode(config: dict) -> str:
    """theme_mode가 'system'이면 실제 라이트/다크 중 어느 쪽을 쓸지 판단합니다."""
    mode = config.get("theme_mode", "system")
    if mode == "system":
        mode = "dark" if windows_prefers_dark() else "light"
    return mode if mode in THEMES else "dark"


def resolve_note_theme(config: dict) -> dict[str, str]:
    """메모 창에 적용할 테마 색상을 계산합니다."""
    colors = resolve_theme(config)
    note_mode = resolved_theme_mode(config)
    colors.update(NOTE_THEMES[note_mode])
    colors["bg"] = colors["memo_bg"]
    return colors
