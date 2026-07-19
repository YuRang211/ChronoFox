"""공용 QSS 조각 빌더 모음 (F3 스펙 D6 ①).

clock/styles.py의 "팔레트 인자를 받는 함수" 패턴을 앱 전역 공유 조각으로 확장한다.
여기 있는 함수들은 최소 2개 파일에서 구조가 동일하게 반복되던 QSS 조각만 담는다 —
값(폭·색·여백)이 다른 정도는 함수 인자로 흡수하되, 겉모습이 비슷할 뿐 실제로는 다른
프로퍼티/셀렉터 구성을 쓰는 스타일은 억지로 통합하지 않는다(D6 규칙: "룰이 다르면
같은 조각이 아니다").
"""

from __future__ import annotations

CALENDAR_STYLE_DEFAULT = "grid"


def calendar_cell_style(config, colors: dict) -> dict:
    """calendar_style 설정(R16)에 따라 DayCell.paintEvent가 그릴 렌더링 파라미터를 계산한다.

    ``config``는 ``.get(key, default)``만 있으면 되는 duck-typed 인자다(AppStore/plain dict
    양쪽 모두 통과 — app_theme.resolve_theme(config)와 같은 관례). 이 함수만 프리셋 이름
    ("grid"/"minimal"/"card")을 알고, DayCell.paintEvent는 반환된 dict의 구조적 값만
    참조한다(draw_grid/cell_tile/chip_mode/today_style 등) — 프리셋명 분기 금지(C2).

    기본값("grid")은 기존 DayCell.paintEvent 동작과 byte-identical이어야 한다(C7).
    """
    style = config.get("calendar_style", CALENDAR_STYLE_DEFAULT)

    if style == "sheet":
        # R16b B2: "시트" 프리셋 — DesktopCal풍 바탕화면 시트. normal 셀 배경은 무채움
        # (cell_fill=False — DayCell.paintEvent가 창 배경/투명도가 비치도록 칠하지 않는다),
        # 그리드 선은 유지하되 옅게(grid_alpha), 오늘은 card와 동일한 액센트 채움 타일,
        # 칩은 기존 bar 모드, other/selected/holiday 등 나머지 상태는 grid와 동일하게 둔다.
        return {
            "draw_grid": True,
            "cell_tile": False,
            "tile_radius": 0,
            "tile_margin": 0,
            "normal_bg": colors["cell"],
            "chip_mode": "bar",
            "max_dots": 4,
            "today_style": "tile",
            "cell_fill": False,
            "grid_alpha": 90,
        }
    if style == "minimal":
        return {
            "draw_grid": False,
            "cell_tile": False,
            "tile_radius": 0,
            "tile_margin": 0,
            "normal_bg": colors["cell"],
            "chip_mode": "dot",
            "max_dots": 4,
            "today_style": "circle",
        }
    if style == "card":
        return {
            "draw_grid": False,
            "cell_tile": True,
            "tile_radius": 10,
            "tile_margin": 3,
            "normal_bg": colors.get("panel2", colors.get("panel", colors["cell"])),
            "chip_mode": "bar",
            "max_dots": 4,
            "today_style": "tile",
        }
    # "grid"(기본) — 기존 렌더링과 동일한 값만 담는다.
    return {
        "draw_grid": True,
        "cell_tile": False,
        "tile_radius": 0,
        "tile_margin": 0,
        "normal_bg": colors["cell"],
        "chip_mode": "bar",
        "max_dots": 4,
        "today_style": "outline",
    }


def calendar_dot_summary(bars: list[dict], max_dots: int) -> tuple[list[dict], int]:
    """미니멀 달력 모양(dot chip)에서 보여줄 앞쪽 max_dots개와 넘친 개수를 계산한다.

    ``bars``는 잘라내기 전 전체 계획 막대 목록이어야 한다 — 넘침 배지("+N")는 셀에 실제로
    표시 가능한 칩 수(예: bar 모드의 [:3] 캡)가 아니라 그 날짜에 걸친 전체 계획 수를
    기준으로 계산한다(calendar-style-v1.md C3).
    """
    shown = bars[:max_dots]
    remaining = max(0, len(bars) - len(shown))
    return shown, remaining


def calendar_bar_summary(bars: list[dict], capacity: int) -> tuple[list[dict], int]:
    """bar 모드(grid/card 스타일)에서 실제로 그릴 막대와 넘침 개수를 계산한다(AUDIT-D2).

    ``bars``는 잘라내기 전 전체 계획 막대 목록(plan_bars_full)이어야 한다. ``capacity``는
    셀 높이가 실제로 그릴 수 있는 줄 수(호출부 paintEvent가 셀 높이로 계산)다.

    예전에는 무조건 [:3]으로 앞쪽 3개만 남긴 뒤, 그중 lane 값이 큰 막대가 셀 높이를
    넘치면 아무 표시 없이 그리지 않았다(감사 D2 — "09:00 주간 회의"가 이렇게 사라졌다:
    같은 날 다른 막대들과 나란히 저장된 lane 값이 우연히 커서 셀 밖으로 넘쳤는데,
    [:3] 절단은 이걸 미리 걸러내지 못했고 "+N" 표시도 없었다). 이제 lane이 낮은(먼저
    배정된) 막대부터 capacity개까지만 남기고, 남은 개수를 "+N" 배지로 알려준다 —
    선택된 막대는 항상 셀에 들어맞도록 호출부가 순번(rank)으로 다시 그린다.
    """
    ordered = sorted(bars, key=lambda bar: int(bar.get("lane", 0)))
    shown = ordered[: max(0, capacity)]
    remaining = max(0, len(bars) - len(shown))
    return shown, remaining


def thin_scrollbar_style(
    handle: str,
    hover: str,
    *,
    track: str = "transparent",
    width: int = 8,
    bar_margin: str = "2px 0",
    handle_margin: str = "",
    radius: int = 4,
) -> str:
    """화살표 버튼이 없는 얇은 세로 스크롤바.

    clock/styles.py의 알람 목록, detail_schedule/window.py의 사이드패널 스크롤 영역이
    이 형태를 공유한다(폭·트랙색·핸들 여백만 다름).
    """
    handle_margin_rule = f" margin: {handle_margin};" if handle_margin else ""
    return (
        f"QScrollBar:vertical {{ background: {track}; width: {width}px; margin: {bar_margin}; }}"
        f"QScrollBar::handle:vertical {{ background: {handle}; min-height: 30px; border-radius: {radius}px;{handle_margin_rule} }}"
        f"QScrollBar::handle:vertical:hover {{ background: {hover}; }}"
        "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
    )


def fancy_scrollbar_style(
    track: str,
    handle: str,
    hover: str,
    arrow: str,
    *,
    width: int = 12,
) -> str:
    """위/아래 화살표 버튼이 있는 세로 스크롤바.

    settings_window.py의 콘텐츠 스크롤 영역과 memo_window.py의 메모 본문 스크롤이
    이 형태를 공유한다(트랙/핸들/화살표 색만 다름). memo_window.py는 이 뒤에 가로
    스크롤바 규칙을 추가로 이어붙인다.
    """
    return (
        f"QScrollBar:vertical {{ background: {track}; width: {width}px; margin: 13px 0 13px 0; }}"
        f"QScrollBar::handle:vertical {{ background: {handle}; min-height: 28px; border-radius: 5px; margin: 1px 3px; }}"
        f"QScrollBar::handle:vertical:hover {{ background: {hover}; }}"
        f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ background: {track}; height: 13px; subcontrol-origin: margin; }}"
        "QScrollBar::sub-line:vertical { subcontrol-position: top; }"
        "QScrollBar::add-line:vertical { subcontrol-position: bottom; }"
        f"QScrollBar::up-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-bottom: 5px solid {arrow}; width: 0; height: 0; }}"
        f"QScrollBar::down-arrow:vertical {{ border-left: 4px solid transparent; border-right: 4px solid transparent; border-top: 5px solid {arrow}; width: 0; height: 0; }}"
        "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
    )
