"""config.json/data.json 읽기·쓰기, 손상 격리(F1 quarantine), schema_version 마이그레이션,
zip 백업 생성(create_backup_archive)을 담당하는 앱 설정/데이터 영속 모듈."""

from __future__ import annotations

import contextlib
import json
import locale
import logging
import shutil
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from chronofox.core.app_constants import (
    APP_DIR,
    APP_NAME_EN,
    CONFIG_PATH,
    DATA_PATH,
    DEFAULT_CALENDAR_GEOMETRY,
    DEFAULT_FONT_FAMILY,
    DEFAULT_NOTES_DIR,
    LEGACY_NOTES_DIR,
)
from chronofox.core.app_hotkey import DEFAULT_QUICK_HOTKEY
from chronofox.core.app_storage import write_text_atomic
from chronofox.core.task_logic import (
    PERIODS,
    compute_next_due,
    normalize_recurrence,
    normalize_task,
    normalize_task_list,
)
from chronofox.core.todo_logic import period_key

CURRENT_SCHEMA_VERSION = 3
MAX_QUARANTINE_FILES = 5
DEFAULT_TASK_LIST_ID = "default"  # T2: 빈/미상 list_name의 정규 list_id


@dataclass
class RecoveryNotice:
    """손상 격리·미래 스키마 감지처럼 사용자에게 알려야 하는 로드 시점 이벤트입니다."""

    kind: str        # "corrupt_reset" | "newer_schema" | "task_migration_failed"
    path: str        # 원본 파일 경로
    quarantine: str  # 격리 파일 경로, newer_schema/task_migration_failed면 ""


class TaskMigrationError(Exception):
    """T2: v2 recurring_tasks → v3 tasks 변환 실패(구조 이상·무손실 검증 실패) 시 발생시킵니다.
    호출부(load_data)가 이 예외를 잡아 원본을 무변경으로 보존하고 schema_version을 2로 유지합니다."""


_recovery_notices: list[RecoveryNotice] = []
_startup_bak_done = False
_save_blocked: set[Path] = set()  # D5b: newer_schema 파일은 세션 내내 저장 금지
_tasks_locked = False  # T2: v2→v3 태스크 마이그레이션 실패 시 할 일 기능만 읽기 전용 잠금
_task_migration_notice_shown = False  # T2: task_migration_failed 알림은 세션당 1회만


def consume_recovery_notices() -> list[RecoveryNotice]:
    """누적된 복구 알림을 반환하고 비웁니다. 프로세스당 1회 소비하도록 호출측에서 관리합니다."""
    notices, _recovery_notices[:] = list(_recovery_notices), []
    return notices


def tasks_locked() -> bool:
    """T2: v2→v3 태스크 마이그레이션이 실패해 할 일 기능이 이 세션 동안 읽기 전용으로
    잠겼는지 여부입니다. `_save_blocked`(달력·일정 전체를 막는 D5b 가드)와는 별개로,
    할 일 영역에만 적용되는 플래그입니다 — UI(T3/T4)가 이 값을 조회해 편집을 막습니다."""
    return _tasks_locked


def block_runtime_saves() -> None:
    """RESTORE1: CONFIG_PATH/DATA_PATH에 대한 런타임 저장(save_config/save_data)을 이 프로세스
    동안 차단합니다. 복원본은 이미 디스크에 원자적으로 쓰여 있으므로, 이후 메모리 상태를 기반으로 한
    저장(창 이동, 메모 flush, 종료 시 save() 등)이 그 위에 덮어써 복원을 무효화하는 것을 막습니다.

    D5b가 newer_schema(미래 스키마 버전) 파일 보호에 쓰던 것과 같은 `_save_blocked` 세트를
    재사용합니다 — save_config/save_data는 이미 이 세트를 확인합니다. CONFIG_PATH/DATA_PATH는
    호출 시점의 모듈 전역 값을 그대로 등록합니다(테스트에서 monkeypatch한 경로도 반영됨)."""
    _save_blocked.add(CONFIG_PATH)
    _save_blocked.add(DATA_PATH)


def default_language() -> str:
    """OS/로케일 설정을 바탕으로 기본 표시 언어 코드('ko' 또는 'en')를 추정합니다."""
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
    """saved memos 존재 여부를 반환합니다."""
    memo_dir = notes_dir / "Memos"
    return memo_dir.exists() and any(path.is_file() for path in memo_dir.glob("*.md"))


def normalize_notes_dir(data: dict) -> None:
    """notes dir를 정규화합니다."""
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
        # 사용자 콘텐츠(파일 본문)는 로그에 남기지 않는다 — 예외와 파일 경로만 기록.
        logging.getLogger(__name__).exception("failed to read/parse JSON object (path=%s)", path)
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


def _stamp_v3_config(payload: dict) -> dict:
    """v2 → v3 config 마이그레이션: schema_version 필드만 갱신합니다(config에는 tasks가 없음 —
    v1→v2의 `_stamp_v2`와 동형인 필드-추가 전용 마이그레이션)."""
    result = dict(payload)
    result["schema_version"] = 3
    return result


# ---------------------------------------------------------------------------
# T2: data v2 → v3 태스크 마이그레이션 (`planning/PROJECT.md` §4 "v2 → v3 마이그레이션")
#
# `recurring_tasks: {daily:[], weekly:[], monthly:[], yearly:[]}` 버킷 모델을
# `tasks: []` + `task_lists: []` 평면 모델로 변환합니다. 정규화·다음 발생일 계산은
# `chronofox.core.task_logic`(T1 산출물)을 재사용하고 재구현하지 않습니다. 변환 후에도
# 원본 `recurring_tasks`는 그대로 남겨 무손실을 보장합니다(§4 마이그레이션 절 — 제거는
# T3 이후 별도 판단).
# ---------------------------------------------------------------------------

# v2 task dict의 알려진 필드 — 여기 없는 키는 "미지 필드"로 간주해 보존합니다(§4 규칙 10).
# "done_count"는 의도적으로 제외합니다: v3 스키마에는 대응 필드가 없는 부가 정보이므로
# 미지 필드 보존 경로를 통해 완료/대기 인스턴스에는 실리되, 재생성된 다음 인스턴스에는
# 승계하지 않습니다(§4 규칙 13과 동일하게, 재생성분은 알려진 필드만으로 새로 만듭니다).
_KNOWN_V2_TASK_FIELDS = {
    "id",
    "text",
    "done",
    "created",
    "counted_keys",
    "important",
    "due",
    "notes",
    "list_name",
    "my_day",
    "steps",
    "order",
    "steps_period",  # §4 마이그레이션 절: 재생성 구조에서 무의미하므로 제거(아무 데도 옮기지 않음)
}


def _unique_task_id(candidate: str, seen: set[str], log: logging.Logger) -> str:
    """`candidate`가 이미 `seen`에 있으면 결정적 접미사(`#2`, `#3`, ...)를 붙여 유일하게 만들고
    로그를 남깁니다(§4 마이그레이션 절 "ID 중복은 뒤 항목에 결정적 접미사 + 로그 기록")."""
    candidate = candidate or "task"
    if candidate not in seen:
        return candidate
    suffix = 2
    deduped = f"{candidate}#{suffix}"
    while deduped in seen:
        suffix += 1
        deduped = f"{candidate}#{suffix}"
    log.warning("task migration: duplicate task id %r deduped to %r", candidate, deduped)
    return deduped


def _validate_lossless_migration(recurring_tasks: dict, tasks: list[dict], source_count: int) -> None:
    """변환 직후 저장 전에 무손실을 검증합니다. 하나라도 어긋나면 `TaskMigrationError`."""
    if source_count == 0:
        if tasks:
            raise TaskMigrationError("no source recurring_tasks items but migrated tasks is non-empty")
        return
    if len(tasks) < source_count:
        raise TaskMigrationError(f"migrated task count ({len(tasks)}) < source item count ({source_count})")
    migrated_texts = {str(task.get("text", "")) for task in tasks}
    for period in PERIODS:
        for raw_task in recurring_tasks.get(period, []) or []:
            if not isinstance(raw_task, dict):
                continue
            text = str(raw_task.get("text", ""))
            if text not in migrated_texts:
                raise TaskMigrationError(f"source text {text!r} missing from migrated tasks")


def migrate_tasks_v2_to_v3(payload: dict, today: date, now: datetime) -> dict:
    """`recurring_tasks` 버킷 모델을 `tasks`/`task_lists` 평면 모델로 변환하는 순수 함수입니다.

    `today`/`now`를 인자로 받아 결정적입니다(task_logic의 관용구와 동일). 실제 마이그레이션
    테이블에 등록되는 `_stamp_v3_data`가 실제 벽시계 값으로 이 함수를 호출하는 얇은 래퍼입니다.
    구조 이상이나 무손실 검증 실패 시 `TaskMigrationError`를 발생시키고, 이 경우 `payload`는
    전혀 수정되지 않습니다(호출부가 원본을 그대로 보존할 수 있게).
    """
    result = dict(payload)
    recurring_tasks = result.get("recurring_tasks")
    if not isinstance(recurring_tasks, dict):
        recurring_tasks = {}

    log = logging.getLogger(__name__)
    tasks: list[dict] = []
    task_lists: list[dict] = []
    seen_list_ids: set[str] = set()
    seen_task_ids: set[str] = set()
    source_count = 0

    for period in PERIODS:
        bucket = recurring_tasks.get(period, [])
        if not isinstance(bucket, list):
            raise TaskMigrationError(f"recurring_tasks[{period!r}] is not a list")
        for bucket_index, raw_task in enumerate(bucket):
            if not isinstance(raw_task, dict):
                raise TaskMigrationError(f"recurring_tasks[{period!r}][{bucket_index}] is not a dict")
            source_count += 1

            list_id = str(raw_task.get("list_name", "") or "").strip() or DEFAULT_TASK_LIST_ID
            if list_id not in seen_list_ids:
                seen_list_ids.add(list_id)
                task_lists.append(normalize_task_list({"id": list_id, "name": list_id}))

            extras = {key: value for key, value in raw_task.items() if key not in _KNOWN_V2_TASK_FIELDS}

            raw_id = str(raw_task.get("id") or f"migrated-{period}-{bucket_index}")
            base_id = _unique_task_id(raw_id, seen_task_ids, log)
            seen_task_ids.add(base_id)

            due_raw = raw_task.get("due") or None
            my_day_raw = raw_task.get("my_day") or None
            counted_keys = list(raw_task.get("counted_keys", []) or [])
            steps = [dict(step) for step in (raw_task.get("steps") or [])]
            order = raw_task.get("order")
            if not isinstance(order, int) or isinstance(order, bool):
                order = None
            important = bool(raw_task.get("important", False))
            text = str(raw_task.get("text", ""))
            notes = str(raw_task.get("notes", ""))
            created = raw_task.get("created") or now.isoformat()

            current_key = period_key(period, today)
            is_done_now = bool(raw_task.get("done")) and raw_task.get("done") == current_key

            if not is_done_now:
                tasks.append(
                    normalize_task(
                        {
                            "id": base_id,
                            "text": text,
                            "notes": notes,
                            "created": created,
                            "completed_at": None,
                            "due": due_raw,
                            "remind_at": None,
                            "important": important,
                            "my_day_date": my_day_raw,
                            "list_id": list_id,
                            "steps": steps,
                            "order": order,
                            "recurrence": normalize_recurrence(
                                {"period": period, "anchor_day": None, "streak_keys": counted_keys}
                            ),
                            **extras,
                        }
                    )
                )
                continue

            # §4 규칙 2와 동형: 완료 인스턴스를 보존하고 다음 pending 인스턴스 하나만 만든다.
            # v2 `set_recurring_done`은 체크 시 counted_keys에 current_key를 이미 추가해 두므로
            # streak_keys는 그대로 승계한다(재계산·재추가하지 않는다).
            streak_keys = counted_keys
            tasks.append(
                normalize_task(
                    {
                        "id": base_id,
                        "text": text,
                        "notes": notes,
                        "created": created,
                        "completed_at": now.isoformat(),
                        "due": due_raw,
                        "remind_at": None,
                        "important": important,
                        "my_day_date": my_day_raw,
                        "list_id": list_id,
                        "steps": steps,
                        "order": order,
                        "recurrence": normalize_recurrence(
                            {"period": period, "anchor_day": None, "streak_keys": list(streak_keys)}
                        ),
                        **extras,
                    }
                )
            )

            next_due: str | None = None
            if due_raw:
                try:
                    next_due = compute_next_due(period, date.fromisoformat(due_raw), None, today).isoformat()
                except (ValueError, TypeError):
                    log.warning(
                        "task migration: unparseable due %r on task id=%s; next due left unset", due_raw, base_id
                    )
                    next_due = None

            next_id = _unique_task_id(f"{base_id}::{current_key}", seen_task_ids, log)
            seen_task_ids.add(next_id)
            # §4 규칙 13: 재생성분은 remind_at·my_day_date를 승계하지 않고, steps는 텍스트만
            # 승계해 전부 미완료로 되돌린다. 미지 필드(extras)도 승계하지 않는다 — 새 인스턴스다.
            next_steps = [{**step, "done": False} for step in steps]
            tasks.append(
                normalize_task(
                    {
                        "id": next_id,
                        "text": text,
                        "notes": notes,
                        "created": now.isoformat(),
                        "completed_at": None,
                        "due": next_due,
                        "remind_at": None,
                        "important": important,
                        "my_day_date": None,
                        "list_id": list_id,
                        "steps": next_steps,
                        "order": order,
                        "recurrence": normalize_recurrence(
                            {"period": period, "anchor_day": None, "streak_keys": list(streak_keys)}
                        ),
                    }
                )
            )

    _validate_lossless_migration(recurring_tasks, tasks, source_count)

    result["tasks"] = tasks
    result["task_lists"] = task_lists
    result["schema_version"] = 3
    return result


def _stamp_v3_data(payload: dict) -> dict:
    """MIGRATIONS_DATA[2] 등록용 래퍼 — 실제 벽시계 today/now로 `migrate_tasks_v2_to_v3`를
    호출합니다. 순수 변환 로직 자체는 결정적이라 테스트가 `migrate_tasks_v2_to_v3`를 직접
    고정된 today/now로 불러 검증합니다."""
    return migrate_tasks_v2_to_v3(payload, date.today(), datetime.now())


MIGRATIONS_CONFIG: dict[int, Callable[[dict], dict]] = {1: _stamp_v2, 2: _stamp_v3_config}
MIGRATIONS_DATA: dict[int, Callable[[dict], dict]] = {1: _stamp_v2, 2: _stamp_v3_data}


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
    # P-2 HL-D2: 이 파일이 이번 호출 전에 이미 있었는지(=기존 사용자)를 마이그레이션/격리
    # 이전에 먼저 확인해 둔다 — load_json_object가 손상 파일을 격리(rename)하면 exists()가
    # False로 바뀌어 구분이 무너지기 때문이다. "기존에 config가 있었다"는 사실 자체가
    # 중요하지, 그 내용이 파싱 가능했는지는 이 판단과 무관하다.
    config_existed = CONFIG_PATH.exists()
    data, save_allowed, _loaded_cleanly = _load_and_migrate(CONFIG_PATH, MIGRATIONS_CONFIG)

    defaults = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "notes_dir": str(DEFAULT_NOTES_DIR),
        "calendar_geometry": DEFAULT_CALENDAR_GEOMETRY,
        "calendar_geometries": {},
        "settings_geometry": "620x520",
        "open_memos": {},
        "memo_titles": {},
        "theme_mode": "system",
        "font_family": DEFAULT_FONT_FAMILY,
        "language": default_language(),
        "holiday_enabled": True,
        "calendar_opacity": 56,
        "calendar_style": "desktop",
        "alert_sound_mode": "default",
        "alert_sound_path": "",
        "alert_sound_url": "",
        "pin_mode": False,  # P-D2: pin-mode-v2 additive. 구버전의 sheet_* 키는 방치(무해).
        "quick_hotkey_enabled": True,  # Q3: 전역 단축키(U1) additive.
        "quick_hotkey": DEFAULT_QUICK_HOTKEY,
    }
    for key, value in defaults.items():
        data.setdefault(key, value)
    # P-2 HL-D2: holiday_country는 나머지 defaults와 값이 같지 않다 — 기존 config는 "KR"로
    # 고정 마이그레이션하고, 신규 설치만 기본값이 "auto"다. 지역 설정이 KR이 아닌 기기를 쓰는
    # 기존 사용자가 어느 날 공휴일을 잃으면 안 된다는 게 이 구분의 이유다.
    data.setdefault("holiday_country", "KR" if config_existed else "auto")
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


def _needs_task_migration_guard(path: Path) -> bool:
    """T2: 이번 `load_data()` 호출이 v2→v3 태스크 변환을 거치게 될지 손상 격리 없이 조회만 해서
    사전 판단합니다. 파일이 없거나 파싱 실패·빈 dict면 변환이 일어나지 않으므로 False입니다
    (기존 손상 복구 경로가 알아서 처리합니다) — 이 함수는 그 경로에 개입하지 않습니다."""
    if not path.exists():
        return False
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not isinstance(parsed, dict) or not parsed:
        return False
    version = parsed.get("schema_version", 1)
    return version < CURRENT_SCHEMA_VERSION


def _create_pre_migration_backup(config: dict) -> bool:
    """T2: v2→v3 태스크 변환 직전 `backups/pre-migration-*.zip`을 생성합니다. 실패하면 로그만
    남기고 False를 반환합니다 — 호출부가 이번 로드에서 태스크 변환을 건너뛰도록 판단합니다
    (백업 없는 손실 가능 변환 금지)."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    destination = APP_DIR / "backups" / f"pre-migration-{timestamp}.zip"
    try:
        create_backup_archive(config, destination)
    except Exception:
        logging.getLogger(__name__).exception("pre-migration backup failed (destination=%s)", destination)
        return False
    return True


def _mark_task_migration_failed(path: Path) -> None:
    """T2: 태스크 마이그레이션 실패(백업 실패 또는 변환/검증 실패)를 기록합니다. 할 일 기능만
    읽기 전용으로 잠그고, `task_migration_failed` 알림은 세션당 1회만 남깁니다."""
    global _tasks_locked, _task_migration_notice_shown
    _tasks_locked = True
    if not _task_migration_notice_shown:
        _task_migration_notice_shown = True
        _recovery_notices.append(RecoveryNotice("task_migration_failed", str(path), ""))


def _load_data_stopping_before_task_migration(path: Path) -> tuple[dict, bool, bool]:
    """T2 폴백: v2→v3 태스크 변환(MIGRATIONS_DATA[2])을 시도하지 않고 v1→v2 스탬프까지만
    적용합니다(백업 실패 또는 변환 검증 실패 시 사용). 원본 `recurring_tasks`와
    schema_version(최대 2)은 그대로 유지됩니다. 반환 형태는 `_load_and_migrate`와 동일해
    `load_data()`의 나머지 흐름(defaults 채움·save_data·startup-bak)을 그대로 재사용할 수
    있습니다 — save_allowed=True이므로 달력·일정 등 나머지 데이터의 저장은 계속 가능합니다."""
    notices_before = len(_recovery_notices)
    raw = load_json_object(path)
    version = raw.get("schema_version", 1 if raw else CURRENT_SCHEMA_VERSION)
    if version > CURRENT_SCHEMA_VERSION:
        _save_blocked.add(path)
        _recovery_notices.append(RecoveryNotice("newer_schema", str(path), ""))
        payload = raw
    elif version < 2:
        payload = MIGRATIONS_DATA[1](raw)  # v1 → v2 스탬프만 적용, v2 → v3(태스크)는 건너뜀
    else:
        payload = raw  # 이미 v2 — 태스크 변환만 이번 로드에서 보류
    loaded_cleanly = len(_recovery_notices) == notices_before
    return payload, True, loaded_cleanly


def load_data(config: dict) -> dict:
    """일정, 계획, 해야 할 일처럼 늘어나는 사용자 데이터를 별도 파일로 읽습니다.

    T2: v2→v3 태스크 마이그레이션 직전에는 반드시 pre-migration 백업이 성공해야 진행합니다.
    백업 실패 또는 변환/무손실 검증 실패 시에는 이번 로드에서 태스크 변환을 건너뛰고
    (schema_version은 2로 유지, recurring_tasks는 무변경) `tasks_locked()`를 True로 만들며
    `task_migration_failed` 알림을 세션당 1회 남깁니다. 달력·일정·알람 등 나머지 데이터는
    계속 정상적으로 읽고 저장할 수 있습니다(§4/§5 — `_save_blocked`는 사용하지 않습니다)."""
    global _startup_bak_done
    APP_DIR.mkdir(parents=True, exist_ok=True)

    if _needs_task_migration_guard(DATA_PATH):
        if _create_pre_migration_backup(config):
            try:
                data, save_allowed, loaded_cleanly = _load_and_migrate(DATA_PATH, MIGRATIONS_DATA)
            except Exception:
                # TaskMigrationError(구조 이상·무손실 검증 실패)뿐 아니라 예상 못 한 다른 예외도
                # 여기서 반드시 삼켜야 한다 — 그러지 않으면 태스크 마이그레이션 버그 하나가
                # load_data() 전체를 죽여 달력·일정까지 포함한 앱 시작 자체를 막는다.
                logging.getLogger(__name__).exception(
                    "task migration failed (path=%s); keeping schema_version=2", DATA_PATH
                )
                _mark_task_migration_failed(DATA_PATH)
                data, save_allowed, loaded_cleanly = _load_data_stopping_before_task_migration(DATA_PATH)
        else:
            _mark_task_migration_failed(DATA_PATH)
            data, save_allowed, loaded_cleanly = _load_data_stopping_before_task_migration(DATA_PATH)
    else:
        data, save_allowed, loaded_cleanly = _load_and_migrate(DATA_PATH, MIGRATIONS_DATA)

    defaults = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        # v0 legacy fallback: 과거 "config에 전부 저장" 시절 잔재 — config dict에 컬렉션이 있으면 끌어온다.
        "schedules": config.get("schedules", {}),
        "plans": config.get("plans", []),
        "recurring_tasks": config.get("recurring_tasks", {"daily": [], "weekly": [], "monthly": [], "yearly": []}),
        "alarms": config.get("alarms", []),
        "tasks": [],  # todo-v3(T2) — 마이그레이션이 채우거나, 신규 설치는 빈 배열로 시작.
        "task_lists": [],
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
