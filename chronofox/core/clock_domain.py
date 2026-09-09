"""알람 CRUD와 타이머·스톱워치 상태 전이를 담당하는 Qt-free 순수 로직 모음.

`planning/QA.md` B1 / `planning/PROJECT.md` §8 P1-3 구현. Quick Input이 저장을 위해 화면에
띄우지 않는 숨김 `ClockWindow`를 만드는 우회(`_headless_clock_window`)를 없애기 위해,
`chronofox/clock/alarms.py`(`ClockAlarmMixin`)와 `chronofox/clock/timer.py`
(`ClockTimerMixin`)에 있던 데이터 조작 로직 중 UI(위젯 갱신·`self.app.save()`·
`store.notify()`·`self.tr()`)와 무관한 부분만 이 모듈로 옮긴다.

Qt import는 core 계층 규약상 절대 금지다(`task_logic.py` 선례). 현재 시각/모노토닉 시각은
항상 인자로만 받는다 — 결정적 함수로 유지해 테스트 가능성을 보장한다(알람=wall clock,
타이머·스톱워치=monotonic, `planning/PROJECT.md` §6 알림 계약과 동일한 구분을 그대로 따른다).

공개 API:
- 알람: `normalize_alarm`, `normalized_alert_sound_mode`, `alarm_label_text`, `find_alarm`,
  `save_alarm_payload`, `set_alarm_enabled`, `delete_alarm`, `next_alarm_occurrence`,
  `snooze_due`, `mark_alarm_triggered`, `resolve_alarm_alert`
- 타이머: `TimerState`, `start_timer`, `pause_timer`, `reset_timer`, `current_timer_remaining_ms`
- 스톱워치: `StopwatchState`, `start_stopwatch`, `pause_stopwatch`, `reset_stopwatch`,
  `current_stopwatch_elapsed`
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import ceil

from chronofox.core.alarm_validation import parse_alarm_time

__all__ = [
    "DEFAULT_REPEAT_DAYS",
    "normalized_alert_sound_mode",
    "normalize_alarm",
    "alarm_label_text",
    "find_alarm",
    "save_alarm_payload",
    "set_alarm_enabled",
    "delete_alarm",
    "next_alarm_occurrence",
    "snooze_due",
    "mark_alarm_triggered",
    "resolve_alarm_alert",
    "TimerState",
    "start_timer",
    "pause_timer",
    "reset_timer",
    "current_timer_remaining_ms",
    "StopwatchState",
    "start_stopwatch",
    "pause_stopwatch",
    "reset_stopwatch",
    "current_stopwatch_elapsed",
]

DEFAULT_REPEAT_DAYS = [0, 1, 2, 3, 4, 5, 6]

# `normalize_alarm`이 채우는 라벨 기본값의 원문 상수. `alarm_label_text`가 "사용자가 라벨을
# 지우지 않았는지"를 판정할 때 언어와 무관하게 이 리터럴과 비교한다(기존 ClockAlarmMixin과
# 동일한 동작 — 저장된 라벨 자체는 항상 이 한국어 문자열이 기본값이라 언어 설정과 무관하다).
_DEFAULT_ALARM_LABEL_RAW = "알람"


# ---------------------------------------------------------------------------
# 알람 CRUD (§4 스타일 — additive setdefault, in-place + 반환)
# ---------------------------------------------------------------------------


def normalized_alert_sound_mode(mode: str) -> str:
    """알림음 모드 값을 지원하는 값(default/local/url)으로 정규화합니다."""
    if mode == "youtube":
        return "url"
    return mode if mode in {"default", "local", "url"} else "default"


def normalize_alarm(
    alarm: dict,
    *,
    default_sound_mode: str = "default",
    default_sound_path: str = "",
    default_sound_url: str = "",
    now: datetime | None = None,
) -> dict:
    """알람 dict에 누락된 기본 필드를 채웁니다. in-place로 수정하고 같은 dict를 반환합니다."""
    now = now or datetime.now()
    alarm.setdefault("id", now.strftime("%Y%m%d%H%M%S%f"))
    alarm.setdefault("time", "07:00")
    alarm.setdefault("label", _DEFAULT_ALARM_LABEL_RAW)
    alarm.setdefault("enabled", True)
    alarm.setdefault("last_triggered", "")
    alarm.setdefault("kind", "repeat")
    alarm.setdefault("date", "")
    alarm.setdefault("notify_mode", "popup")
    alarm.setdefault("repeat_days", list(DEFAULT_REPEAT_DAYS))
    alarm.setdefault("snooze_minutes", 5)
    alarm.setdefault("snoozed_until", "")
    alarm.setdefault("sound_mode", normalized_alert_sound_mode(default_sound_mode))
    alarm.setdefault("sound_path", default_sound_path)
    alarm.setdefault("sound_url", default_sound_url)
    return alarm


def alarm_label_text(alarm: dict, fallback: str) -> str:
    """알람 목록에 표시할 라벨 문자열을 만듭니다.

    라벨이 비어 있거나 `normalize_alarm`이 채운 기본값 그대로면(언어 무관, 원문 비교)
    `fallback`(호출부가 번역해서 넘긴 문자열)을 돌려줍니다.
    """
    label = str(alarm.get("label", "")).strip()
    if not label or label == _DEFAULT_ALARM_LABEL_RAW:
        return fallback
    return label


def find_alarm(alarms: list[dict], alarm_id: str) -> dict | None:
    """id로 알람을 찾아 반환합니다."""
    for alarm in alarms:
        if str(alarm.get("id")) == alarm_id:
            return alarm
    return None


def save_alarm_payload(
    alarms: list[dict],
    payload: dict,
    alarm_id: str = "",
    *,
    now: datetime | None = None,
) -> dict | None:
    """알람 편집기(또는 Quick Input) 입력값을 저장합니다.

    `alarm_id`가 주어지고 해당 알람을 찾으면 `enabled`를 보존한 채 갱신합니다. 주어졌는데
    찾지 못하면 아무 것도 하지 않고 `None`을 반환합니다(기존 편집기 동작과 동일). `alarm_id`가
    없으면 새 알람을 만들어 `alarms`에 append합니다. 두 경우 모두 저장된 알람 dict를
    반환합니다(호출부가 store.notify/refresh 같은 UI 갱신을 잇기 위함).
    """
    if alarm_id:
        alarm = find_alarm(alarms, alarm_id)
        if alarm is None:
            return None
        enabled = bool(alarm.get("enabled", True))
        alarm.update(payload)
        alarm["enabled"] = enabled
        return alarm
    now = now or datetime.now()
    alarm = {"id": now.strftime("%Y%m%d%H%M%S%f"), **payload}
    alarms.append(alarm)
    return alarm


def set_alarm_enabled(alarms: list[dict], alarm_id: str, enabled: bool) -> dict | None:
    """알람 켜짐/꺼짐 상태를 바꿉니다. 꺼지면 스누즈를, 켜지면 마지막 발화 기록을 지웁니다."""
    for alarm in alarms:
        if str(alarm.get("id")) == alarm_id:
            alarm["enabled"] = enabled
            if enabled:
                alarm["last_triggered"] = ""
            else:
                alarm["snoozed_until"] = ""
            return alarm
    return None


def delete_alarm(alarms: list[dict], alarm_id: str) -> None:
    """알람을 삭제합니다. `alarms`가 store가 들고 있는 live 리스트라는 전제로 in-place
    슬라이스 대입을 씁니다(참조를 바꾸지 않아 호출부 재할당이 필요 없습니다)."""
    alarms[:] = [alarm for alarm in alarms if str(alarm.get("id")) != alarm_id]


def next_alarm_occurrence(alarms: list[dict], now: datetime) -> datetime | None:
    """켜져 있는 알람들 중 앞으로 7일 안에 가장 먼저 울릴 시각을 돌려줍니다."""
    best: datetime | None = None
    for alarm in alarms:
        if not alarm.get("enabled", True):
            continue
        parsed_time = parse_alarm_time(alarm.get("time"))
        if parsed_time is None:
            continue
        hour, minute = parsed_time
        if alarm.get("kind") == "date":
            try:
                day = date.fromisoformat(str(alarm.get("date", "")))
            except ValueError:
                continue
            candidate = datetime(day.year, day.month, day.day, hour, minute)
            if candidate > now and (best is None or candidate < best):
                best = candidate
            continue
        repeat_days = alarm.get("repeat_days", DEFAULT_REPEAT_DAYS)
        for offset in range(8):
            day = now.date() + timedelta(days=offset)
            if day.weekday() not in repeat_days:
                continue
            candidate = datetime(day.year, day.month, day.day, hour, minute)
            if candidate <= now:
                continue
            if best is None or candidate < best:
                best = candidate
            break
    return best


def snooze_due(alarm: dict, now: datetime) -> bool:
    """다시 울림(스누즈)이 도래한 알람을 확인합니다. 저장된 값이 깨져 있으면 지우고 False."""
    value = str(alarm.get("snoozed_until", ""))
    if not value:
        return False
    try:
        snoozed_until = datetime.fromisoformat(value)
    except ValueError:
        alarm["snoozed_until"] = ""
        return False
    if snoozed_until.tzinfo is None and now.tzinfo is not None:
        now = now.astimezone().replace(tzinfo=None)
    elif snoozed_until.tzinfo is not None and now.tzinfo is None:
        snoozed_until = snoozed_until.astimezone().replace(tzinfo=None)
    return now >= snoozed_until


def mark_alarm_triggered(alarm: dict, now: datetime) -> None:
    """알람이 발화했음을 기록합니다(오늘 날짜로 `last_triggered` 갱신)."""
    alarm["last_triggered"] = now.date().isoformat()


def resolve_alarm_alert(alarm: dict, action: str, now: datetime) -> None:
    """알림 팝업 결과(`"snooze"`/`"stop"`)를 알람에 반영합니다.

    스누즈면 `snoozed_until`을 `now + snooze_minutes`로 설정합니다. 정지면 스누즈를 지우고,
    date-kind 알람이면 다시 울리지 않도록 비활성화합니다(1회성 알람 관례).
    """
    if action == "snooze":
        minutes = max(1, int(alarm.get("snooze_minutes", 5)))
        alarm["snoozed_until"] = (now + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    else:
        alarm["snoozed_until"] = ""
        if alarm.get("kind") == "date":
            alarm["enabled"] = False


# ---------------------------------------------------------------------------
# 타이머 상태 전이 (monotonic — 알람과 절대 섞지 않는다, §6 알림 계약)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimerState:
    """타이머의 현재 상태. 불변 dataclass — 전이 함수는 항상 새 인스턴스를 돌려줍니다."""

    running: bool = False
    start_time: float | None = None
    total_duration_ms: float = 0.0
    remaining_before_pause_ms: int = 0
    remaining_ms: int = 0


def current_timer_remaining_ms(state: TimerState, now_monotonic: float) -> int:
    """현재 타이머 남은 시간(ms)을 계산합니다. 실행 중이 아니면 일시정지 시점 값을 그대로."""
    if not state.running or state.start_time is None:
        return max(0, int(state.remaining_before_pause_ms or state.remaining_ms))
    elapsed_ms = int((now_monotonic - state.start_time) * 1000)
    return max(0, int(ceil(state.total_duration_ms - elapsed_ms)))


def start_timer(state: TimerState, requested_ms: int, now_monotonic: float) -> TimerState:
    """타이머를 시작합니다. 이미 실행 중이면 상태를 그대로 돌려줍니다(중복 시작 무시).

    일시정지 후 재개(`remaining_before_pause_ms > 0`)면 그 값을 이어서 쓰고, 처음 시작이면
    `requested_ms`(위젯 입력값 또는 호출부가 계산한 길이)를 씁니다.
    """
    if state.running:
        return state
    total = state.remaining_before_pause_ms if state.remaining_before_pause_ms > 0 else requested_ms
    remaining = int(round(total))
    running = total > 0
    return TimerState(
        running=running,
        start_time=now_monotonic if running else None,
        total_duration_ms=total,
        remaining_before_pause_ms=0,
        remaining_ms=remaining,
    )


def pause_timer(state: TimerState, now_monotonic: float) -> TimerState:
    """타이머를 일시정지합니다. 실행 중이 아니면 상태를 그대로 돌려줍니다."""
    if not state.running:
        return state
    remaining = current_timer_remaining_ms(state, now_monotonic)
    return replace(state, running=False, start_time=None, remaining_before_pause_ms=remaining)


def reset_timer(requested_ms: int) -> TimerState:
    """타이머를 입력값 기준으로 초기화합니다."""
    return TimerState(remaining_ms=requested_ms)


# ---------------------------------------------------------------------------
# 스톱워치 상태 전이 (monotonic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StopwatchState:
    """스톱워치의 현재 상태. 불변 dataclass — 전이 함수는 항상 새 인스턴스를 돌려줍니다."""

    running: bool = False
    start_time: float | None = None
    elapsed_before_pause: float = 0.0


def current_stopwatch_elapsed(state: StopwatchState, now_monotonic: float) -> float:
    """현재 스톱워치 경과 시간(초)을 계산합니다."""
    elapsed = state.elapsed_before_pause
    if state.running and state.start_time is not None:
        elapsed += now_monotonic - state.start_time
    return elapsed


def start_stopwatch(state: StopwatchState, now_monotonic: float) -> StopwatchState:
    """스톱워치를 시작합니다. 이미 실행 중이면 상태를 그대로 돌려줍니다."""
    if state.running:
        return state
    return StopwatchState(running=True, start_time=now_monotonic, elapsed_before_pause=state.elapsed_before_pause)


def pause_stopwatch(state: StopwatchState, now_monotonic: float) -> StopwatchState:
    """스톱워치를 일시정지합니다. 실행 중이 아니면 상태를 그대로 돌려줍니다."""
    if not state.running:
        return state
    elapsed = current_stopwatch_elapsed(state, now_monotonic)
    return StopwatchState(running=False, start_time=None, elapsed_before_pause=elapsed)


def reset_stopwatch() -> StopwatchState:
    """스톱워치를 0으로 초기화합니다."""
    return StopwatchState()
