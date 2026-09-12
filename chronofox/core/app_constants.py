"""앱 전역에서 공유하는 상수 모음 — 이름/버전, config·data·notes 경로, 폰트, 기본 창 크기/위치."""

from __future__ import annotations

import os
from pathlib import Path

# PACKAGE_DIR은 패키지 자원, REPO_ROOT는 소스 실행용 진입점 경로의 기준이다.
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parents[1]

APP_NAME = "크로노폭스"
APP_NAME_EN = "ChronoFox"
# 앱 표시 버전의 단일 출처다. 패키징 파일은 릴리스 스크립트가 동기 검증한다.
APP_VERSION = "0.8.3"
APP_DIR = Path.home() / ".desktop_note_calendar"
UPDATE_API_URL = "https://api.github.com/repos/YuRang211/ChronoFox/releases?per_page=20"
UPDATE_RELEASES_URL = "https://github.com/YuRang211/ChronoFox/releases"
UPDATE_CHANNEL = "beta"
UPDATE_CACHE_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "ChronoFox" / "Updates"
CONFIG_PATH = APP_DIR / "config.json"
DATA_PATH = APP_DIR / "data.json"
# 공휴일 캐시는 삭제해도 재생성되는 파생 데이터라 사용자 데이터와 분리한다.
HOLIDAY_CACHE_PATH = APP_DIR / "holiday_cache.json"
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
# HKCU Run으로 이관하기 전 버전이 만든 파일. 신규 등록에는 쓰지 않고 마이그레이션·제거
# 호환을 위해서만 정확한 두 파일명을 유지한다.
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
