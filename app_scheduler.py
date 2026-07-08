"""F2: 알람 · 리마인더 · 날짜 롤오버를 단일 1초 tick으로 구동하는 스케줄러.

설계 근거: planning/specs/notification-engine.md (D1~D12, 시나리오 S1~S12).
코어(NotificationScheduler, due_occurrence_today)는 Qt에 의존하지 않는다 — 시간 주입
(``now_fn``)만으로 테스트 가능해야 한다(D12). Qt 타이머 연결은 이 모듈을 사용하는
쪽(FoxCalendarApp)에서 얇은 어댑터로 감싼다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta


def due_occurrence_today(alarm: dict, now: datetime) -> datetime | None:
    """오늘(now 날짜 기준) 이 알람이 울려야 할 HH:MM 시각을 돌려준다.

    ``clock/alarms.py``의 ``next_alarm_occurrence``(미래 방향 탐색)의 역방향 버전이다:
    "오늘이 발화 대상일인가"만 판정하고, 아니면 None을 돌려준다.
    """
    try:
        hour, minute = (int(part) for part in str(alarm.get("time", "")).split(":"))
    except ValueError:
        return None
    today = now.date()
    if alarm.get("kind") == "date":
        try:
            day = date.fromisoformat(str(alarm.get("date", "")))
        except ValueError:
            return None
        if day != today:
            return None
    else:
        repeat_days = alarm.get("repeat_days", [0, 1, 2, 3, 4, 5, 6])
        if today.weekday() not in repeat_days:
            return None
    return datetime(today.year, today.month, today.day, hour, minute)


def _snooze_due(alarm: dict, now: datetime) -> bool:
    """D9: 스누즈는 창 제한 없이 ``snoozed_until <= now``면 즉시 발화 대상이다."""
    value = str(alarm.get("snoozed_until", ""))
    if not value:
        return False
    try:
        snoozed_until = datetime.fromisoformat(value)
    except ValueError:
        return False
    if snoozed_until.tzinfo is None and now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    elif snoozed_until.tzinfo is not None and now.tzinfo is None:
        snoozed_until = snoozed_until.astimezone().replace(tzinfo=None)
    return now >= snoozed_until


class NotificationScheduler:
    """알람·리마인더·날짜 롤오버를 단일 1초 tick으로 구동한다. 코어는 Qt 비의존."""

    JUMP_THRESHOLD = timedelta(seconds=90)
    CATCHUP_WINDOW = timedelta(minutes=10)
    REMINDER_SCAN_INTERVAL = 30

    def __init__(
        self,
        now_fn: Callable[[], datetime] = datetime.now,
        alarms_fn: Callable[[], list[dict]] | None = None,
    ) -> None:
        self.now_fn = now_fn
        self.alarms_fn = alarms_fn if alarms_fn is not None else (lambda: [])
        self.last_tick: datetime | None = None
        self.tick_count = 0
        self.last_jump: bool = False

        # 콜백 목록. 마킹(발화 예정 표시)이 콜백 호출보다 먼저 일어나므로
        # tick()은 절대 블로킹하지 않는다 (D6).
        self.on_alarm_due: list[Callable[[dict], None]] = []
        self.on_alarms_missed: list[Callable[[list[dict]], None]] = []
        self.on_reminder_scan: list[Callable[[], None]] = []
        self.on_day_changed: list[Callable[[], None]] = []

    def tick(self) -> None:
        now = self.now_fn()

        self.last_jump = self.last_tick is not None and (now - self.last_tick) > self.JUMP_THRESHOLD
        day_rolled = self.last_tick is not None and now.date() != self.last_tick.date()

        self._scan_alarms(now)

        self.tick_count += 1
        if self.tick_count % self.REMINDER_SCAN_INTERVAL == 0:
            for callback in list(self.on_reminder_scan):
                callback()

        if day_rolled:
            for callback in list(self.on_day_changed):
                callback()

        self.last_tick = now

    def _scan_alarms(self, now: datetime) -> None:
        today = now.date().isoformat()
        missed: list[dict] = []
        for alarm in self.alarms_fn():
            if not alarm.get("enabled", True):
                continue

            if _snooze_due(alarm, now):
                # D9: 스누즈는 catch-up 창과 무관하게 즉시 발화.
                alarm["snoozed_until"] = ""
                alarm["last_triggered"] = today
                for callback in list(self.on_alarm_due):
                    callback(alarm)
                continue

            if alarm.get("last_triggered") == today:
                continue  # D4: repeat dedupe (오늘 이미 발화/요약 처리됨)

            due = due_occurrence_today(alarm, now)
            if due is None or due > now:
                continue

            if now < due + self.CATCHUP_WINDOW:
                # D2: due-based 발화 — 정각 폴링 일치와 무관하게 기한 경과로 판정.
                alarm["last_triggered"] = today
                for callback in list(self.on_alarm_due):
                    callback(alarm)
            else:
                # D3: catch-up 창을 넘긴 알람은 모달 대신 요약 알림 대상.
                alarm["last_triggered"] = today
                missed.append(alarm)

        if missed:
            for callback in list(self.on_alarms_missed):
                callback(missed)
