"""ChronoFox 진입점 셔틀 shim.

본체는 `chronofox/windows/desktop_note_calendar.py`(FoxCalendarApp 등)로 이동했다
(C3, repo-layout-v1 §4). 이 루트 파일은 얇은 셔틀로만 남는다 — PyInstaller spec의
진입 스크립트 경로, Windows 시작프로그램 등록 스크립트 경로, 사용자의 기존 실행
습관(`python desktop_note_calendar.py`)이 전부 이 경로를 가리키므로 파일명·위치를
바꾸지 않는다. 본체의 공개 심볼은 재수출하지 않는다 — 필요하면
`chronofox.windows.desktop_note_calendar`를 직접 import한다.
"""

from __future__ import annotations

from chronofox.windows.desktop_note_calendar import main

if __name__ == "__main__":
    main()
