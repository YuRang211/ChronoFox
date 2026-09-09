"""알람 시각 입력을 부작용 없이 검증하는 Qt-free 헬퍼."""

from __future__ import annotations

import re

_ALARM_TIME_PATTERN = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]")


def parse_alarm_time(value: object) -> tuple[int, int] | None:
    """엄격한 24시간제 ``HH:MM`` 문자열을 ``(hour, minute)``로 변환합니다."""
    if not isinstance(value, str):
        return None
    if _ALARM_TIME_PATTERN.fullmatch(value) is None:
        return None
    hour_text, minute_text = value.split(":")
    return int(hour_text), int(minute_text)
