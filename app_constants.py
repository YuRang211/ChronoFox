from __future__ import annotations

from pathlib import Path

APP_NAME = "크로노폭스"
APP_NAME_EN = "ChronoFox"
APP_VERSION = "0.7"
APP_DIR = Path.home() / ".desktop_note_calendar"
CONFIG_PATH = APP_DIR / "config.json"
DATA_PATH = APP_DIR / "data.json"
LEGACY_NOTES_DIR = Path.home() / "Documents" / "DesktopNotes"
DEFAULT_NOTES_DIR = APP_DIR / "Notes"
APP_ICON_PATH = Path(__file__).resolve().parent / "assets" / "fox_calendar_icon.png"
APP_FONT_DIR = Path(__file__).resolve().parent / "assets" / "fonts"
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
