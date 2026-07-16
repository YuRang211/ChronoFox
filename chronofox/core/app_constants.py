"""앱 전역에서 공유하는 상수 모음 — 이름/버전, config·data·notes 경로, 폰트, 기본 창 크기/위치."""

from __future__ import annotations

from pathlib import Path

# C1(repo-layout-v1 §4): 이 파일이 chronofox/core/ 하위로 들어오면서 `Path(__file__).parent`
# 기반 자원 경로가 전부 파손된다. REPO_ROOT를 단일 앵커로 두고 자원 경로 상수(APP_ICON_PATH·
# APP_FONT_DIR·LOCALES_DIR·SETTINGS_ICON_DIR)를 여기 한 곳에서만 정의한다 — assets/·locales/는
# C5 전까지 저장소 루트에 그대로 있다. C5에서 assets/·locales/가 chronofox/ 하위로 이동하면
# 앵커를 PACKAGE_DIR(parents[1])로 전환한다.
REPO_ROOT = Path(__file__).resolve().parents[2]

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
APP_ICON_PATH = REPO_ROOT / "assets" / "fox_calendar_icon.png"
APP_FONT_DIR = REPO_ROOT / "assets" / "fonts"
LOCALES_DIR = REPO_ROOT / "locales"
SETTINGS_ICON_DIR = REPO_ROOT / "assets" / "settings_icons"
DEFAULT_FONT_LABEL = "Pretendard"
DEFAULT_FONT_FAMILY = "Pretendard Variable"
SAVE_DEBOUNCE_MS = 400
SEARCH_DEBOUNCE_MS = 180
DEFAULT_CALENDAR_GEOMETRY = "980x620+180+40"
DEFAULT_SETTINGS_GEOMETRY = "860x520"
DEFAULT_SEARCH_GEOMETRY = "520x420"
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
