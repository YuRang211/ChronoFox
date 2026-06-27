from __future__ import annotations

import time
from math import ceil


class ClockTimerMixin:
    """Stopwatch and timer behavior for the clock window."""

    def start_stopwatch(self) -> None:
        if self.stopwatch_running:
            return
        self.stopwatch_start_time = time.monotonic()
        self.stopwatch_running = True
        if hasattr(self, "stopwatch_start_button"):
            self.stopwatch_start_button.setText(self.tr("clock.action.stop", "중지"))

    def toggle_stopwatch(self) -> None:
        if self.stopwatch_running:
            self.pause_stopwatch()
            return
        self.start_stopwatch()

    def pause_stopwatch(self) -> None:
        if self.stopwatch_running:
            self.stopwatch_elapsed_before_pause = self.current_stopwatch_elapsed()
            self.stopwatch_start_time = None
        self.stopwatch_running = False
        if hasattr(self, "stopwatch_start_button"):
            self.stopwatch_start_button.setText(self.tr("clock.action.start", "시작"))

    def reset_stopwatch(self) -> None:
        self.stopwatch_running = False
        self.stopwatch_start_time = None
        self.stopwatch_elapsed_before_pause = 0.0
        self.stopwatch_label.setText(self.format_stopwatch(0.0))
        if hasattr(self, "stopwatch_start_button"):
            self.stopwatch_start_button.setText(self.tr("clock.action.start", "시작"))

    def start_timer(self) -> None:
        if self.timer_running:
            return
        if self.timer_remaining_before_pause_ms > 0:
            self.timer_total_duration = self.timer_remaining_before_pause_ms
        else:
            self.timer_total_duration = self.timer_input_milliseconds()
        self.timer_remaining_ms = int(round(self.timer_total_duration))
        self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))
        self.timer_running = self.timer_total_duration > 0
        self.timer_start_time = time.monotonic() if self.timer_running else None
        self.timer_remaining_before_pause_ms = 0

    def pause_timer(self) -> None:
        if self.timer_running:
            self.timer_remaining_before_pause_ms = self.current_timer_remaining_ms()
            self.timer_start_time = None
        self.timer_running = False

    def reset_timer(self) -> None:
        self.timer_running = False
        self.timer_start_time = None
        self.timer_total_duration = 0.0
        self.timer_remaining_before_pause_ms = 0
        self.timer_remaining_ms = self.timer_input_milliseconds()
        self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def refresh_timer_from_inputs(self) -> None:
        if self.timer_running or self.timer_remaining_before_pause_ms > 0:
            return
        self.timer_remaining_ms = self.timer_input_milliseconds()
        self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def current_stopwatch_elapsed(self) -> float:
        elapsed = self.stopwatch_elapsed_before_pause
        if self.stopwatch_running and self.stopwatch_start_time is not None:
            elapsed += time.monotonic() - self.stopwatch_start_time
        return elapsed

    def current_timer_remaining_ms(self) -> int:
        if not self.timer_running or self.timer_start_time is None:
            return max(0, int(self.timer_remaining_before_pause_ms or self.timer_remaining_ms))
        elapsed_ms = int((time.monotonic() - self.timer_start_time) * 1000)
        return max(0, int(ceil(self.timer_total_duration - elapsed_ms)))

    def timer_input_milliseconds(self) -> int:
        return (
            self.timer_hours.value() * 3_600_000
            + self.timer_minutes.value() * 60_000
            + self.timer_seconds.value() * 1000
        )

    def format_milliseconds(self, total_ms: int) -> str:
        total_ms = max(0, int(total_ms))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) // 1000
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def format_stopwatch(self, elapsed: float) -> str:
        total_ms = max(0, int(elapsed * 1000))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) // 1000
        millis = total_ms % 1000
        if hours:
            return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"
        return f"{minutes:02}:{seconds:02}.{millis:03}"
