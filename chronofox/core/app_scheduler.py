"""F2: 알람 · 리마인더 · 날짜 롤오버를 단일 1초 tick으로 구동하는 스케줄러.

설계 근거: planning/specs/notification-engine.md (D1~D12, 시나리오 S1~S12).
코어(NotificationScheduler, due_occurrence_today)는 Qt에 의존하지 않는다 — 시간 주입
(``now_fn``)만으로 테스트 가능해야 한다(D12). Qt 타이머 연결은 이 모듈을 사용하는
쪽(FoxCalendarApp)에서 얇은 어댑터로 감싼다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta

from chronofox.core.alarm_validation import parse_alarm_time

_log = logging.getLogger(__name__)


def due_occurrence_on(alarm: dict, day: date) -> datetime | None:
    """``day``에 이 알람이 울려야 할 HH:MM 시각을 돌려준다(발화 대상일이 아니면 None)."""
    parsed_time = parse_alarm_time(alarm.get("time"))
    if parsed_time is None:
        return None
    hour, minute = parsed_time
    if alarm.get("kind") == "date":
        try:
            alarm_day = date.fromisoformat(str(alarm.get("date", "")))
        except ValueError:
            return None
        if alarm_day != day:
            return None
    else:
        repeat_days = alarm.get("repeat_days", [0, 1, 2, 3, 4, 5, 6])
        if day.weekday() not in repeat_days:
            return None
    return datetime(day.year, day.month, day.day, hour, minute)


def due_occurrence_today(alarm: dict, now: datetime) -> datetime | None:
    """오늘(now 날짜 기준) 이 알람이 울려야 할 HH:MM 시각을 돌려준다.

    ``clock/alarms.py``의 ``next_alarm_occurrence``(미래 방향 탐색)의 역방향 버전이다:
    "오늘이 발화 대상일인가"만 판정하고, 아니면 None을 돌려준다.
    """
    return due_occurrence_on(alarm, now.date())


def handled_marker_for_activation(alarm: dict, now: datetime) -> str:
    """새로 켜거나 일정을 바꾼 알람이 이미 지난 회차를 다시 울리지 않도록 표시값을 정한다.

    오늘(날짜 지정 알람은 그 날짜) 회차가 지났으면 그 날짜(처리됨), 아니면 빈 값을 돌려준다.
    절전·재시작 catch-up은 이 표시를 거치지 않으므로 그대로 유지된다.
    """
    day = now.date()
    if alarm.get("kind") == "date":
        try:
            day = date.fromisoformat(str(alarm.get("date", "")))
        except ValueError:
            return ""
    due = due_occurrence_on(alarm, day)
    if due is not None and due <= now:
        return day.isoformat()
    return ""


def _snooze_due(alarm: dict, now: datetime) -> bool:
    """스누즈 시각이 지났는지 판정합니다. catch-up 창은 적용하지 않습니다."""
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
        """1초마다 호출되어 알람 발화, 리마인더 스캔, 날짜 롤오버를 확인합니다."""
        now = self.now_fn()

        self.last_jump = self.last_tick is not None and (now - self.last_tick) > self.JUMP_THRESHOLD
        day_rolled = self.last_tick is not None and now.date() != self.last_tick.date()

        self._scan_alarms(now)

        self.tick_count += 1
        if self.tick_count % self.REMINDER_SCAN_INTERVAL == 0:
            self._dispatch(self.on_reminder_scan)

        if day_rolled:
            self._dispatch(self.on_day_changed)

        self.last_tick = now

    @staticmethod
    def _dispatch(callbacks: list[Callable], *args) -> bool:
        """콜백 하나의 예외가 같은 tick의 다른 알림·롤오버를 막지 않도록 격리한다. 모두 성공하면 True."""
        ok = True
        for callback in list(callbacks):
            try:
                callback(*args)
            except Exception:
                ok = False
                _log.exception("notification callback failed")
        return ok

    def _fire(self, alarm: dict, missed: list[dict]) -> None:
        # 발화 표시를 먼저 했으므로 표시에 실패한 알람은 요약으로라도 알린다.
        if not self._dispatch(self.on_alarm_due, alarm):
            missed.append(alarm)

    def _handle_due(self, alarm: dict, due: datetime, now: datetime, missed: list[dict]) -> None:
        alarm["last_triggered"] = due.date().isoformat()
        if now < due + self.CATCHUP_WINDOW:
            # 폴링 시각의 정확한 일치가 아니라 기한 경과로 판정한다.
            self._fire(alarm, missed)
        else:
            # catch-up 창을 넘긴 알람은 모달 대신 요약 알림으로 보낸다.
            missed.append(alarm)

    def _scan_alarms(self, now: datetime) -> None:
        today_date = now.date()
        today = today_date.isoformat()
        yesterday = today_date - timedelta(days=1)
        # 실행 중 자정을 넘긴 경우(절전 포함)에만 어제 회차를 본다. 앱이 꺼져 있던
        # 지난날의 반복 알람까지 시작 때 몰아서 알리지 않기 위함이다.
        crossed_midnight = self.last_tick is not None and self.last_tick.date() < today_date
        missed: list[dict] = []
        for alarm in self.alarms_fn():
            if not alarm.get("enabled", True):
                continue
            if parse_alarm_time(alarm.get("time")) is None:
                continue

            if _snooze_due(alarm, now):
                # 스누즈 시각은 사용자가 새로 정한 기한이므로 catch-up 창과 무관하게 발화한다.
                alarm["snoozed_until"] = ""
                alarm["last_triggered"] = today
                self._fire(alarm, missed)
                continue

            if alarm.get("kind") == "date":
                self._scan_date_alarm(alarm, now, missed)
                continue

            if crossed_midnight and alarm.get("last_triggered") not in (yesterday.isoformat(), today):
                due_yesterday = due_occurrence_on(alarm, yesterday)
                if due_yesterday is not None and self.last_tick < due_yesterday <= now:
                    self._handle_due(alarm, due_yesterday, now, missed)

            if alarm.get("last_triggered") == today:
                continue  # 같은 날 이미 발화하거나 요약한 반복 알람

            due = due_occurrence_on(alarm, today_date)
            if due is None or due > now:
                continue
            self._handle_due(alarm, due, now, missed)

        if missed:
            self._dispatch(self.on_alarms_missed, missed)

    def _scan_date_alarm(self, alarm: dict, now: datetime, missed: list[dict]) -> None:
        """날짜 지정 알람은 한 번뿐이므로 그날이 지나도록 놓쳤으면 다음 기회에 요약한다."""
        try:
            day = date.fromisoformat(str(alarm.get("date", "")))
        except ValueError:
            return
        if alarm.get("last_triggered") == day.isoformat():
            return
        due = due_occurrence_on(alarm, day)
        if due is None or due > now:
            return
        self._handle_due(alarm, due, now, missed)
