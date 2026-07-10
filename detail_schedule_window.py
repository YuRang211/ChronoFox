"""S3P2(M4) re-export shim.

detail_schedule_window.py는 `detail_schedule/` 패키지로 분할됐다(D7).
기존 `from detail_schedule_window import DetailScheduleWindow` 등 호출부/테스트가
무수정으로 계속 동작하도록 이 모듈은 얇은 재수출만 담당한다.
"""

from __future__ import annotations

from detail_schedule.palette import DESIGN_DARK, DESIGN_LIGHT, design_palette
from detail_schedule.window import DetailScheduleWindow

__all__ = ["DESIGN_DARK", "DESIGN_LIGHT", "DetailScheduleWindow", "design_palette"]
