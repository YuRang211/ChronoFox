"""알람/타이머/스톱워치 로직 믹스인 모음 패키지.

R4-3b: 전용 시계 창(`ClockWindow`, `window.py`/`layout.py`/`nav.py`)은 진입점을 허브
알람 섹션(`chronofox.detail_schedule.alarms_section.AlarmsSectionMixin`)으로 옮긴 뒤
제거했다(H-D4·H-D10). 이 패키지에 남은 `alarms.py`(`ClockAlarmMixin`)·`timer.py`
(`ClockTimerMixin`/`AppTimerStateMixin`)·`styles.py`(`ClockStyleMixin`)·
`alarm_dialog.py`·`alarm_row.py`는 `FoxCalendarApp`(헤드리스 알람 발화)과 허브 알람
섹션이 함께 재사용하므로, 각 submodule에서 직접 import한다(패키지 최상위 재수출 없음)."""

from __future__ import annotations
