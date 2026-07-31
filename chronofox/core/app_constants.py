"""앱 전역에서 공유하는 상수 모음 — 이름/버전, config·data·notes 경로, 폰트, 기본 창 크기/위치."""

from __future__ import annotations

from pathlib import Path

# C5(repo-layout-v1 §4): assets/·locales/가 chronofox/ 하위로 이동 완료 — 자원 경로 앵커를
# PACKAGE_DIR(parents[1], chronofox/ 자체)로 전환했다. REPO_ROOT는 자원 경로용이 아니라
# 저장소 루트 진입점 shim(desktop_note_calendar.py) 경로 참조 전용으로 남는다 — 시작프로그램
# .bat과 SettingsActionsMixin._restart_app()의 재시작 스크립트 경로가 이를 사용 중(C3에서 도입).
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parents[1]

APP_NAME = "크로노폭스"
APP_NAME_EN = "ChronoFox"
# AUDIT-D7: 앱이 실제로 표시하는 버전(설정 정보 페이지 등)의 단일 출처. 패키징 쪽
# (version_info.txt/installer/chronofox.iss/build_release.ps1)은 PyInstaller/Inno Setup이
# 별도 프로세스로 이 값을 직접 import할 수 없어 각자 같은 버전을 하드코딩하며, 각 파일에
# 이 상수를 가리키는 주석을 남겨뒀다 — 버전을 올릴 때는 이 값과 그 3곳을 함께 맞춘다.
APP_VERSION = "0.8.0"
APP_DIR = Path.home() / ".desktop_note_calendar"
CONFIG_PATH = APP_DIR / "config.json"
DATA_PATH = APP_DIR / "data.json"
LEGACY_NOTES_DIR = Path.home() / "Documents" / "DesktopNotes"
DEFAULT_NOTES_DIR = APP_DIR / "Notes"
APP_ICON_PATH = PACKAGE_DIR / "assets" / "fox_calendar_icon.png"
APP_FONT_DIR = PACKAGE_DIR / "assets" / "fonts"
LOCALES_DIR = PACKAGE_DIR / "locales"
DEFAULT_FONT_LABEL = "Pretendard"
DEFAULT_FONT_FAMILY = "Pretendard Variable"
SAVE_DEBOUNCE_MS = 400
SEARCH_DEBOUNCE_MS = 180
DEFAULT_CALENDAR_GEOMETRY = "980x620+180+40"
DEFAULT_SCHEDULE_GEOMETRY = "620x430+260+160"
DEFAULT_MEMO_WIDTH = 280
DEFAULT_MEMO_HEIGHT = 260
STARTUP_PATH = (
    Path.home()
    / "AppData"
    / "Roaming"
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / "Startup"
    / "ChronoFox.bat"
)
LEGACY_STARTUP_PATH = STARTUP_PATH.with_name("FoxCalendar.bat")
