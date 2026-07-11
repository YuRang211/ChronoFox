"""clock 패키지의 ClockWindow를 재노출하는 하위 호환용 얇은 shim 모듈."""

from __future__ import annotations

from clock import ClockWindow

__all__ = ["ClockWindow"]
