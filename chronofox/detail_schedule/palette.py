"""Detail-schedule 창의 디자인 팔레트 정의입니다.

이 모듈 밖에서는 새 hex 리터럴을 추가하지 않는다 (app_theme.py의 다른 팔레트 파일과 동일 규칙).
"""

from __future__ import annotations

from chronofox.ui.app_theme import resolved_theme_mode

# Dark palette taken from the ChronoFox "Weekly Schedule View" design mockup.
DESIGN_DARK: dict[str, str] = {
    "bg": "#0a0a0c",
    "sidebar": "#0c0c0f",
    "panel": "#121215",
    "panel2": "#17171b",
    "hover": "#141418",
    "border": "#1b1b1f",
    "border_soft": "#161619",
    "grid": "#1c1c20",
    "text": "#ececef",
    "text_soft": "#dadade",
    "muted": "#7e7e86",
    "muted2": "#6a6a72",
    "faint": "#5a5a62",
    "fainter": "#3c3c44",
    "accent": "#60a5fa",
    "accent_hover": "#3b82f6",
    "card": "#121215",
    "card_border": "#1e1e22",
    "pill": "#ececef",
    "pill_text": "#16161c",
    "upgrade": "#dad6ec",
    "today_bg": "#131c2e",
}

# Light variant of the same design so the tab follows the app theme.
DESIGN_LIGHT: dict[str, str] = {
    "bg": "#ffffff",
    "sidebar": "#f6f6f8",
    "panel": "#ffffff",
    "panel2": "#ececef",
    "hover": "#f1f1f4",
    "border": "#e2e2e7",
    "border_soft": "#ececef",
    "grid": "#e9e9ee",
    "text": "#16161c",
    "text_soft": "#33333a",
    "muted": "#6a6a72",
    "muted2": "#8a8a92",
    "faint": "#a6a6ae",
    "fainter": "#c8c8d0",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "card": "#f7f7f9",
    "card_border": "#e6e6ea",
    "pill": "#16161c",
    "pill_text": "#ffffff",
    "upgrade": "#dad6ec",
    "today_bg": "#e8f1ff",
}


def design_palette(config: dict) -> dict[str, str]:
    """config의 테마 모드에 맞는 세부 일정 화면 색상 팔레트를 반환합니다."""
    mode = resolved_theme_mode(config)
    return dict(DESIGN_LIGHT if mode == "light" else DESIGN_DARK)
