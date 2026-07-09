from __future__ import annotations

import time

import pytest

from desktop_note_calendar import FoxCalendarApp

pytestmark = pytest.mark.slow  # F4 D3: 실제 FoxCalendarApp() 풀 생성 — fast lane 제외


def test_app_has_background_timer_and_states(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    # 1. Verify the notification scheduler (F2: single 1s tick) is active and variables exist
    assert hasattr(app, "scheduler")
    assert hasattr(app, "scheduler_timer")
    assert app.scheduler_timer.isActive()
    assert not app.stopwatch_running
    assert not app.timer_running


def test_background_stopwatch_behavior(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    # Initially not running and elapsed is 0
    assert app.current_stopwatch_elapsed() == 0.0
    assert app.format_stopwatch_tray(0.0) == "00:00"

    # Start stopwatch (via mixin/properties on window, or directly on app)
    app.stopwatch_start_time = time.monotonic() - 5.5  # Simulate 5.5 seconds elapsed
    app.stopwatch_running = True

    assert app.current_stopwatch_elapsed() >= 5.5
    tray_text = app.format_stopwatch_tray(app.current_stopwatch_elapsed())
    assert tray_text == "00:05" or tray_text == "00:06"


def test_background_timer_expiration(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    # Configure alarm sound mode to default to avoid player initialization
    app.config["alert_sound_mode"] = "default"

    # Mock show_alert to avoid showing blocking modal dialog in test
    alert_called = []
    app.show_alert = lambda msg: alert_called.append(msg)

    # Start timer for 100 milliseconds
    app.timer_total_duration = 100.0
    app.timer_remaining_ms = 100
    app.timer_start_time = time.monotonic()
    app.timer_running = True

    # Initially running and remaining > 0
    assert app.current_timer_remaining_ms() > 0

    # Wait for timer to expire in monotonic time
    app.timer_start_time = time.monotonic() - 0.2  # Simulate 200ms elapsed
    app.check_background_timer()

    assert not app.timer_running
    assert app.timer_remaining_ms == 0
    assert len(alert_called) == 1
    assert "finished" in alert_called[0] or "끝났습니다" in alert_called[0]


def test_tray_menu_dynamic_rebuilding(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)
    app.config["language"] = "en"
    app.data["alarms"] = []  # Clear user-specific alarms to ensure consistent output

    # Set background states to verify tray text formatting
    app.stopwatch_running = True
    app.stopwatch_start_time = time.monotonic() - 10.0  # 10s elapsed
    app.timer_running = True
    app.timer_total_duration = 5000.0
    app.timer_start_time = time.monotonic() - 2.0  # 3s remaining

    app.update_tray_menu()

    actions = app.tray_menu.actions()
    action_texts = [action.text() for action in actions]
    print("ACTION TEXTS:", action_texts)

    # No upcoming alarm exists, so the alarm status entry must be hidden entirely
    assert not any("Alarm" in text for text in action_texts)
    # Running timer/stopwatch status entries are present with correct text
    assert any("Timer" in text and "00:03" in text or "Timer" in text and "00:02" in text for text in action_texts)
    assert any("Stopwatch" in text and "00:10" in text for text in action_texts)
    assert any("Open ChronoFox" in text for text in action_texts)


def test_tray_menu_hides_idle_status_items(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)
    app.config["language"] = "en"
    app.data["alarms"] = []  # No alarms -> next_alarm_occurrence() is None

    # Nothing active: no alarm, timer stopped, stopwatch stopped
    app.stopwatch_running = False
    app.timer_running = False

    app.update_tray_menu()

    actions = app.tray_menu.actions()
    action_texts = [action.text() for action in actions]
    print("ACTION TEXTS (idle):", action_texts)

    # No status entries should be present when everything is idle
    assert not any("Alarm" in text for text in action_texts)
    assert not any("Timer" in text for text in action_texts)
    assert not any("Stopwatch" in text for text in action_texts)

    # The menu should open directly with "Open ChronoFox" and no leading separator
    assert action_texts[0] == "Open ChronoFox"
    assert not actions[0].isSeparator()


def test_tray_menu_shows_running_stopwatch_only(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)
    app.config["language"] = "en"
    app.data["alarms"] = []  # No alarms -> alarm status stays hidden

    # Only the stopwatch is active; timer stays idle/hidden
    app.stopwatch_running = True
    app.stopwatch_start_time = time.monotonic() - 3.0  # 3s elapsed
    app.timer_running = False

    app.update_tray_menu()

    actions = app.tray_menu.actions()
    action_texts = [action.text() for action in actions]
    print("ACTION TEXTS (stopwatch only):", action_texts)

    assert not any("Alarm" in text for text in action_texts)
    assert not any("Timer" in text for text in action_texts)
    assert any("Stopwatch" in text and "00:03" in text for text in action_texts)
    assert any("Open ChronoFox" in text for text in action_texts)


def test_open_clock_tab_navigation(qtbot, app_paths) -> None:
    app = FoxCalendarApp()
    qtbot.addWidget(app)

    # Ensure clock window is initially closed
    assert app.clock_window is None

    # Open clock window and go to tab 2 (Timer)
    app.open_clock_tab(2)
    assert app.clock_window is not None
    qtbot.addWidget(app.clock_window)

    assert app.clock_window.isVisible()
    assert app.clock_window.content_stack.currentIndex() == 2
