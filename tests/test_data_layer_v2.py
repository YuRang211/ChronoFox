from __future__ import annotations

import json
import os
import time
import zipfile
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app_config
import app_models
from app_config import (
    CURRENT_SCHEMA_VERSION,
    RecoveryNotice,
    consume_recovery_notices,
    create_backup_archive,
    load_config,
    load_data,
    save_config,
    save_data,
)
from app_integrations import export_ics
from app_models import MemoStore


def _patch_paths(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    """test_config_safety.py의 패턴을 재사용하고, 프로세스 전역 상태(격리 알림/startup-bak/저장 차단)도 테스트별로 초기화합니다."""
    app_dir = tmp_path / "app"
    default_notes = app_dir / "Notes"
    config_path = app_dir / "config.json"
    data_path = app_dir / "data.json"
    monkeypatch.setattr(app_config, "APP_DIR", app_dir)
    monkeypatch.setattr(app_config, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_config, "DATA_PATH", data_path)
    monkeypatch.setattr(app_config, "DEFAULT_NOTES_DIR", default_notes)
    monkeypatch.setattr(app_config, "LEGACY_NOTES_DIR", tmp_path / "legacy")
    monkeypatch.setattr(app_config, "_recovery_notices", [])
    monkeypatch.setattr(app_config, "_startup_bak_done", False)
    monkeypatch.setattr(app_config, "_save_blocked", set())
    return config_path, data_path


# --- T1/T2: 손상 격리 -------------------------------------------------------


def test_t1_broken_data_json_is_quarantined(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    original_bytes = b"{not valid json"
    data_path.write_bytes(original_bytes)

    data = load_data({})
    notices = consume_recovery_notices()

    assert data["schedules"] == {}
    assert data["plans"] == []
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert len(notices) == 1
    assert notices[0].kind == "corrupt_reset"
    assert notices[0].path == str(data_path)

    quarantine_files = list(data_path.parent.glob("data.json.corrupt-*"))
    assert len(quarantine_files) == 1
    assert quarantine_files[0].read_bytes() == original_bytes
    assert notices[0].quarantine == str(quarantine_files[0])


@pytest.mark.parametrize("payload", [[1, 2, 3], "hello", 42])
def test_t2_non_dict_root_is_quarantined(monkeypatch, tmp_path: Path, payload: object) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    original_text = json.dumps(payload)
    data_path.write_text(original_text, encoding="utf-8")

    data = load_data({})
    notices = consume_recovery_notices()

    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["alarms"] == []
    assert len(notices) == 1
    assert notices[0].kind == "corrupt_reset"

    quarantine_files = list(data_path.parent.glob("data.json.corrupt-*"))
    assert len(quarantine_files) == 1
    assert quarantine_files[0].read_text(encoding="utf-8") == original_text


# --- T3~T6: 버전 판정과 마이그레이션 ------------------------------------------


def test_t3_missing_file_creates_new_versioned_file(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    assert not data_path.exists()

    data = load_data({})
    notices = consume_recovery_notices()

    assert notices == []
    assert not list(data_path.parent.glob("data.json.corrupt-*"))
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    saved = json.loads(data_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION


def test_t4_v1_file_migrates_without_data_loss(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    v1_payload = {
        "schedules": {"2026-07-04": "memo"},
        "plans": [{"id": "1", "title": "trip"}],
        "recurring_tasks": {"daily": ["water"], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [{"id": "a1"}],
    }
    data_path.write_text(json.dumps(v1_payload), encoding="utf-8")

    data = load_data({})
    notices = consume_recovery_notices()

    assert notices == []
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["schedules"] == v1_payload["schedules"]
    assert data["plans"] == v1_payload["plans"]
    assert data["recurring_tasks"] == v1_payload["recurring_tasks"]
    assert data["alarms"] == v1_payload["alarms"]

    saved = json.loads(data_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION
    assert saved["schedules"] == v1_payload["schedules"]
    assert saved["alarms"] == v1_payload["alarms"]


def test_t5_v0_collections_from_config_fallback(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    config = {
        "schedules": {"2026-07-04": "legacy memo"},
        "plans": [{"id": "legacy"}],
        "recurring_tasks": {"daily": ["legacy task"], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [{"id": "legacy-alarm"}],
    }

    data = load_data(config)
    notices = consume_recovery_notices()

    assert notices == []
    assert data["schema_version"] == CURRENT_SCHEMA_VERSION
    assert data["schedules"] == config["schedules"]
    assert data["plans"] == config["plans"]
    assert data["recurring_tasks"] == config["recurring_tasks"]
    assert data["alarms"] == config["alarms"]
    saved = json.loads(data_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION
    assert saved["schedules"] == config["schedules"]


def test_t6_future_schema_version_is_read_only(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    future_payload = {
        "schema_version": 99,
        "schedules": {"2099-01-01": "future"},
        "plans": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [],
    }
    data_path.write_text(json.dumps(future_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    original_bytes = data_path.read_bytes()
    original_mtime = data_path.stat().st_mtime

    data = load_data({})
    notices = consume_recovery_notices()

    assert data["schedules"] == {"2099-01-01": "future"}
    assert data["schema_version"] == 99
    assert len(notices) == 1
    assert notices[0].kind == "newer_schema"
    assert notices[0].path == str(data_path)
    assert notices[0].quarantine == ""
    assert data_path.read_bytes() == original_bytes
    assert data_path.stat().st_mtime == original_mtime
    assert not list(data_path.parent.glob("data.json.corrupt-*"))


def test_d5b_runtime_save_is_blocked_after_newer_schema_load(monkeypatch, tmp_path: Path) -> None:
    """D5b: newer_schema 파일을 로드한 세션에서는 이후 save_data() 호출도 파일을 건드리지 않는다."""
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    future_payload = {
        "schema_version": 99,
        "schedules": {"2099-01-01": "future"},
        "plans": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [],
    }
    data_path.write_text(json.dumps(future_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    original_bytes = data_path.read_bytes()

    data = load_data({})
    consume_recovery_notices()

    # FoxCalendarApp.save()가 창 이동 등으로 세션 중 저장을 시도하는 상황
    data["schedules"]["2026-07-08"] = "downgrade attempt"
    save_data(data)

    assert data_path.read_bytes() == original_bytes
    saved = json.loads(data_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == 99
    assert "2026-07-08" not in saved["schedules"]
    assert not data_path.with_name("data.json.tmp").exists()


def test_d5b_runtime_save_still_works_for_current_schema(monkeypatch, tmp_path: Path) -> None:
    """D5b 가드가 정상(v2) 파일의 일반 저장 경로를 막지 않는다."""
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "schedules": {},
        "plans": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [],
    }
    data_path.write_text(json.dumps(payload), encoding="utf-8")

    data = load_data({})
    assert consume_recovery_notices() == []

    data["schedules"]["2026-07-08"] = "normal save"
    save_data(data)

    saved = json.loads(data_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION
    assert saved["schedules"]["2026-07-08"] == "normal save"


# --- T7/T8: 알림 소비와 startup-bak ------------------------------------------


def test_t7_notices_consumed_once_across_double_config_load(monkeypatch, tmp_path: Path) -> None:
    config_path, _data_path = _patch_paths(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("{not valid json", encoding="utf-8")  # 손상된 config.json

    # main(): 폰트 로딩용으로 load_config() 1회
    load_config()
    # FoxCalendarApp.__init__: load_config() 재호출 (이번엔 이미 복구된 정상 파일을 읽음)
    config_from_init = load_config()

    notices = consume_recovery_notices()

    assert len(notices) == 1
    assert notices[0].kind == "corrupt_reset"
    assert notices[0].path == str(config_path)
    assert config_from_init["theme_mode"] == "system"
    # 이후 다시 consume해도 더 남아있지 않다
    assert consume_recovery_notices() == []


def test_t7_startup_bak_created_only_once_across_double_data_load(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "schedules": {},
        "plans": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [],
    }
    data_path.write_text(json.dumps(payload), encoding="utf-8")

    load_data({})
    bak_path = data_path.with_name("data.json.startup-bak")
    assert bak_path.exists()
    first_mtime = bak_path.stat().st_mtime

    # FoxCalendarApp.__init__이 다시 load_data()를 호출해도 startup-bak은 갱신되지 않는다
    load_data({})

    assert bak_path.stat().st_mtime == first_mtime


def test_t8_startup_bak_matches_content_on_clean_load(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "schedules": {"2026-01-01": "hi"},
        "plans": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [],
    }
    data_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    load_data({})

    bak_path = data_path.with_name("data.json.startup-bak")
    assert bak_path.exists()
    assert json.loads(bak_path.read_text(encoding="utf-8")) == payload


def test_t8_startup_bak_not_updated_after_corrupt_session(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    good_payload = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "schedules": {"2026-01-01": "hi"},
        "plans": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
        "alarms": [],
    }
    data_path.write_text(json.dumps(good_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    load_data({})  # 1세대 startup-bak 생성
    bak_path = data_path.with_name("data.json.startup-bak")
    bak_snapshot = bak_path.read_text(encoding="utf-8")

    # 이후 별도 세션(프로세스)에서 data.json이 손상된 상황을 흉내낸다
    monkeypatch.setattr(app_config, "_startup_bak_done", False)
    data_path.write_text("{not valid json", encoding="utf-8")
    load_data({})
    consume_recovery_notices()

    assert bak_path.read_text(encoding="utf-8") == bak_snapshot


# --- T9: 격리 파일 프루닝 ----------------------------------------------------


def test_t9_quarantine_files_pruned_to_five(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)

    for i in range(7):
        data_path.write_text(f"not valid json {i}", encoding="utf-8")
        load_data({})
        consume_recovery_notices()
        time.sleep(0.01)

    quarantine_files = sorted(data_path.parent.glob("data.json.corrupt-*"))
    assert len(quarantine_files) == app_config.MAX_QUARANTINE_FILES


# --- T10/T11: 백업 zip 원자화 -------------------------------------------------


def test_t10_backup_archive_atomic_no_tmp_left(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    notes_dir = tmp_path / "notes"
    (notes_dir / "Memos").mkdir(parents=True)
    (notes_dir / "Memos" / "memo-1.md").write_text("hello", encoding="utf-8")
    config = {"notes_dir": str(notes_dir)}
    destination = tmp_path / "backup.zip"

    result = create_backup_archive(config, destination)

    assert result == destination
    assert destination.exists()
    assert not destination.with_name("backup.zip.tmp").exists()
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        assert "backup_manifest.json" in archive.namelist()
        assert "Notes/Memos/memo-1.md" in archive.namelist()


def test_t11_backup_archive_failure_preserves_existing_zip(monkeypatch, tmp_path: Path) -> None:
    _config_path, data_path = _patch_paths(monkeypatch, tmp_path)
    config = {"notes_dir": str(tmp_path / "notes")}
    destination = tmp_path / "backup.zip"
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("existing.txt", "old backup")
    original_bytes = destination.read_bytes()

    def boom(*_args, **_kwargs):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(zipfile.ZipFile, "writestr", boom)

    with pytest.raises(RuntimeError):
        create_backup_archive(config, destination)

    assert destination.read_bytes() == original_bytes


# --- T12: ICS 원자화 ---------------------------------------------------------


def test_t12_export_ics_atomic_write_and_content(tmp_path: Path) -> None:
    data = {
        "schedules": {"2026-07-08": "회의\n오후 3시"},
        "plans": [
            {
                "id": "p1",
                "title": "여행",
                "start": "2026-07-10T09:00:00",
                "end": "2026-07-10T10:00:00",
                "kind": "timed",
                "description": "공항 도착",
            }
        ],
    }
    destination = tmp_path / "calendar.ics"

    result = export_ics(data, destination)

    assert result == destination
    assert not destination.with_name("calendar.ics.tmp").exists()
    content = destination.read_bytes()
    assert b"\r\n" in content
    assert b"\r\r\n" not in content  # 원자 쓰기가 개행을 이중 변환하지 않는다
    text = content.decode("utf-8")
    assert "BEGIN:VCALENDAR" in text
    assert "SUMMARY:회의" in text
    assert "SUMMARY:여행" in text


# --- T13: MemoStore.save가 write_text_atomic을 경유 ---------------------------


def test_t13_memo_store_save_uses_write_text_atomic(monkeypatch, tmp_path: Path) -> None:
    original = app_models.write_text_atomic
    calls = []

    def spy(path, text, encoding="utf-8"):
        calls.append(path)
        return original(path, text, encoding)

    monkeypatch.setattr(app_models, "write_text_atomic", spy)

    store = MemoStore(tmp_path)
    store.save("memo-1", "hello world")

    assert calls == [store.path_for("memo-1")]
    assert store.load("memo-1") == "hello world\n"
    assert not (tmp_path / "Memos" / "memo-1.md.tmp").exists()


# --- T14: save_config의 schema_version 보존 + 컬렉션 strip -------------------


def test_t14_save_config_preserves_schema_version_and_strips_collections(monkeypatch, tmp_path: Path) -> None:
    config_path, _data_path = _patch_paths(monkeypatch, tmp_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config = {
        "schema_version": CURRENT_SCHEMA_VERSION,
        "theme_mode": "dark",
        "schedules": {"2026-01-01": "leak"},
        "plans": [{"id": "leak"}],
        "recurring_tasks": {"daily": []},
        "alarms": [{"id": "leak"}],
    }

    save_config(config)

    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == CURRENT_SCHEMA_VERSION
    assert saved["theme_mode"] == "dark"
    for key in ("schedules", "plans", "recurring_tasks", "alarms"):
        assert key not in saved


# --- 보너스: FoxCalendarApp의 복구 다이얼로그 메시지 조립 ------------------------


def test_format_notices_includes_both_kinds() -> None:
    from desktop_note_calendar import _format_notices

    notices = [
        RecoveryNotice("corrupt_reset", "C:/data.json", "C:/data.json.corrupt-1"),
        RecoveryNotice("newer_schema", "C:/config.json", ""),
    ]

    def tr(_key: str, fallback: str = "") -> str:
        return fallback

    message = _format_notices(notices, tr)

    assert "C:/data.json.corrupt-1" in message
    assert "C:/config.json" in message
