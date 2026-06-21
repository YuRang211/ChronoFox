from __future__ import annotations

import json
import locale
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from app_constants import APP_DIR, APP_NAME_EN, CONFIG_PATH, DATA_PATH, DEFAULT_NOTES_DIR, LEGACY_NOTES_DIR
from app_constants import DEFAULT_FONT_FAMILY


def default_language() -> str:
    locale_names = [
        locale.getlocale()[0] or "",
        locale.getlocale(locale.LC_CTYPE)[0] or "",
        locale.getencoding(),
    ]
    joined = " ".join(locale_names).lower()
    return "ko" if "ko" in joined or "korean" in joined else "en"


def migrate_legacy_memos(target_notes_dir: Path) -> None:
    """기존 Documents\\DesktopNotes 메모를 앱 데이터 폴더로 보존 복사합니다."""
    old_memo_dir = LEGACY_NOTES_DIR / "Memos"
    new_memo_dir = target_notes_dir / "Memos"
    if not old_memo_dir.exists() or old_memo_dir == new_memo_dir:
        return
    new_memo_dir.mkdir(parents=True, exist_ok=True)
    for old_path in old_memo_dir.glob("*.md"):
        new_path = new_memo_dir / old_path.name
        if not new_path.exists():
            shutil.copy2(old_path, new_path)


def load_config() -> dict:
    """설정 파일을 읽고, 없는 값은 기본값으로 채운 뒤 다시 저장합니다."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    defaults = {
        "notes_dir": str(DEFAULT_NOTES_DIR),
        "calendar_geometry": "760x520+180+40",
        "settings_geometry": "620x520",
        "open_memos": {},
        "memo_titles": {},
        "theme_mode": "system",
        "font_family": DEFAULT_FONT_FAMILY,
        "language": default_language(),
        "holiday_enabled": True,
        "calendar_opacity": 56,
        "alert_sound_mode": "default",
        "alert_sound_path": "",
        "alert_sound_url": "",
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    if data.get("font_family") == "Pretendard":
        data["font_family"] = DEFAULT_FONT_FAMILY
    if Path(data.get("notes_dir", "")) == LEGACY_NOTES_DIR:
        data["notes_dir"] = str(DEFAULT_NOTES_DIR)
    migrate_legacy_memos(Path(data["notes_dir"]))
    save_config(data)
    return data


def save_config(config: dict) -> None:
    """창 위치, 일정, 설정값 같은 앱 상태를 config.json에 저장합니다."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    config_only = dict(config)
    for key in ("schedules", "plans", "recurring_tasks", "alarms"):
        config_only.pop(key, None)
    write_json_atomic(CONFIG_PATH, config_only)


def load_data(config: dict) -> dict:
    """일정, 계획, 해야 할 일처럼 늘어나는 사용자 데이터를 별도 파일로 읽습니다."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    if DATA_PATH.exists():
        try:
            data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    else:
        data = {}

    defaults = {
        "schedules": config.get("schedules", {}),
        "plans": config.get("plans", []),
        "recurring_tasks": config.get("recurring_tasks", {"daily": [], "weekly": [], "monthly": [], "yearly": []}),
        "alarms": config.get("alarms", []),
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    save_data(data)
    return data


def save_data(data: dict) -> None:
    """일정, 계획, 해야 할 일 데이터를 data.json에 저장합니다."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(DATA_PATH, data)


def write_json_atomic(path: Path, data: dict) -> None:
    """저장 중 앱이 종료되어도 기존 JSON 파일이 깨질 가능성을 줄입니다."""
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(path)


def create_backup_archive(config: dict, destination: Path) -> Path:
    """현재 설정, 일정 데이터, 메모 폴더를 zip 백업으로 묶습니다."""
    destination = Path(destination)
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_path = destination.resolve(strict=False)

    notes_dir = Path(config.get("notes_dir", DEFAULT_NOTES_DIR))
    notes_root = notes_dir.resolve(strict=False)
    manifest = {
        "app": APP_NAME_EN,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes_dir": str(notes_dir),
    }

    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("backup_manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        if CONFIG_PATH.exists():
            archive.write(CONFIG_PATH, "config.json")
        if DATA_PATH.exists():
            archive.write(DATA_PATH, "data.json")
        if notes_dir.exists():
            for path in notes_dir.rglob("*"):
                if path.is_file():
                    if path.is_symlink():
                        continue
                    path_resolved = path.resolve(strict=False)
                    try:
                        path_resolved.relative_to(notes_root)
                    except ValueError:
                        continue
                    if path_resolved == destination_path:
                        continue
                    archive.write(path, Path("Notes") / path.relative_to(notes_dir))
    return destination
