from __future__ import annotations

import os
from datetime import date, datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app_scheduler import NotificationScheduler, due_occurrence_today
from desktop_note_calendar import FoxCalendarApp


def make_alarm(
    alarm_id: str,
    time_: str = "07:00",
    kind: str = "repeat",
    repeat_days: list[int] | None = None,
    date_: str = "",
    last_triggered: str = "",
    enabled: bool = True,
    snoozed_until: str = "",
    label: str = "Test",
) -> dict:
    return {
        "id": alarm_id,
        "time": time_,
        "label": label,
        "enabled": enabled,
        "last_triggered": last_triggered,
        "kind": kind,
        "date": date_,
        "notify_mode": "popup",
        "repeat_days": repeat_days if repeat_days is not None else [0, 1, 2, 3, 4, 5, 6],
        "snooze_minutes": 5,
        "snoozed_until": snoozed_until,
    }


# ---------------------------------------------------------------------------
# 코어 순수 로직 테스트 (Qt 비의존, now_fn 주입) — 구현 순서 1단계
# ---------------------------------------------------------------------------


def test_due_occurrence_today_repeat_and_date_kind() -> None:
    now = datetime(2026, 7, 8, 7, 0, 0)  # 2026-07-08 = Wednesday(weekday=2)
    repeat_alarm = make_alarm("r1", time_="07:30", repeat_days=[2])
    assert due_occurrence_today(repeat_alarm, now) == datetime(2026, 7, 8, 7, 30)

    not_today = make_alarm("r2", time_="07:30", repeat_days=[0])  # Monday only
    assert due_occurrence_today(not_today, now) is None

    date_alarm = make_alarm("d1", time_="08:00", kind="date", date_="2026-07-08")
    assert due_occurrence_today(date_alarm, now) == datetime(2026, 7, 8, 8, 0)

    other_day = make_alarm("d2", time_="08:00", kind="date", date_="2026-07-09")
    assert due_occurrence_today(other_day, now) is None


def test_t1_on_time_fire_and_no_refire_same_tick() -> None:
    """T1 (S1): 정각 발화 + 같은 분 재발화 없음."""
    now = datetime(2026, 7, 8, 7, 0, 0)
    alarm = make_alarm("a1", time_="07:00")
    fired: list[str] = []
    scheduler = NotificationScheduler(now_fn=lambda: now, alarms_fn=lambda: [alarm])
    scheduler.on_alarm_due.append(lambda a: fired.append(a["id"]))

    scheduler.tick()
    assert fired == ["a1"]
    assert alarm["last_triggered"] == now.date().isoformat()

    scheduler.tick()  # 같은 now로 다시 tick — 재발화 없음
    assert fired == ["a1"]


def test_t2_catchup_jump_within_window_fires() -> None:
    """T2 (S2/S3/S6): 폴링 누락·절전 복귀·재시작 후 due+7분 시점의 첫 tick에서 발화."""
    due = datetime(2026, 7, 8, 7, 0, 0)
    jumped_now = due + timedelta(minutes=7)
    alarm = make_alarm("a2", time_="07:00")
    fired: list[str] = []
    scheduler = NotificationScheduler(now_fn=lambda: jumped_now, alarms_fn=lambda: [alarm])
    scheduler.on_alarm_due.append(lambda a: fired.append(a["id"]))

    scheduler.tick()

    assert fired == ["a2"]
    assert alarm["last_triggered"] == jumped_now.date().isoformat()


def test_t3_missed_beyond_catchup_window_summarized_not_fired() -> None:
    """T3 (S4): 10분 창을 넘겨 발견되면 on_alarms_missed 1회, on_alarm_due 미호출, last_triggered 마킹."""
    due = datetime(2026, 7, 8, 7, 0, 0)
    late_now = due + timedelta(hours=3)
    alarm = make_alarm("a3", time_="07:00")
    fired: list[str] = []
    missed_batches: list[list[str]] = []
    scheduler = NotificationScheduler(now_fn=lambda: late_now, alarms_fn=lambda: [alarm])
    scheduler.on_alarm_due.append(lambda a: fired.append(a["id"]))
    scheduler.on_alarms_missed.append(lambda alarms: missed_batches.append([a["id"] for a in alarms]))

    scheduler.tick()

    assert fired == []
    assert missed_batches == [["a3"]]
    assert alarm["last_triggered"] == late_now.date().isoformat()

    # 같은 날 다시 tick해도 재요약하지 않는다 (dedupe).
    scheduler.tick()
    assert missed_batches == [["a3"]]


def test_t5_snooze_fires_immediately_ignoring_catchup_window() -> None:
    """T5 (S7): 스누즈는 절전으로 늦어져도(점프 포함) 창 제한 없이 즉시 발화."""
    now = datetime(2026, 7, 8, 10, 0, 0)
    alarm = make_alarm("a4", time_="07:00", last_triggered=now.date().isoformat())
    alarm["snoozed_until"] = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    fired: list[str] = []
    scheduler = NotificationScheduler(now_fn=lambda: now, alarms_fn=lambda: [alarm])
    scheduler.on_alarm_due.append(lambda a: fired.append(a["id"]))

    scheduler.tick()

    assert fired == ["a4"]
    assert alarm["snoozed_until"] == ""


def test_t7_reminder_scan_only_at_30s_boundary() -> None:
    """T7 (S10 회귀 전제): tick_count % 30 == 0 에서만 on_reminder_scan 호출."""
    now = datetime(2026, 7, 8, 10, 0, 0)
    calls: list[int] = []
    scheduler = NotificationScheduler(now_fn=lambda: now, alarms_fn=lambda: [])
    scheduler.on_reminder_scan.append(lambda: calls.append(1))

    for _ in range(29):
        scheduler.tick()
    assert calls == []

    scheduler.tick()  # 30번째 tick
    assert len(calls) == 1

    for _ in range(29):
        scheduler.tick()
    assert len(calls) == 1

    scheduler.tick()  # 60번째 tick
    assert len(calls) == 2


def test_t8_day_changed_fires_once_on_midnight_rollover() -> None:
    """T8 (S12): 자정 경과 tick에서 on_day_changed가 정확히 1회 호출된다."""
    box = {"now": datetime(2026, 7, 8, 23, 59, 59)}
    calls: list[int] = []
    scheduler = NotificationScheduler(now_fn=lambda: box["now"], alarms_fn=lambda: [])
    scheduler.on_day_changed.append(lambda: calls.append(1))

    scheduler.tick()  # 기준 tick (전날) — last_tick만 설정됨
    assert calls == []

    box["now"] = datetime(2026, 7, 9, 0, 0, 0)
    scheduler.tick()
    assert calls == [1]

    box["now"] = datetime(2026, 7, 9, 0, 0, 1)
    scheduler.tick()  # 같은 날 다시 tick — 재호출 없음
    assert calls == [1]


def test_t9_jump_detection_boundary() -> None:
    """T9 (D5): 89초 차이는 무시, 91초 차이는 감지."""
    box = {"now": datetime(2026, 7, 8, 10, 0, 0)}
    scheduler = NotificationScheduler(now_fn=lambda: box["now"], alarms_fn=lambda: [])

    scheduler.tick()
    assert scheduler.last_jump is False

    box["now"] += timedelta(seconds=89)
    scheduler.tick()
    assert scheduler.last_jump is False

    box["now"] += timedelta(seconds=91)
    scheduler.tick()
    assert scheduler.last_jump is True


# ---------------------------------------------------------------------------
# 호스트 통합 테스트 (FoxCalendarApp + scheduler 배선) — 구현 순서 2단계
# ---------------------------------------------------------------------------


def test_t4_same_minute_two_alarms_queue_and_serialize(qtbot) -> None:
    """T4 (S5): 같은 분 알람 2개 → 큐 2건, _alert_active 가드로 동시 표시는 항상 1개."""
    app = FoxCalendarApp()
    qtbot.addWidget(app)
    app.save = lambda: None  # 테스트 알람이 실제 사용자 데이터에 저장되지 않도록 차단

    now = datetime.now().replace(second=0, microsecond=0)
    stamp = f"{now:%H:%M}"
    alarm1 = make_alarm("q1", time_=stamp, label="First")
    alarm2 = make_alarm("q2", time_=stamp, label="Second")
    app.data["alarms"] = [alarm1, alarm2]

    order: list[str] = []
    active = {"n": 0, "max": 0}

    def fake_trigger_alarm(alarm: dict, message: str) -> None:
        active["n"] += 1
        active["max"] = max(active["max"], active["n"])
        order.append(alarm["id"])
        # 실제로는 QMessageBox.exec()가 이벤트 루프를 돌리는 동안 scheduler_timer가
        # 다시 발화할 수 있다 — 그 재진입 상황을 흉내낸다.
        app.scheduler.tick()
        active["n"] -= 1

    app.trigger_alarm = fake_trigger_alarm
    app.scheduler.now_fn = lambda: now

    app.scheduler.tick()

    assert order == ["q1", "q2"]
    assert active["max"] == 1


def test_t6_date_kind_alarm_disables_after_stop(qtbot) -> None:
    """T6 (S8): date-kind 알람은 발화(정지) 후 enabled=False."""
    app = FoxCalendarApp()
    qtbot.addWidget(app)
    app.save = lambda: None  # 테스트 알람이 실제 사용자 데이터에 저장되지 않도록 차단

    today = date.today()
    alarm = make_alarm("d1", time_="07:00", kind="date", date_=today.isoformat())
    app.data["alarms"] = [alarm]
    app.show_alert = lambda message, allow_snooze=True, notify_mode="popup": "stop"

    now = datetime(today.year, today.month, today.day, 7, 0, 0)
    app.scheduler.now_fn = lambda: now
    app.scheduler.tick()

    assert alarm["enabled"] is False
    assert alarm["last_triggered"] == today.isoformat()


def test_missed_alarm_summary_message_and_more_suffix(qtbot) -> None:
    """D3/i18n: 놓친 알람 요약 메시지는 3건까지 나열하고, 초과분은 '외 N건'/'+N more'."""
    app = FoxCalendarApp()
    qtbot.addWidget(app)
    app.config["language"] = "ko"

    alarms = [make_alarm(f"m{i}", time_=f"0{i}:00", label=f"L{i}") for i in range(1, 5)]
    message = app.format_missed_alarms_message(alarms)

    assert message.startswith("절전/종료 중 놓친 알람 4건:")
    assert "외 1건" in message

    app.config["language"] = "en"
    message_en = app.format_missed_alarms_message(alarms)
    assert message_en.startswith("Missed 4 alarm(s) while asleep/off:")
    assert "+1 more" in message_en


def test_scheduler_wired_on_app_init(qtbot) -> None:
    """desktop_note_calendar.FoxCalendarApp이 단일 스케줄러 + QTimer 어댑터로 배선되어 있다."""
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    assert hasattr(app, "scheduler")
    assert hasattr(app, "scheduler_timer")
    assert app.scheduler_timer.isActive()
    assert not hasattr(app, "alarm_timer")
    assert not hasattr(app, "reminder_timer")
