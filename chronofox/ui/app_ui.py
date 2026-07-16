"""폰트 로딩·창 지오메트리 문자열 변환·화면 밖 위치 보정 같은 공용 Qt UI 헬퍼 모음."""

from __future__ import annotations

import html as _html

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QGraphicsDropShadowEffect, QWidget

from chronofox.core.app_constants import APP_FONT_DIR, DEFAULT_FONT_FAMILY

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
    """active 폰트 family를 설정합니다."""
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
    """'WxH+X+Y' 형식의 지오메트리 문자열을 (width, height, x, y) 튜플로 파싱합니다."""
    try:
        size, x_text, y_text = geometry.split("+")
        width_text, height_text = size.split("x")
        return int(width_text), int(height_text), int(x_text), int(y_text)
    except ValueError:
        return fallback


def geometry_string(widget: QWidget) -> str:
    """위젯의 현재 위치/크기를 'WxH+X+Y' 문자열로 만듭니다."""
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


def meta_segments_html(
    segments: list[tuple[str, str]],
    normal_color: str,
    danger_color: str,
    separator: str = " · ",
) -> str:
    """(text, role) 세그먼트 목록을 role별로 색을 입힌 rich-text HTML로 합칩니다.

    AUDIT-D1 수정: 예전에는 메타라인 전체를 danger 색으로 칠했다(스트릭·단계 같은
    긍정 정보까지 붉게). 이제 role == "danger"인 세그먼트만 danger_color, 그 외는
    normal_color를 쓴다. QLabel의 rich-text 자동 인식(Qt::AutoText)으로 그대로
    setText() 가능하다.
    """
    spans = []
    for text, role in segments:
        color = danger_color if role == "danger" else normal_color
        spans.append(f'<span style="color:{color};">{_html.escape(str(text))}</span>')
    return separator.join(spans)


def clear_layout(layout) -> None:
    """레이아웃에 담긴 자식 위젯/레이아웃을 모두 제거합니다."""
    while layout.count():
        item = layout.takeAt(0)
        child_layout = item.layout()
        child_widget = item.widget()
        if child_layout is not None:
            clear_layout(child_layout)
        if child_widget is not None:
            child_widget.setParent(None)
            child_widget.deleteLater()
