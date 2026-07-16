"""백업 zip 파일을 검사하고 안전하게 복원하는 Qt 비의존 코어 모듈입니다.

`inspect_backup`으로 미리보기 정보를 만들고, `restore_backup`으로 복원 전
자동 롤백 백업을 남긴 뒤 Zip Slip 방어를 적용해 config/data/Notes 파일을
현재 앱 데이터 폴더로 풀어 씁니다. 실제 적용은 앱 재시작 시 F1 마이그레이션
경로를 통해 이뤄지므로, 이 모듈은 실행 중 프로세스의 메모리 상태를 건드리지
않습니다.
"""

from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from chronofox.core.app_config import block_runtime_saves, create_backup_archive
from chronofox.core.app_constants import APP_DIR, CONFIG_PATH, DATA_PATH, DEFAULT_NOTES_DIR
from chronofox.core.app_storage import write_text_atomic

MANIFEST_NAME = "backup_manifest.json"
CONFIG_ENTRY = "config.json"
DATA_ENTRY = "data.json"
NOTES_PREFIX = "Notes/"


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


def inspect_backup(zip_path: Path) -> BackupInfo:
    """백업 zip을 열어 유효성을 검사하고 요약 정보를 돌려줍니다.

    backup_manifest.json이 없거나 config.json/data.json이 둘 다 없으면 거부합니다.
    깨진 zip이나 손상된 JSON을 만나도 예외를 던지지 않고 오류를 결과에 담습니다.
    """
    zip_path = Path(zip_path)
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            names = set(archive.namelist())
            if MANIFEST_NAME not in names:
                return BackupInfo(ok=False, error="missing_manifest")
            if CONFIG_ENTRY not in names and DATA_ENTRY not in names:
                return BackupInfo(ok=False, error="missing_manifest")

            manifest: dict = {}
            try:
                parsed = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
                if isinstance(parsed, dict):
                    manifest = parsed
            except Exception:
                manifest = {}

            plans_count = schedules_count = alarms_count = recurring_count = 0
            if DATA_ENTRY in names:
                try:
                    data = json.loads(archive.read(DATA_ENTRY).decode("utf-8"))
                except Exception:
                    data = None
                if isinstance(data, dict):
                    plans_count = len(data.get("plans", []) or [])
                    schedules_count = _count_schedules(data.get("schedules", {}))
                    alarms_count = len(data.get("alarms", []) or [])
                    recurring_count = _count_recurring(data.get("recurring_tasks", {}))

            notes_count = sum(
                1 for name in names if name.startswith(NOTES_PREFIX) and not name.endswith("/")
            )

            return BackupInfo(
                ok=True,
                created_at=str(manifest.get("created_at", "")),
                app=str(manifest.get("app", "")),
                plans_count=plans_count,
                schedules_count=schedules_count,
                alarms_count=alarms_count,
                recurring_count=recurring_count,
                notes_count=notes_count,
            )
    except (zipfile.BadZipFile, FileNotFoundError, OSError, EOFError):
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
    """백업 zip을 검증 → 현재 상태 롤백 백업 → Zip Slip 방어 적용 순으로 복원합니다.

    복원된 config.json/data.json/Notes 파일은 프로세스 메모리에 반영되지 않고
    디스크에만 쓰입니다 — 다음 앱 시작 시 F1 마이그레이션/신버전 보호 경로를 통해
    자연스럽게 로드되도록 의도한 설계입니다.
    """
    zip_path = Path(zip_path)
    info = inspect_backup(zip_path)
    if not info.ok:
        return RestoreResult(ok=False, error=info.error or "invalid_zip")

    APP_DIR.mkdir(parents=True, exist_ok=True)
    backups_dir = APP_DIR / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    rollback_path = backups_dir / f"pre-restore-{timestamp}.zip"
    try:
        create_backup_archive(config, rollback_path)
    except Exception:
        return RestoreResult(ok=False, error="rollback_failed")

    notes_dir = Path(config.get("notes_dir", DEFAULT_NOTES_DIR))
    notes_root = notes_dir.resolve(strict=False)
    config_root = APP_DIR.resolve(strict=False)

    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.infolist():
                if member.is_dir():
                    continue
                target = _safe_extract_target(member.filename, notes_dir, notes_root, config_root)
                if target is None:
                    continue
                content = archive.read(member)
                target.parent.mkdir(parents=True, exist_ok=True)
                if member.filename in (CONFIG_ENTRY, DATA_ENTRY):
                    write_text_atomic(target, content.decode("utf-8"))
                else:
                    target.write_bytes(content)
    except (zipfile.BadZipFile, OSError, EOFError):
        return RestoreResult(ok=False, error="extract_failed", rollback_path=str(rollback_path))

    _normalize_restored_notes_dir(notes_dir)

    # RESTORE1: 디스크의 복원본이 이후 메모리 상태 기반 저장(창 이동/종료 flush)에 덮어써지지
    # 않도록, 이 프로세스에서는 CONFIG_PATH/DATA_PATH 런타임 저장을 전부 차단한다.
    block_runtime_saves()

    return RestoreResult(ok=True, rollback_path=str(rollback_path))


def _normalize_restored_notes_dir(notes_dir: Path) -> None:
    """RESTORE2: 복원된 config.json의 notes_dir을 실제 추출 위치(현재 notes_dir)로 맞춘다.

    백업이 다른 PC/경로에서 만들어졌다면 복원된 config.json의 notes_dir이 이번 추출 위치와
    다를 수 있다 — 그대로 두면 재시작 후 메모가 "사라진" 것처럼 보인다. Notes 파일은 항상
    현재 notes_dir 아래로 풀리므로, config.json 쪽을 그 값에 맞춰 단일 정규화한다.
    """
    if not CONFIG_PATH.exists():
        return
    try:
        restored_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(restored_config, dict):
        return
    if restored_config.get("notes_dir") == str(notes_dir):
        return
    restored_config["notes_dir"] = str(notes_dir)
    write_text_atomic(CONFIG_PATH, json.dumps(restored_config, indent=2, ensure_ascii=False))
