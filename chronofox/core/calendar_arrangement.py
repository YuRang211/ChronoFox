"""달력 디자인과 독립적인 날짜 배치 규칙.

이 모듈은 Qt를 import하지 않는다. 화면은 여기서 반환하는 날짜·행 구조만 소비하고,
색상·셀 표현·보조 패널은 기존 디자인 계층이 계속 담당한다.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta

CALENDAR_ARRANGEMENT_KEYS = ("center_week", "top_week", "month")
_WEEK_BASED_STYLES = {"desktop", "immersive", "grid", "sheet"}


def normalized_calendar_arrangement(config) -> str:
    """저장된 정렬값을 읽고, 값이 없거나 잘못됐으면 기존 디자인 동작을 보존한다."""
    arrangement = str(config.get("calendar_arrangement", ""))
    if arrangement in CALENDAR_ARRANGEMENT_KEYS:
        return arrangement
    style = str(config.get("calendar_style", "desktop"))
    return "center_week" if style in _WEEK_BASED_STYLES else "month"


def calendar_arrangement_spec(config) -> dict[str, object]:
    """격자 조립에 필요한 정렬 토큰을 반환한다.

    ``month``의 주차 열은 ``None``으로 두어 기존 디자인의 표시 여부를 보존한다.
    """
    arrangement = normalized_calendar_arrangement(config)
    if arrangement in {"center_week", "top_week"}:
        return {
            "key": arrangement,
            "week_count": 5,
            "first_weekday": 0,
            "show_week_numbers": True,
        }
    return {
        "key": "month",
        "week_count": 6,
        "first_weekday": 6,
        "show_week_numbers": None,
    }


def calendar_dates_for_arrangement(arrangement: str, anchor_day: date) -> list[date]:
    """정렬 방식과 기준일에 대응하는 연속 날짜 격자를 반환한다."""
    if arrangement == "month":
        weeks = calendar.Calendar(firstweekday=6).monthdatescalendar(
            anchor_day.year,
            anchor_day.month,
        )
        return [day for week in weeks for day in week]

    monday = anchor_day - timedelta(days=anchor_day.weekday())
    first_day = monday - timedelta(weeks=2) if arrangement == "center_week" else monday
    return [first_day + timedelta(days=offset) for offset in range(35)]


def calendar_week_numbers(days: list[date]) -> list[int]:
    """날짜 격자의 각 행에 대응하는 ISO 주차를 반환한다."""
    return [days[offset].isocalendar().week for offset in range(0, len(days), 7)]


def calendar_date_label(arrangement: str, day: date) -> str:
    """5주 정렬의 월 경계에만 월/일을 표시하고 월간 숫자 표기는 보존한다."""
    if arrangement in {"center_week", "top_week"} and day.day in {
        1, calendar.monthrange(day.year, day.month)[1],
    }:
        return f"{day.month}/{day.day}"
    return str(day.day)


def shift_calendar_anchor(arrangement: str, anchor_day: date, direction: int) -> date:
    """주 기반 정렬은 주 단위, 월 정렬은 월 단위로 기준일을 이동한다."""
    if arrangement != "month":
        return anchor_day + timedelta(weeks=direction)

    month_index = anchor_day.year * 12 + anchor_day.month - 1 + direction
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    day = min(anchor_day.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
