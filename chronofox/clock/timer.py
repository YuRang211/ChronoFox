"""ClockWindow의 스톱워치/타이머 시작·일시정지·리셋과 경과/남은 시간 계산을 담당하는 ClockTimerMixin.

상태 전이·남은 시간 계산 자체는 `chronofox.core.clock_domain`의 Qt-free 순수 함수
(`TimerState`/`StopwatchState` + `start_timer`/`pause_timer`/... )로 옮겨졌다. 이 믹스인은
위젯 상태(`self.timer_running` 등 — `ClockWindow`의 property가 `app` 전역 상태로 위임한다)를
`TimerState`/`StopwatchState`로 모았다 풀었다 하며 도메인 함수를 호출하고, 라벨/버튼 텍스트
갱신 같은 UI 반영만 담당한다."""

from __future__ import annotations

import time

from chronofox.core import clock_domain


class ClockTimerMixin:
    """Stopwatch and timer behavior for the clock window."""

    def _timer_state(self) -> clock_domain.TimerState:
        """위젯이 들고 있는(app 전역에 위임된) 개별 속성들을 TimerState로 모읍니다."""
        return clock_domain.TimerState(
            running=self.timer_running,
            start_time=self.timer_start_time,
            total_duration_ms=self.timer_total_duration,
            remaining_before_pause_ms=self.timer_remaining_before_pause_ms,
            remaining_ms=self.timer_remaining_ms,
        )

    def _apply_timer_state(self, state: clock_domain.TimerState) -> None:
        """TimerState를 다시 개별 속성(app 전역 상태)에 반영합니다."""
        self.timer_running = state.running
        self.timer_start_time = state.start_time
        self.timer_total_duration = state.total_duration_ms
        self.timer_remaining_before_pause_ms = state.remaining_before_pause_ms
        self.timer_remaining_ms = state.remaining_ms

    def _stopwatch_state(self) -> clock_domain.StopwatchState:
        """위젯이 들고 있는(app 전역에 위임된) 개별 속성들을 StopwatchState로 모읍니다."""
        return clock_domain.StopwatchState(
            running=self.stopwatch_running,
            start_time=self.stopwatch_start_time,
            elapsed_before_pause=self.stopwatch_elapsed_before_pause,
        )

    def _apply_stopwatch_state(self, state: clock_domain.StopwatchState) -> None:
        """StopwatchState를 다시 개별 속성(app 전역 상태)에 반영합니다."""
        self.stopwatch_running = state.running
        self.stopwatch_start_time = state.start_time
        self.stopwatch_elapsed_before_pause = state.elapsed_before_pause

    def start_stopwatch(self) -> None:
        """스톱워치를 시작합니다."""
        if self.stopwatch_running:
            return
        self._apply_stopwatch_state(clock_domain.start_stopwatch(self._stopwatch_state(), time.monotonic()))
        if hasattr(self, "stopwatch_start_button"):
            self.stopwatch_start_button.setText(self.tr("clock.action.stop", "중지"))

    def toggle_stopwatch(self) -> None:
        """스톱워치를 시작/일시정지로 전환합니다."""
        if self.stopwatch_running:
            self.pause_stopwatch()
            return
        self.start_stopwatch()

    def pause_stopwatch(self) -> None:
        """스톱워치를 일시정지합니다."""
        self._apply_stopwatch_state(clock_domain.pause_stopwatch(self._stopwatch_state(), time.monotonic()))
        if hasattr(self, "stopwatch_start_button"):
            self.stopwatch_start_button.setText(self.tr("clock.action.start", "시작"))

    def reset_stopwatch(self) -> None:
        """스톱워치를 0으로 초기화합니다."""
        self._apply_stopwatch_state(clock_domain.reset_stopwatch())
        self.stopwatch_label.setText(self.format_stopwatch(0.0))
        if hasattr(self, "stopwatch_start_button"):
            self.stopwatch_start_button.setText(self.tr("clock.action.start", "시작"))

    def start_timer(self) -> None:
        """타이머를 시작합니다."""
        if self.timer_running:
            return
        requested_ms = self.timer_input_milliseconds()
        self._apply_timer_state(clock_domain.start_timer(self._timer_state(), requested_ms, time.monotonic()))
        self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def pause_timer(self) -> None:
        """타이머를 일시정지합니다."""
        self._apply_timer_state(clock_domain.pause_timer(self._timer_state(), time.monotonic()))

    def reset_timer(self) -> None:
        """타이머를 입력값 기준으로 초기화합니다."""
        self._apply_timer_state(clock_domain.reset_timer(self.timer_input_milliseconds()))
        self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def refresh_timer_from_inputs(self) -> None:
        """입력된 시:분:초 값으로 타이머 설정을 갱신합니다."""
        if self.timer_running or self.timer_remaining_before_pause_ms > 0:
            return
        self.timer_remaining_ms = self.timer_input_milliseconds()
        self.timer_label.setText(self.format_milliseconds(self.timer_remaining_ms))

    def current_stopwatch_elapsed(self) -> float:
        """현재 스톱워치 경과 시간을 반환합니다."""
        return clock_domain.current_stopwatch_elapsed(self._stopwatch_state(), time.monotonic())

    def current_timer_remaining_ms(self) -> int:
        """현재 타이머 남은 시간(ms)을 반환합니다."""
        return clock_domain.current_timer_remaining_ms(self._timer_state(), time.monotonic())

    def timer_input_milliseconds(self) -> int:
        """타이머 입력 위젯 값을 밀리초로 변환합니다."""
        return (
            self.timer_hours.value() * 3_600_000
            + self.timer_minutes.value() * 60_000
            + self.timer_seconds.value() * 1000
        )

    def format_milliseconds(self, total_ms: int) -> str:
        """밀리초를 mm:ss(또는 hh:mm:ss) 문자열로 만듭니다."""
        total_ms = max(0, int(total_ms))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) // 1000
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def format_stopwatch(self, elapsed: float) -> str:
        """스톱워치 경과 시간을 화면용 문자열로 만듭니다."""
        total_ms = max(0, int(elapsed * 1000))
        hours = total_ms // 3_600_000
        minutes = (total_ms % 3_600_000) // 60_000
        seconds = (total_ms % 60_000) // 1000
        millis = total_ms % 1000
        if hours:
            return f"{hours:02}:{minutes:02}:{seconds:02}.{millis:03}"
        return f"{minutes:02}:{seconds:02}.{millis:03}"
