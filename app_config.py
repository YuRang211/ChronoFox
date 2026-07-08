from __future__ import annotations

import contextlib
import json
import locale
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app_constants import APP_DIR, APP_NAME_EN, CONFIG_PATH, DATA_PATH, DEFAULT_FONT_FAMILY, DEFAULT_NOTES_DIR, LEGACY_NOTES_DIR
from app_storage import write_text_atomic

CURRENT_SCHEMA_VERSION = 2
MAX_QUARANTINE_FILES = 5


@dataclass
class RecoveryNotice:
    """손상 격리·미래 스키마 감지처럼 사용자에게 알려야 하는 로드 시점 이벤트입니다."""

    kind: str        # "corrupt_reset" | "newer_schema"
    path: str        # 원본 파일 경로
    quarantine: str  # 격리 파일 경로, newer_schema면 ""


_recovery_notices: list[RecoveryNotice] = []
_startup_bak_done = False
_save_blocked: set[Path] = set()  # D5b: newer_schema 파일은 세션 내내 저장 금지


def consume_recovery_notices() -> list[RecoveryNotice]:
    """누적된 복구 알림을 반환하고 비웁니다. 프로세스당 1회 소비하도록 호출측에서 관리합니다."""
    notices, _recovery_notices[:] = list(_recovery_notices), []
    return notices


def default_language() -> str:
    import sys
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.kernel32.GetUserDefaultUILanguage() == 1042:
                return "ko"
        except Exception:
            pass

    try:
        locale_names = []
        with contextlib.suppress(Exception):
            locale_names.append(locale.getlocale()[0] or "")
        with contextlib.suppress(Exception):
            locale_names.append(locale.getlocale(locale.LC_CTYPE)[0] or "")
        with contextlib.suppress(Exception):
            locale_names.append(locale.getencoding() or "")

        joined = " ".join(locale_names).lower()
        if "ko" in joined or "korean" in joined:
            return "ko"
    except Exception:
        pass

    return "en"


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


def has_saved_memos(notes_dir: Path) -> bool:
    memo_dir = notes_dir / "Memos"
    return memo_dir.exists() and any(path.is_file() for path in memo_dir.glob("*.md"))


def normalize_notes_dir(data: dict) -> None:
    configured_notes_dir = Path(data.get("notes_dir", DEFAULT_NOTES_DIR))
    if configured_notes_dir == LEGACY_NOTES_DIR:
        data["notes_dir"] = str(DEFAULT_NOTES_DIR)
        return
    if configured_notes_dir != DEFAULT_NOTES_DIR and not has_saved_memos(configured_notes_dir) and has_saved_memos(DEFAULT_NOTES_DIR):
        data["notes_dir"] = str(DEFAULT_NOTES_DIR)


def _prune_quarantine_files(path: Path) -> None:
    """파일별 격리본을 최신 MAX_QUARANTINE_FILES개만 남기고 오래된 것부터 정리합니다."""
    candidates = sorted(
        path.parent.glob(f"{path.name}.corrupt-*"),
        key=lambda candidate: candidate.stat().st_mtime,
    )
    excess = max(len(candidates) - MAX_QUARANTINE_FILES, 0)
    for old_path in candidates[:excess]:
        with contextlib.suppress(OSError):
            old_path.unlink()


def _quarantine_corrupt_file(path: Path) -> Path:
    """손상된 파일을 원본 보존을 위해 격리 이름으로 옮기고, 오래된 격리본을 정리합니다."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    quarantine_path = path.with_name(f"{path.name}.corrupt-{timestamp}")
    suffix = 1
    while quarantine_path.exists():
        quarantine_path = path.with_name(f"{path.name}.corrupt-{timestamp}-{suffix}")
        suffix += 1
    try:
        path.replace(quarantine_path)
    except OSError:
        shutil.copy2(path, quarantine_path)
    _prune_quarantine_files(path)
    return quarantine_path


def load_json_object(path: Path) -> dict:
    """JSON 파일을 읽어 dict가 아니면(깨짐/비-object 루트 포함) 격리 후 빈 dict로 복구합니다."""
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    quarantine = _quarantine_corrupt_file(path)
    _recovery_notices.append(RecoveryNotice("corrupt_reset", str(path), str(quarantine)))
    return {}


def _stamp_v2(payload: dict) -> dict:
    """v1 → v2 마이그레이션: schema_version 필드만 추가합니다. 다른 키는 그대로 보존합니다."""
    result = dict(payload)
    result["schema_version"] = 2
    return result


MIGRATIONS_CONFIG: dict[int, Callable[[dict], dict]] = {1: _stamp_v2}
MIGRATIONS_DATA: dict[int, Callable[[dict], dict]] = {1: _stamp_v2}


def _apply_migrations(payload: dict, table: dict[int, Callable[[dict], dict]], path: Path) -> tuple[dict, bool]:
    """반환: (payload, save_allowed). 파일이 미래 스키마 버전이면 손대지 않고 저장을 금지합니다."""
    version = payload.get("schema_version", 1 if payload else CURRENT_SCHEMA_VERSION)
    if version > CURRENT_SCHEMA_VERSION:
        _save_blocked.add(path)  # D5b: 이 세션에서는 런타임 저장(save_config/save_data)도 차단
        _recovery_notices.append(RecoveryNotice("newer_schema", str(path), ""))
        return payload, False
    while version < CURRENT_SCHEMA_VERSION:
        payload = table[version](payload)
        version = payload["schema_version"]
    return payload, True


def _load_and_migrate(path: Path, table: dict[int, Callable[[dict], dict]]) -> tuple[dict, bool, bool]:
    """load_json_object + 마이그레이션을 묶고, 이 호출에서 알림이 발생하지 않았는지(loaded_cleanly)도 함께 반환합니다."""
    notices_before = len(_recovery_notices)
    raw = load_json_object(path)
    payload, save_allowed = _apply_migrations(raw, table, path)
    loaded_cleanly = len(_recovery_notices) == notices_before
    return payload, save_allowed, loaded_cleanly


def load_config() -> dict:
    """설정 파일을 읽고, 없는 값은 기본값으로 채운 뒤 다시 저장합니다."""
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data, save_allowed, _loaded_cleanly = _load_and_migrate(CONFIG_PATH, MIGRATIONS_CONFIG)

    defaults = {
        "schema_version": CURRENT_SCHEMA_VERSION,
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
    normalize_notes_dir(data)
    migrate_legacy_memos(Path(data["notes_dir"]))
    if save_allowed:
        save_config(data)
    return data


def save_config(config: dict) -> None:
    """창 위치, 일정, 설정값 같은 앱 상태를 config.json에 저장합니다."""
    if CONFIG_PATH in _save_blocked:  # D5b: 신버전 파일 보호 — 조용히 no-op
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
    config_only = dict(config)
    for key in ("schedules", "plans", "recurring_tasks", "alarms"):
        config_only.pop(key, None)
    write_json_atomic(CONFIG_PATH, config_only)


def load_data(config: dict) -> dict:
    """일정, 계획, 해야 할 일처럼 늘어나는 사용자 데이터를 별도 파일로 읽습니다."""
    global _startup_bak_done
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data, save_allowed, loaded_cleanly = _load_and_migrate(DATA_PATH, MIGRATIONS_DATA)

    defaults = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        # v0 legacy fallback: 과거 "config에 전부 저장" 시절 잔재 — config dict에 컬렉션이 있으면 끌어온다.
        "schedules": config.get("schedules", {}),
        "plans": config.get("plans", []),
        "recurring_tasks": config.get("recurring_tasks", {"daily": [], "weekly": [], "monthly": [], "yearly": []}),
        "alarms": config.get("alarms", []),
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    if save_allowed:
        save_data(data)
    if loaded_cleanly and not _startup_bak_done:
        _startup_bak_done = True
        if DATA_PATH.exists():
            shutil.copy2(DATA_PATH, DATA_PATH.with_name(f"{DATA_PATH.name}.startup-bak"))
    return data


def save_data(data: dict) -> None:
    """일정, 계획, 해야 할 일 데이터를 data.json에 저장합니다."""
    if DATA_PATH in _save_blocked:  # D5b: 신버전 파일 보호 — 조용히 no-op
        return
    APP_DIR.mkdir(parents=True, exist_ok=True)
    write_json_atomic(DATA_PATH, data)


def write_json_atomic(path: Path, data: dict) -> None:
    """저장 중 앱이 종료되어도 기존 JSON 파일이 깨지지 않도록 원자적으로 씁니다."""
    write_text_atomic(path, json.dumps(data, indent=2, ensure_ascii=False))


def create_backup_archive(config: dict, destination: Path) -> Path:
    """현재 설정, 일정 데이터, 메모 폴더를 zip 백업으로 묶습니다."""
    destination = Path(destination)
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination_path = destination.resolve(strict=False)
    temp_destination = destination.with_name(f"{destination.name}.tmp")
    temp_destination_path = temp_destination.resolve(strict=False)

    notes_dir = Path(config.get("notes_dir", DEFAULT_NOTES_DIR))
    notes_root = notes_dir.resolve(strict=False)
    manifest = {
        "app": APP_NAME_EN,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "notes_dir": str(notes_dir),
    }

    with zipfile.ZipFile(temp_destination, "w", zipfile.ZIP_DEFLATED) as archive:
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
                    if path_resolved in (destination_path, temp_destination_path):
                        continue
                    archive.write(path, Path("Notes") / path.relative_to(notes_dir))
    temp_destination.replace(destination)
    return destination
