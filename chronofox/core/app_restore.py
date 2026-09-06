"""백업 zip 파일을 검사하고 안전하게 복원하는 Qt 비의존 코어 모듈입니다.

`inspect_backup`으로 미리보기 정보를 만들고, `restore_backup`으로 복원 전
자동 롤백 백업을 남긴 뒤 Zip Slip 방어를 적용해 config/data/Notes 파일을
현재 앱 데이터 폴더로 풀어 씁니다. 실제 적용은 앱 재시작 시 F1 마이그레이션
경로를 통해 이뤄지므로, 이 모듈은 실행 중 프로세스의 메모리 상태를 건드리지
않습니다.
"""

from __future__ import annotations

import json
import tempfile
import zipfile
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from chronofox.core.app_config import block_runtime_saves, create_backup_archive, pause_runtime_saves
from chronofox.core.app_constants import APP_DIR, CONFIG_PATH, DATA_PATH, DEFAULT_NOTES_DIR
from chronofox.core.app_storage import write_bytes_atomic

MANIFEST_NAME = "backup_manifest.json"
CONFIG_ENTRY = "config.json"
DATA_ENTRY = "data.json"
NOTES_PREFIX = "Notes/"
_ARCHIVE_ERRORS = (zipfile.BadZipFile, zlib.error, OSError, EOFError, ValueError, RuntimeError, NotImplementedError)


@dataclass
class BackupInfo:
    """백업 zip 미리보기 결과. ok가 False면 나머지 필드는 의미가 없습니다."""

    ok: bool
    error: str = ""
    created_at: str = ""
    app: str = ""
    plans_count: int = 0
    schedules_count: int = 0
    alarms_count: int = 0
    recurring_count: int = 0
    notes_count: int = 0


@dataclass
class RestoreResult:
    """복원 작업 결과. rollback_path는 성공/일부 실패와 무관하게 롤백 백업이
    만들어졌다면 채워집니다(복원 자체가 실패해도 사용자는 롤백본으로 되돌릴 수 있음)."""

    ok: bool
    error: str = ""
    rollback_path: str = ""


def _count_schedules(schedules: object) -> int:
    """schedules dict(실제 모델: {ISO날짜: 노트 텍스트 문자열})에서 내용이 있는 날짜 수를 셉니다."""
    if not isinstance(schedules, dict):
        return 0
    return sum(1 for text in schedules.values() if isinstance(text, str) and text.strip())


def _count_recurring(recurring: object) -> int:
    """daily/weekly/monthly/yearly 버킷으로 구성된 반복 작업 총 개수를 셉니다."""
    if not isinstance(recurring, dict):
        return 0
    total = 0
    for entries in recurring.values():
        if isinstance(entries, list):
            total += len(entries)
    return total


class _InvalidBackup(ValueError):
    pass


def _validate_model(payload: dict, *, is_config: bool) -> None:
    """기존 필드의 구조만 검사하고 누락된 구버전 필드와 알 수 없는 새 필드는 보존합니다."""
    if "schema_version" in payload and (type(payload["schema_version"]) is not int or payload["schema_version"] < 1):
        raise _InvalidBackup("invalid_zip")
    for key in ("plans", "alarms", "tasks", "task_lists"):
        if key in payload and (not isinstance(payload[key], list) or not all(isinstance(item, dict) for item in payload[key])):
            raise _InvalidBackup("invalid_zip")
    if "schedules" in payload and (
        not isinstance(payload["schedules"], dict) or not all(isinstance(value, str) for value in payload["schedules"].values())
    ):
        raise _InvalidBackup("invalid_zip")
    if "recurring_tasks" in payload and (
        not isinstance(payload["recurring_tasks"], dict)
        or not all(isinstance(items, list) and all(isinstance(item, dict) for item in items)
                   for items in payload["recurring_tasks"].values())
    ):
        raise _InvalidBackup("invalid_zip")
    if not is_config:
        return
    for key in ("open_memos", "memo_titles", "calendar_geometries"):
        if key in payload and (
            not isinstance(payload[key], dict) or not all(isinstance(value, str) for value in payload[key].values())
        ):
            raise _InvalidBackup("invalid_zip")
    for key in (
        "notes_dir", "calendar_geometry", "settings_geometry", "theme_mode", "font_family", "language",
        "calendar_style", "alert_sound_mode", "alert_sound_path", "alert_sound_url", "quick_hotkey", "holiday_country",
    ):
        if key in payload and not isinstance(payload[key], str):
            raise _InvalidBackup("invalid_zip")
    for key in ("holiday_enabled", "pin_mode", "quick_hotkey_enabled", "immersive_scrim_enabled"):
        if key in payload and not isinstance(payload[key], bool):
            raise _InvalidBackup("invalid_zip")
    if payload.get("calendar_arrangement") is not None and not isinstance(payload["calendar_arrangement"], str):
        raise _InvalidBackup("invalid_zip")
    if "calendar_opacity" in payload:
        opacity = payload["calendar_opacity"]
        if type(opacity) not in (int, float) or not 0 <= opacity <= 100:
            raise _InvalidBackup("invalid_zip")


def _read_backup_json(archive: zipfile.ZipFile) -> dict[str, dict]:
    names = archive.namelist()
    if MANIFEST_NAME not in names or not {CONFIG_ENTRY, DATA_ENTRY}.intersection(names):
        raise _InvalidBackup("missing_manifest")
    if len(names) != len(set(names)):
        raise _InvalidBackup("invalid_zip")
    documents = {}
    for name in (MANIFEST_NAME, CONFIG_ENTRY, DATA_ENTRY):
        if name not in names:
            continue
        payload = json.loads(archive.read(name).decode("utf-8"))
        if not isinstance(payload, dict):
            raise _InvalidBackup("invalid_zip")
        if name != MANIFEST_NAME:
            _validate_model(payload, is_config=name == CONFIG_ENTRY)
        documents[name] = payload
    return documents


def inspect_backup(zip_path: Path) -> BackupInfo:
    """쓰기 없이 모든 JSON의 구문·루트·모델 구조를 검사하고 요약합니다."""
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            documents = _read_backup_json(archive)
            manifest = documents[MANIFEST_NAME]
            data = documents.get(DATA_ENTRY, {})
            return BackupInfo(
                ok=True,
                created_at=str(manifest.get("created_at", "")),
                app=str(manifest.get("app", "")),
                plans_count=len(data.get("plans", [])),
                schedules_count=_count_schedules(data.get("schedules", {})),
                alarms_count=len(data.get("alarms", [])),
                recurring_count=_count_recurring(data.get("recurring_tasks", {})),
                notes_count=sum(name.startswith(NOTES_PREFIX) and not name.endswith("/") for name in archive.namelist()),
            )
    except _InvalidBackup as exc:
        return BackupInfo(ok=False, error=str(exc))
    except _ARCHIVE_ERRORS:
        return BackupInfo(ok=False, error="invalid_zip")


def _looks_unsafe(name: str) -> bool:
    """zip 멤버 이름 자체에 대한 1차 방어(절대 경로/드라이브 문자/상위 이동 표기).

    최종 판단은 항상 resolve() 후 relative_to()로 하지만, 명백히 의심스러운
    이름을 조기에 걸러내면 구분자 혼용 등으로 인한 실수를 줄일 수 있습니다.
    """
    if not name or name.startswith("/") or name.startswith("\\"):
        return True
    if ":" in name:
        return True
    parts = PurePosixPath(name).parts
    return ".." in parts


def _safe_extract_target(name: str, notes_dir: Path, notes_root: Path, config_root: Path) -> Path | None:
    """zip 멤버 이름을 실제 쓰기 대상 경로로 변환합니다. 허용 루트를 벗어나거나
    알 수 없는 최상위 항목이면 None을 돌려줘 호출측이 건너뛰게 합니다."""
    if name in (MANIFEST_NAME,):
        return None
    if _looks_unsafe(name):
        return None

    if name == CONFIG_ENTRY:
        target, root = CONFIG_PATH, config_root
    elif name == DATA_ENTRY:
        target, root = DATA_PATH, config_root
    elif name.startswith(NOTES_PREFIX):
        rel = name[len(NOTES_PREFIX):]
        if not rel:
            return None
        target, root = notes_dir / rel, notes_root
    else:
        return None  # 알 수 없는 최상위 항목은 조용히 건너뜁니다.

    resolved = target.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        return None  # Zip Slip 시도 — 허용 루트 밖.
    return resolved


def restore_backup(zip_path: Path, config: dict) -> RestoreResult:
    """전체 준비 후 적용하며, 교체 실패는 원복합니다. 성공한 복원은 재시작 때 로드됩니다.

    원복도 실패하면 recovery_failed와 복구 백업 경로를 반환하고 저장을 차단합니다.
    다중 파일 교체 중 전원 손실까지 원자성을 보장하지는 않습니다.
    """
    with pause_runtime_saves():
        result = _restore_backup(Path(zip_path), config)
    if result.ok or result.error == "recovery_failed":
        # 이후 창 이동이나 종료 flush가 옛 메모리로 복원본을 덮지 못하게 저장을 차단한다.
        block_runtime_saves()
    return result


@dataclass
class _PreparedFile:
    target: Path
    content: Path
    original: Path | None


def _prepare_files(archive: zipfile.ZipFile, documents: dict, notes_dir: Path, staging: Path) -> list[_PreparedFile]:
    prepared = []
    targets = set()
    notes_root = notes_dir.resolve(strict=False)
    config_root = APP_DIR.resolve(strict=False)
    for member in archive.infolist():
        if member.is_dir():
            continue
        target = _safe_extract_target(member.filename, notes_dir, notes_root, config_root)
        if target is None:
            continue
        if target in targets or (member.filename.startswith(NOTES_PREFIX) and target in {CONFIG_PATH.resolve(), DATA_PATH.resolve()}):
            raise _InvalidBackup("invalid_zip")
        targets.add(target)
        content = archive.read(member)  # CRC 오류도 모든 쓰기 대상 교체 전에 발견해야 한다.
        if member.filename == CONFIG_ENTRY:
            restored_config = dict(documents[CONFIG_ENTRY])
            # 다른 PC의 notes_dir 대신 이번에 메모를 실제로 푸는 위치를 저장한다.
            restored_config["notes_dir"] = str(notes_dir)
            content = json.dumps(restored_config, indent=2, ensure_ascii=False).encode("utf-8")
        staged = staging / f"{len(prepared)}.new"
        staged.write_bytes(content)
        original = None
        if target.exists():
            original = staging / f"{len(prepared)}.old"
            original.write_bytes(target.read_bytes())
        prepared.append(_PreparedFile(target, staged, original))
    return prepared


def _apply_files(prepared: list[_PreparedFile]) -> str:
    touched = []
    try:
        for entry in prepared:
            entry.target.parent.mkdir(parents=True, exist_ok=True)
            touched.append(entry)
            write_bytes_atomic(entry.target, entry.content.read_bytes())
    except OSError:
        recovered = True
        for entry in reversed(touched):
            try:
                if entry.original is None:
                    entry.target.unlink(missing_ok=True)
                else:
                    original = entry.original.read_bytes()
                    if not entry.target.exists() or entry.target.read_bytes() != original:
                        write_bytes_atomic(entry.target, original)
            except OSError:
                recovered = False
        return "extract_failed" if recovered else "recovery_failed"
    return ""


def _restore_backup(zip_path: Path, config: dict) -> RestoreResult:
    try:
        with tempfile.TemporaryDirectory(prefix="chronofox-restore-", ignore_cleanup_errors=True) as temporary:
            with zipfile.ZipFile(zip_path, "r") as archive:
                documents = _read_backup_json(archive)
                notes_dir = Path(config.get("notes_dir", DEFAULT_NOTES_DIR))
                prepared = _prepare_files(archive, documents, notes_dir, Path(temporary))
            try:
                backups_dir = APP_DIR / "backups"
                backups_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                rollback_path = backups_dir / f"pre-restore-{timestamp}.zip"
                create_backup_archive(config, rollback_path)
            except Exception:
                return RestoreResult(ok=False, error="rollback_failed")
            error = _apply_files(prepared)
            return RestoreResult(ok=not error, error=error, rollback_path=str(rollback_path))
    except _InvalidBackup as exc:
        return RestoreResult(ok=False, error=str(exc))
    except _ARCHIVE_ERRORS:
        return RestoreResult(ok=False, error="invalid_zip")
