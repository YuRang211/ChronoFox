"""공용 QSS 조각 빌더 모음 (F3 스펙 D6 ①).

clock/styles.py의 "팔레트 인자를 받는 함수" 패턴을 앱 전역 공유 조각으로 확장한다.
여기 있는 함수들은 최소 2개 파일에서 구조가 동일하게 반복되던 QSS 조각만 담는다 —
값(폭·색·여백)이 다른 정도는 함수 인자로 흡수하되, 겉모습이 비슷할 뿐 실제로는 다른
프로퍼티/셀렉터 구성을 쓰는 스타일은 억지로 통합하지 않는다(D6 규칙: "룰이 다르면
같은 조각이 아니다").
"""

from __future__ import annotations


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

    clock/styles.py의 알람 목록, detail_schedule_window.py의 사이드패널 스크롤 영역이
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
