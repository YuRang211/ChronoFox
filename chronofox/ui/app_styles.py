"""공용 QSS 조각 빌더 모음 (F3 스펙 D6 ①).

clock/styles.py의 "팔레트 인자를 받는 함수" 패턴을 앱 전역 공유 조각으로 확장한다.
여기 있는 함수들은 최소 2개 파일에서 구조가 동일하게 반복되던 QSS 조각만 담는다 —
값(폭·색·여백)이 다른 정도는 함수 인자로 흡수하되, 겉모습이 비슷할 뿐 실제로는 다른
프로퍼티/셀렉터 구성을 쓰는 스타일은 억지로 통합하지 않는다(D6 규칙: "룰이 다르면
같은 조각이 아니다").
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from chronofox.core.wallpaper_luma import FALLBACK_INK, FALLBACK_SCRIM_ENABLED
from chronofox.ui.app_theme import resolve_immersive_ink

CALENDAR_STYLE_DEFAULT = "desktop"
# W-D1: "immersive"는 추가일 뿐이다 — desktop/minimal/card 세 값과 기본값은 불변이고
# additive라 마이그레이션이 필요 없다.
CALENDAR_STYLE_KEYS = ("desktop", "minimal", "card", "immersive")
_CALENDAR_STYLE_ALIASES = {"grid": "desktop", "sheet": "desktop"}


def normalized_calendar_style(config) -> str:
    """저장값을 공개 프리셋 세 값 중 하나로 읽되 기존 alias는 보존한다."""
    style = str(config.get("calendar_style", CALENDAR_STYLE_DEFAULT))
    style = _CALENDAR_STYLE_ALIASES.get(style, style)
    return style if style in CALENDAR_STYLE_KEYS else CALENDAR_STYLE_DEFAULT


def calendar_layout_preset(config, colors: dict) -> dict:
    """메인 달력 전체 구조가 소비하는 프리셋 토큰을 반환한다.

    날짜 셀 그리기와 달리 헤더·그리드·보조 영역은 이 dict만 보고 구성한다. 프리셋 이름
    분기는 이 함수에 모아 두어 ``FoxCalendarApp.build_ui``가 구조 토큰만 소비하게 한다.
    """
    style = normalized_calendar_style(config)
    common = {
        "key": style,
        "header_mode": "desktop",
        "minimum_size": (840, 560),
        "header_height": 38,
        "header_margin": (12, 4, 12, 4),
        "header_spacing": 6,
        "search_width": 170,
        "weekday_height": 28,
        "grid_spacing": 0,
        "grid_margin": 0,
        "cell_minimum_height": 92,
        "footer_height": 0,
        "date_alignment": "left",
        "show_week_strip": False,
        "show_agenda": False,
        "show_week_numbers": True,
        "week_count": 5,
        "first_weekday": 0,
        "auxiliary_size": 0,
        "window_background": colors["bg"],
        "panel_background": colors["panel"],
        "grid_background": colors["cell"],
    }
    if style == "minimal":
        common.update({
            "header_mode": "classic",
            "minimum_size": (900, 620),
            "header_height": 42,
            "header_margin": (14, 6, 14, 6),
            "search_width": 170,
            "weekday_height": 28,
            "cell_minimum_height": 72,
            "footer_height": 0,
            "show_week_strip": True,
            "show_week_numbers": False,
            "week_count": 6,
            "first_weekday": 6,
            "auxiliary_size": 116,
        })
    elif style == "card":
        common.update({
            "header_mode": "agenda",
            "minimum_size": (980, 560),
            "header_height": 42,
            "header_margin": (14, 6, 14, 6),
            "search_width": 0,
            "weekday_height": 28,
            "cell_minimum_height": 72,
            "footer_height": 0,
            "show_agenda": True,
            "show_week_numbers": False,
            "week_count": 6,
            "first_weekday": 6,
            "auxiliary_size": 250,
        })
    elif style == "immersive":
        # W-D2: 구조는 데스크톱 작업판과 같은 "대형 월 격자"(header_mode="desktop"이
        # render_calendar()/previous_month/next_month의 35일·주차·4주 이동 로직을
        # 그대로 타게 한다 — 새 날짜 계산을 만들지 않는다). 시각적으로만 패널·테두리·
        # 그림자를 없앤다(desktop_note_calendar.py의 QSS/paintEvent가 이 key로 분기).
        # window_background="transparent"가 calendar_root QSS에 그대로 반영된다.
        common.update({
            "header_mode": "desktop",
            "minimum_size": (860, 600),
            "cell_minimum_height": 108,
            "window_background": "transparent",
            "panel_background": "transparent",
            "grid_background": "transparent",
        })
    return common


def calendar_geometry_for_style(config, style: str, fallback: str) -> str:
    """프리셋별 저장 기하를 우선하고 기존 단일 기하와 전달된 fallback 순으로 반환한다."""
    geometries = config.get("calendar_geometries", {})
    if isinstance(geometries, dict):
        value = geometries.get(style)
        if isinstance(value, str) and value.strip():
            return value
        if style == "desktop":
            raw_style = str(config.get("calendar_style", ""))
            alias_keys = [raw_style] if raw_style in _CALENDAR_STYLE_ALIASES else ["grid", "sheet"]
            for alias in alias_keys:
                value = geometries.get(alias)
                if isinstance(value, str) and value.strip():
                    return value
    legacy = config.get("calendar_geometry")
    if isinstance(legacy, str) and legacy.strip():
        return legacy
    return fallback


def calendar_week_dates(selected_day: date) -> list[date]:
    """선택 날짜가 속한 일요일~토요일 7일을 반환한다."""
    sunday = selected_day - timedelta(days=(selected_day.weekday() + 1) % 7)
    return [sunday + timedelta(days=offset) for offset in range(7)]


def desktop_calendar_dates(selected_day: date) -> list[date]:
    """선택 ISO 주를 세 번째 행에 둔 월요일 시작 35일을 반환한다."""
    monday = selected_day - timedelta(days=selected_day.weekday())
    first_day = monday - timedelta(weeks=2)
    return [first_day + timedelta(days=offset) for offset in range(35)]


def desktop_calendar_week_numbers(days: list[date]) -> list[int]:
    """35일 작업판의 각 행 ISO 주차를 반환한다."""
    return [days[offset].isocalendar().week for offset in range(0, len(days), 7)]


def calendar_agenda_entries(plans: list[dict], schedule: str) -> list[tuple[str, str]]:
    """선택 날짜 아젠다용 ``(시간, 제목)`` 행을 실제 저장 데이터에서 파생한다."""
    entries: list[tuple[str, str]] = []
    for plan in plans:
        title = str(plan.get("title", "")).strip()
        if not title:
            continue
        time_text = ""
        if plan.get("kind") != "long":
            try:
                start = datetime.fromisoformat(str(plan.get("start", "")))
                if "T" in str(plan.get("start", "")):
                    time_text = start.strftime("%H:%M")
            except ValueError:
                pass
        entries.append((time_text, title))
    entries.extend(
        ("", line.strip())
        for line in str(schedule).splitlines()
        if line.strip()
    )
    return entries


def calendar_text_summary(
    plans: list[dict],
    schedule: str,
    capacity: int = 3,
) -> tuple[list[str], int]:
    """데스크톱 셀의 평문을 시간순 일정, 무시간 일정, 메모 순으로 요약한다."""
    timed: list[tuple[datetime, str]] = []
    plain: list[str] = []
    for plan in plans:
        if plan.get("kind") == "long":
            continue
        title = str(plan.get("title", "")).strip()
        if not title:
            continue
        raw_start = str(plan.get("start", ""))
        try:
            start = datetime.fromisoformat(raw_start)
        except ValueError:
            plain.append(title)
            continue
        if "T" in raw_start:
            timed.append((start, f"{start:%H:%M} {title}"))
        else:
            plain.append(title)
    timed.sort(key=lambda item: item[0])
    entries = [text for _start, text in timed]
    entries.extend(plain)
    entries.extend(line.strip() for line in str(schedule).splitlines() if line.strip())
    shown = entries[: max(0, capacity)]
    return shown, max(0, len(entries) - len(shown))


def desktop_cell_text_flow(
    base_y: int,
    *,
    bar_height: int,
    ascent: int,
    line_height: int,
    has_bar: bool,
    has_title: bool,
    gap: int = 3,
) -> tuple[int, int]:
    """desktop 프리셋 셀에서 (장기 일정 제목 베이스라인, 첫 평문 줄 베이스라인)을 계산한다.

    CAL1(2026-07-22): 예전에는 제목을 `QRect`(상단 기준)로 그리고 y를 고정값(+14/+13)으로
    전진시켰는데, 이어지는 평문 줄 루프는 같은 y를 **베이스라인**으로 해석했다. 한 값이 두
    의미로 쓰이면서 막대·제목·평문 줄이 약 5~10px 겹쳤다. 이 함수가 셀 내부 수직 흐름을
    베이스라인 규약 하나로 계산하고, `DayCell.paintEvent`는 결과만 쓴다 — 겹침 불변식을
    Qt 없이 단위 테스트로 고정하기 위해 순수 함수로 분리했다.

    - 막대가 없으면 첫 평문 줄은 기존과 같이 `base_y`(베이스라인)에서 시작한다.
    - 막대가 있으면 막대 아래로 `gap`을 두고 제목/평문 줄을 차례로 내려 쌓는다.
    """
    if not has_bar:
        return base_y, base_y
    first_baseline = base_y + bar_height + gap + ascent
    if has_title:
        return first_baseline, first_baseline + line_height
    return first_baseline, first_baseline


def calendar_cell_style(config, colors: dict) -> dict:
    """calendar_style 설정(R16)에 따라 DayCell.paintEvent가 그릴 렌더링 파라미터를 계산한다.

    ``config``는 ``.get(key, default)``만 있으면 되는 duck-typed 인자다(AppStore/plain dict
    양쪽 모두 통과 — app_theme.resolve_theme(config)와 같은 관례). 이 함수만 프리셋 이름
    ("desktop"/"minimal"/"card")을 알고, DayCell.paintEvent는 반환된 dict의 구조적 값만
    참조한다(draw_grid/cell_tile/chip_mode/today_style 등) — 프리셋명 분기 금지(C2).

    기본값("desktop")은 셀 내부 평문을 사용한다.
    """
    style = normalized_calendar_style(config)

    if style == "desktop":
        return {
            "draw_grid": True,
            "cell_tile": False,
            "tile_radius": 0,
            "tile_margin": 0,
            "normal_bg": colors["cell"],
            "chip_mode": "text",
            "max_dots": 4,
            "today_style": "outline",
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
            "draw_grid": True,
            "cell_tile": False,
            "tile_radius": 0,
            "tile_margin": 0,
            "normal_bg": colors["cell"],
            "chip_mode": "bar",
            "max_dots": 4,
            "today_style": "outline",
        }
    if style == "immersive":
        # W-D3/W-D7/W-D9: 실제 계산 전(또는 실패 시) 항상 FALLBACK_INK(밝은 잉크)로
        # 그린다 — ImmersiveInkController가 첫 표시 이후 비동기로 이 dict를 in-place
        # 갱신한다(같은 dict 객체를 모든 DayCell.style이 참조하는 기존 R16 관례).
        # cell_fill/state_fill 둘 다 False라 today/selected를 포함해 어떤 상태도
        # 배경을 칠하지 않는다 — "패널도 테두리도 그림자도 없다"(W-D2 성격).
        ink = resolve_immersive_ink(FALLBACK_INK)
        return {
            "draw_grid": False,
            "cell_tile": False,
            "tile_radius": 0,
            "tile_margin": 0,
            "cell_fill": False,
            "state_fill": False,
            "normal_bg": colors["cell"],
            "chip_mode": "text",
            "max_dots": 4,
            "today_style": "line",
            "ink_mode": True,
            "scrim_active": FALLBACK_SCRIM_ENABLED,
            "ink": ink["ink"],
            "ink_soft": ink["ink_soft"],
            "ink_faint": ink["ink_faint"],
            "ink_accent": ink["ink_accent"],
            "veil": ink["veil"],
            "chip": ink["chip"],
        }
    # 정규화가 항상 지원값을 반환하므로 방어용 desktop 기본값이다.
    return {
        "draw_grid": True,
        "cell_tile": False,
        "tile_radius": 0,
        "tile_margin": 0,
        "normal_bg": colors["cell"],
        "chip_mode": "text",
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
