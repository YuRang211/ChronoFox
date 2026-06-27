from __future__ import annotations

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from app_constants import APP_FONT_DIR, DEFAULT_FONT_FAMILY

ACTIVE_FONT_FAMILY = DEFAULT_FONT_FAMILY
SYSTEM_FONT_FAMILIES: list[str] | None = None
APP_FONT_FALLBACKS = ["Pretendard Variable", "Pretendard", "Malgun Gothic", "맑은 고딕", "Segoe UI"]


def load_app_font(app: QApplication, config: dict) -> None:
    """Pretendard가 동봉되어 있으면 등록하고, 앱 전체 기본 폰트로 사용합니다."""
    global ACTIVE_FONT_FAMILY
    for font_path in (
        APP_FONT_DIR / "PretendardVariable.ttf",
        APP_FONT_DIR / "Pretendard-Regular.otf",
        APP_FONT_DIR / "Pretendard-Regular.ttf",
    ):
        if font_path.exists():
            QFontDatabase.addApplicationFont(str(font_path))
            break
    ACTIVE_FONT_FAMILY = config.get("font_family", DEFAULT_FONT_FAMILY)
    app.setFont(app_font())


def set_active_font_family(family: str) -> None:
    global ACTIVE_FONT_FAMILY
    ACTIVE_FONT_FAMILY = family or DEFAULT_FONT_FAMILY


def app_font(point_size: int = 9, weight: int = QFont.Normal) -> QFont:
    """현재 선택된 앱 글꼴을 반환합니다."""
    families = [ACTIVE_FONT_FAMILY]
    families.extend(family for family in APP_FONT_FALLBACKS if family not in families)
    font = QFont(families[0], point_size, weight)
    font.setFamilies(families)
    return font


def system_font_families() -> list[str]:
    """설정창 드롭다운용 시스템 폰트 목록을 한 번만 불러옵니다."""
    global SYSTEM_FONT_FAMILIES
    if SYSTEM_FONT_FAMILIES is None:
        families = sorted(set(QFontDatabase.families()), key=lambda item: item.casefold())
        priority = ["Noto Sans KR", "맑은 고딕", "Malgun Gothic", "SUIT", DEFAULT_FONT_FAMILY, "Pretendard"]
        ordered = [family for family in priority if family in families and family != DEFAULT_FONT_FAMILY]
        ordered.extend(family for family in families if family not in ordered and family != DEFAULT_FONT_FAMILY)
        SYSTEM_FONT_FAMILIES = ordered
    return SYSTEM_FONT_FAMILIES


def add_soft_shadow(widget: QWidget, colors: dict[str, str], blur: int = 18, alpha: int = 34) -> None:
    """패널과 카드가 배경에서 살짝 떠 보이도록 은은한 그림자를 추가합니다."""
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setOffset(0, 2)
    base = QColor("#000000")
    base.setAlpha(alpha)
    shadow.setColor(base)
    widget.setGraphicsEffect(shadow)


def parse_geometry(geometry: str, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    try:
        size, x_text, y_text = geometry.split("+")
        width_text, height_text = size.split("x")
        return int(width_text), int(height_text), int(x_text), int(y_text)
    except ValueError:
        return fallback


def geometry_string(widget: QWidget) -> str:
    return f"{widget.width()}x{widget.height()}+{widget.x()}+{widget.y()}"


def clamp_window_position(
    width: int,
    height: int,
    preferred_x: int,
    preferred_y: int,
    available: QRect,
    margin: int = 8,
) -> tuple[int, int]:
    """창 전체가 화면의 사용 가능 영역 안에 들어오도록 좌표를 보정합니다."""
    left = available.x() + margin
    top = available.y() + margin
    right = available.x() + available.width() - width - margin
    bottom = available.y() + available.height() - height - margin
    max_x = max(left, right)
    max_y = max(top, bottom)
    x = min(max(left, preferred_x), max_x)
    y = min(max(top, preferred_y), max_y)
    return x, y


def clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        child_widget = item.widget()
        if child_layout is not None:
            clear_layout(child_layout)
        if child_widget is not None:
            child_widget.setParent(None)
            child_widget.deleteLater()
