"""S4/2 백업 복원 기능 회귀 테스트.

대상: app_restore.inspect_backup/restore_backup (Qt 비의존 코어)와
settings_window.SettingsWindow.restore_backup_from_file의 최소 다이얼로그 배선.

커버 범위: 정상 백업 왕복(라운드트립), Zip Slip 공격 차단, manifest 누락 거부,
복원 전 롤백 백업 생성, 깨진 zip에 대한 예외 없는 오류 결과, 설정창 버튼이
inspect_backup/confirm/restore/restart 흐름을 순서대로 호출하는지.

RESTORE1/RESTORE2 (2026-07-11 Fable 전체 리뷰): 복원이 종료 시 저장에 무효화되던 결함과
복원된 config.json의 notes_dir 불일치 가능성에 대한 회귀 테스트도 여기에 포함한다.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QMessageBox

import settings_window
from app_config import create_backup_archive, save_config, save_data
from app_restore import BackupInfo, RestoreResult, inspect_backup, restore_backup
from app_store import AppStore
from app_theme import resolve_theme
from settings_window import SettingsWindow
from window_manager import WindowManager

# ---------------------------------------------------------------------------
# inspect_backup
# ---------------------------------------------------------------------------


def test_inspect_backup_reports_manifest_and_counts(app_paths: Path, tmp_path: Path) -> None:
    """유효한 백업의 생성 시각/앱 이름과 plans/schedules/alarms/recurring/메모 개수를 정확히 센다."""
    app_paths.mkdir(parents=True, exist_ok=True)
    notes_dir = app_paths / "Notes"
    config = {"notes_dir": str(notes_dir)}
    data = {
        "plans": [{"id": "p1"}, {"id": "p2"}],
        "schedules": {"2026-07-10": "회의 준비", "2026-07-11": "장보기", "2026-07-12": "   "},
        "alarms": [{"id": "a1"}],
        "recurring_tasks": {"daily": [{"id": "r1"}], "weekly": [{"id": "r2"}], "monthly": [], "yearly": []},
    }
    (app_paths / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (app_paths / "data.json").write_text(json.dumps(data), encoding="utf-8")
    memos_dir = notes_dir / "Memos"
    memos_dir.mkdir(parents=True)
    (memos_dir / "memo-1.md").write_text("a", encoding="utf-8")
    (memos_dir / "memo-2.md").write_text("b", encoding="utf-8")

    backup_zip = tmp_path / "backup.zip"
    create_backup_archive(config, backup_zip)

    info = inspect_backup(backup_zip)

    assert info.ok
    assert info.app == "ChronoFox"
    assert info.created_at
    assert info.plans_count == 2
    # 실제 데이터 모델은 {ISO날짜: 노트 텍스트 문자열} — 공백뿐인 날짜는 세지 않는다.
    assert info.schedules_count == 2
    assert info.alarms_count == 1
    assert info.recurring_count == 2
    assert info.notes_count == 2


def test_inspect_backup_accepts_config_only_backup(tmp_path: Path) -> None:
    """manifest + config.json만 있어도(둘 다는 아니어도) 유효한 백업으로 인정한다."""
    zip_path = tmp_path / "config-only.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("backup_manifest.json", json.dumps({"app": "ChronoFox", "created_at": "2026-01-01"}))
        archive.writestr("config.json", json.dumps({"a": 1}))

    info = inspect_backup(zip_path)

    assert info.ok
    assert info.plans_count == 0
    assert info.notes_count == 0


def test_inspect_backup_rejects_zip_without_manifest(tmp_path: Path) -> None:
    """backup_manifest.json이 없으면 config.json/data.json이 있어도 거부한다."""
    zip_path = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("config.json", json.dumps({"a": 1}))
        archive.writestr("data.json", json.dumps({"plans": []}))

    info = inspect_backup(zip_path)

    assert info.ok is False
    assert info.error == "missing_manifest"


def test_inspect_backup_rejects_zip_without_config_or_data(tmp_path: Path) -> None:
    """manifest만 있고 config.json/data.json이 둘 다 없으면 거부한다."""
    zip_path = tmp_path / "empty.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("backup_manifest.json", json.dumps({"app": "ChronoFox"}))

    info = inspect_backup(zip_path)

    assert info.ok is False
    assert info.error == "missing_manifest"


def test_inspect_backup_handles_broken_zip_gracefully(tmp_path: Path) -> None:
    """zip이 아닌 파일을 열어도 예외를 던지지 않고 오류 결과를 돌려준다."""
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip file at all")

    info = inspect_backup(broken)

    assert info.ok is False
    assert info.error == "invalid_zip"


# ---------------------------------------------------------------------------
# restore_backup
# ---------------------------------------------------------------------------


def _seed_state(app_dir: Path, notes_dir: Path, *, plans: list, memo_text: str) -> dict:
    app_dir.mkdir(parents=True, exist_ok=True)
    config = {"schema_version": 2, "notes_dir": str(notes_dir)}
    data = {
        "schema_version": 2,
        "plans": plans,
        "schedules": {},
        "alarms": [],
        "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
    }
    (app_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (app_dir / "data.json").write_text(json.dumps(data), encoding="utf-8")
    memos_dir = notes_dir / "Memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    (memos_dir / "memo-1.md").write_text(memo_text, encoding="utf-8")
    return config


def test_restore_backup_roundtrip_matches_backup_contents(app_paths: Path, tmp_path: Path) -> None:
    """백업 생성(상태 A) → 데이터 변경(상태 B) → 복원 → 파일이 다시 상태 A와 일치한다."""
    notes_dir = app_paths / "Notes"
    config = _seed_state(app_paths, notes_dir, plans=[{"id": "p1", "title": "Plan A"}], memo_text="state A content")

    backup_zip = tmp_path / "backup-a.zip"
    create_backup_archive(config, backup_zip)

    # 상태 B로 변경
    (app_paths / "data.json").write_text(
        json.dumps({"schema_version": 2, "plans": [{"id": "p2", "title": "Plan B"}], "schedules": {}, "alarms": [], "recurring_tasks": {}}),
        encoding="utf-8",
    )
    (notes_dir / "Memos" / "memo-1.md").write_text("state B content", encoding="utf-8")

    result = restore_backup(backup_zip, config)

    assert result.ok
    assert result.rollback_path
    restored_data = json.loads((app_paths / "data.json").read_text(encoding="utf-8"))
    assert restored_data["plans"] == [{"id": "p1", "title": "Plan A"}]
    assert (notes_dir / "Memos" / "memo-1.md").read_text(encoding="utf-8") == "state A content"


def test_restore_backup_creates_rollback_before_overwrite(app_paths: Path, tmp_path: Path) -> None:
    """복원 직전 현재(상태 B) 데이터를 APP_DIR/backups/pre-restore-*.zip으로 먼저 저장한다."""
    notes_dir = app_paths / "Notes"
    config = _seed_state(app_paths, notes_dir, plans=[{"id": "p1", "title": "Plan A"}], memo_text="state A")

    backup_zip = tmp_path / "backup-a.zip"
    create_backup_archive(config, backup_zip)

    (app_paths / "data.json").write_text(
        json.dumps({"schema_version": 2, "plans": [{"id": "p2", "title": "Plan B"}], "schedules": {}, "alarms": [], "recurring_tasks": {}}),
        encoding="utf-8",
    )

    result = restore_backup(backup_zip, config)

    assert result.ok
    rollback_path = Path(result.rollback_path)
    assert rollback_path.exists()
    assert rollback_path.parent == app_paths / "backups"
    with zipfile.ZipFile(rollback_path) as archive:
        rollback_data = json.loads(archive.read("data.json"))
    assert rollback_data["plans"] == [{"id": "p2", "title": "Plan B"}]  # 덮어쓰기 전(상태 B) 스냅샷


def test_restore_backup_blocks_zip_slip_attempts(app_paths: Path, tmp_path: Path) -> None:
    """Notes/../ 상위 이동, 최상위 ../ 이동 같은 조작된 zip 멤버는 허용 루트 밖에 쓰이지 않는다."""
    app_paths.mkdir(parents=True, exist_ok=True)
    notes_dir = app_paths / "Notes"
    config = {"schema_version": 2, "notes_dir": str(notes_dir)}
    (app_paths / "config.json").write_text(json.dumps(config), encoding="utf-8")
    (app_paths / "data.json").write_text(json.dumps({"plans": []}), encoding="utf-8")

    malicious_zip = tmp_path / "evil-backup.zip"
    manifest = {"app": "ChronoFox", "created_at": "2026-01-01T00:00:00", "notes_dir": str(notes_dir)}
    with zipfile.ZipFile(malicious_zip, "w") as archive:
        archive.writestr("backup_manifest.json", json.dumps(manifest))
        archive.writestr("config.json", json.dumps({"schema_version": 2, "notes_dir": str(notes_dir), "restored": True}))
        archive.writestr("data.json", json.dumps({"schema_version": 2, "plans": [{"id": "safe"}]}))
        archive.writestr("Notes/../../evil.txt", "should not escape notes dir")
        archive.writestr("../../outside.txt", "should not escape app dir")
        archive.writestr("Notes/../../../evil-abs.txt", "still should not escape")

    result = restore_backup(malicious_zip, config)

    assert result.ok
    # 허용 루트(app_dir, notes_dir) 밖 어디에도 evil 파일이 만들어지지 않아야 한다.
    for evil_name in ("evil.txt", "outside.txt", "evil-abs.txt"):
        assert not list(tmp_path.rglob(evil_name))
        assert not list(app_paths.parent.rglob(evil_name))
    # 정상 항목(config.json/data.json)은 그대로 복원된다.
    restored_config = json.loads((app_paths / "config.json").read_text(encoding="utf-8"))
    assert restored_config.get("restored") is True
    restored_data = json.loads((app_paths / "data.json").read_text(encoding="utf-8"))
    assert restored_data["plans"] == [{"id": "safe"}]


def test_restore_backup_rejects_missing_manifest_without_touching_files(app_paths: Path, tmp_path: Path) -> None:
    """manifest 없는 zip은 즉시 거부되고, 롤백을 만들거나 기존 파일을 건드리지 않는다."""
    notes_dir = app_paths / "Notes"
    config = _seed_state(app_paths, notes_dir, plans=["existing"], memo_text="untouched")

    zip_path = tmp_path / "no-manifest.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("config.json", json.dumps({"restored": True}))
        archive.writestr("data.json", json.dumps({"plans": ["malicious"]}))

    result = restore_backup(zip_path, config)

    assert result.ok is False
    assert result.error == "missing_manifest"
    assert result.rollback_path == ""
    assert not (app_paths / "backups").exists()
    restored_data = json.loads((app_paths / "data.json").read_text(encoding="utf-8"))
    assert restored_data["plans"] == ["existing"]


def test_restore_backup_handles_broken_zip_gracefully(app_paths: Path, tmp_path: Path) -> None:
    """복원 대상 zip 자체가 깨져 있으면 예외 없이 오류 결과를 돌려준다."""
    notes_dir = app_paths / "Notes"
    config = _seed_state(app_paths, notes_dir, plans=[], memo_text="x")

    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"garbage not a zip")

    result = restore_backup(broken, config)

    assert result.ok is False
    assert result.error == "invalid_zip"


def test_restore_backup_normalizes_config_notes_dir_to_current(app_paths: Path, tmp_path: Path) -> None:
    """RESTORE2: 백업 속 config.json이 다른(예: 다른 PC의) notes_dir을 가리켜도, Notes 파일은
    항상 현재 notes_dir 아래로 풀리므로 복원 후 config.json의 notes_dir도 그 값으로 맞춰진다."""
    notes_dir = app_paths / "Notes"
    app_paths.mkdir(parents=True, exist_ok=True)
    (app_paths / "config.json").write_text(json.dumps({"schema_version": 2, "notes_dir": str(notes_dir)}), encoding="utf-8")
    (app_paths / "data.json").write_text(json.dumps({"schema_version": 2, "plans": []}), encoding="utf-8")

    other_notes_dir = tmp_path / "other-machine" / "Notes"
    zip_path = tmp_path / "backup.zip"
    manifest = {"app": "ChronoFox", "created_at": "2026-01-01T00:00:00", "notes_dir": str(other_notes_dir)}
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("backup_manifest.json", json.dumps(manifest))
        archive.writestr("config.json", json.dumps({"schema_version": 2, "notes_dir": str(other_notes_dir)}))
        archive.writestr("data.json", json.dumps({"schema_version": 2, "plans": []}))
        archive.writestr("Notes/Memos/memo-1.md", "restored content")

    config = {"schema_version": 2, "notes_dir": str(notes_dir)}
    result = restore_backup(zip_path, config)

    assert result.ok
    restored_config = json.loads((app_paths / "config.json").read_text(encoding="utf-8"))
    assert restored_config["notes_dir"] == str(notes_dir)
    # Notes 파일 자체도 (다른 경로가 아닌) 현재 notes_dir 아래에 풀려 있어야 한다.
    assert (notes_dir / "Memos" / "memo-1.md").read_text(encoding="utf-8") == "restored content"


# ---------------------------------------------------------------------------
# RESTORE1: 복원이 종료 시 저장에 무효화되지 않는지 (block_runtime_saves / skip_exit_flush)
# ---------------------------------------------------------------------------


class _CountingWindow:
    """isVisible()/save_now() 호출 여부만 기록하는 최소 편집창 더블."""

    def __init__(self) -> None:
        self.save_calls = 0

    def isVisible(self) -> bool:
        return True

    def save_now(self) -> None:
        self.save_calls += 1


class _FlushSimApp:
    """WindowManager.persist_open_windows/persist_open_memos가 요구하는 최소 계약(app)의 더블."""

    def __init__(self, store: AppStore, *, skip_exit_flush: bool) -> None:
        self.store = store
        self.memo_windows: dict = {}
        self.schedule_windows: dict = {}
        self.skip_exit_flush = skip_exit_flush
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1
        self.store.save()


def test_restore_backup_blocks_runtime_saves_after_success(app_paths: Path, tmp_path: Path) -> None:
    """복원 성공 직후 block_runtime_saves()가 걸린다 — 옛 메모리 상태로 save_config/save_data를
    호출해도(예: 재시작 전 어딘가에서 트리거됨) 디스크의 복원본이 byte-identical하게 유지된다."""
    notes_dir = app_paths / "Notes"
    config = _seed_state(app_paths, notes_dir, plans=[{"id": "p1", "title": "Plan A"}], memo_text="state A content")

    backup_zip = tmp_path / "backup-a.zip"
    create_backup_archive(config, backup_zip)

    # 상태 B로 변경(복원 전 옛 메모리 상태를 흉내)
    (app_paths / "data.json").write_text(
        json.dumps({"schema_version": 2, "plans": [{"id": "p2", "title": "Plan B"}], "schedules": {}, "alarms": [], "recurring_tasks": {}}),
        encoding="utf-8",
    )

    result = restore_backup(backup_zip, config)
    assert result.ok

    restored_config_bytes = (app_paths / "config.json").read_bytes()
    restored_data_bytes = (app_paths / "data.json").read_bytes()

    # 옛(상태 B) 메모리 상태로 런타임 저장을 시도해도 D5b와 동일한 _save_blocked 가드가 무시한다.
    save_config({"schema_version": 2, "notes_dir": str(notes_dir), "stale": "B"})
    save_data({"schema_version": 2, "plans": [{"id": "p2", "title": "Plan B"}], "schedules": {}, "alarms": [], "recurring_tasks": {}})

    assert (app_paths / "config.json").read_bytes() == restored_config_bytes
    assert (app_paths / "data.json").read_bytes() == restored_data_bytes


def test_restore_then_simulated_quit_flush_does_not_clobber_restored_files(app_paths: Path, tmp_path: Path) -> None:
    """복원 성공 후 settings_window가 하는 대로 skip_exit_flush를 세우면, closeEvent/quit_from_tray가
    하는 persist_open_windows() + save() 시퀀스를 그대로 재현해도 복원본이 그대로 유지된다."""
    notes_dir = app_paths / "Notes"
    config = _seed_state(app_paths, notes_dir, plans=[{"id": "p1", "title": "Plan A"}], memo_text="state A content")

    backup_zip = tmp_path / "backup-a.zip"
    create_backup_archive(config, backup_zip)

    stale_config = {"schema_version": 2, "notes_dir": str(notes_dir), "stale": "B"}
    stale_data = {"schema_version": 2, "plans": [{"id": "p2", "title": "Plan B"}], "schedules": {}, "alarms": [], "recurring_tasks": {}}
    (app_paths / "data.json").write_text(json.dumps(stale_data), encoding="utf-8")

    result = restore_backup(backup_zip, config)
    assert result.ok

    restored_config_bytes = (app_paths / "config.json").read_bytes()
    restored_data_bytes = (app_paths / "data.json").read_bytes()

    store = AppStore(stale_config, stale_data, save_config, save_data)
    app = _FlushSimApp(store, skip_exit_flush=True)
    memo_window = _CountingWindow()
    app.memo_windows["m1"] = memo_window

    # closeEvent/quit_from_tray가 실제로 하는 시퀀스: persist_open_windows() 후 save().
    WindowManager(app).persist_open_windows()
    app.save()

    assert memo_window.save_calls == 0  # skip_exit_flush면 memo_store.save() 경유 flush도 건너뛴다.
    assert (app_paths / "config.json").read_bytes() == restored_config_bytes
    assert (app_paths / "data.json").read_bytes() == restored_data_bytes


def test_skip_exit_flush_short_circuits_persist_open_windows() -> None:
    """skip_exit_flush가 True면 persist_open_windows()는 열린 창의 save_now()도, app.save()도
    호출하지 않고 조기 반환한다."""
    store = AppStore({"schema_version": 2}, {"schema_version": 2}, lambda _c: None, lambda _d: None)
    app = _FlushSimApp(store, skip_exit_flush=True)
    memo_window = _CountingWindow()
    schedule_window = _CountingWindow()
    app.memo_windows["m1"] = memo_window
    app.schedule_windows["2026-07-11"] = schedule_window

    WindowManager(app).persist_open_windows()

    assert memo_window.save_calls == 0
    assert schedule_window.save_calls == 0
    assert app.save_calls == 0


def test_skip_exit_flush_false_still_flushes_persist_open_windows() -> None:
    """대조군: skip_exit_flush가 False(평상시)면 persist_open_windows()는 평소처럼 flush한다."""
    store = AppStore({"schema_version": 2}, {"schema_version": 2}, lambda _c: None, lambda _d: None)
    app = _FlushSimApp(store, skip_exit_flush=False)
    memo_window = _CountingWindow()
    schedule_window = _CountingWindow()
    app.memo_windows["m1"] = memo_window
    app.schedule_windows["2026-07-11"] = schedule_window

    WindowManager(app).persist_open_windows()

    assert memo_window.save_calls == 1
    assert schedule_window.save_calls == 1
    assert app.save_calls == 1


def test_skip_exit_flush_short_circuits_persist_open_memos() -> None:
    """skip_exit_flush가 True면 persist_open_memos()도 동일하게 조기 반환한다."""
    store = AppStore({"schema_version": 2}, {"schema_version": 2}, lambda _c: None, lambda _d: None)
    app = _FlushSimApp(store, skip_exit_flush=True)
    memo_window = _CountingWindow()
    app.memo_windows["m1"] = memo_window

    WindowManager(app).persist_open_memos()

    assert memo_window.save_calls == 0
    assert app.save_calls == 0


# ---------------------------------------------------------------------------
# settings_window 최소 다이얼로그 배선
# ---------------------------------------------------------------------------


class _RestoreSettingsApp:
    def __init__(self) -> None:
        self.config = {
            "theme_mode": "light",
            "language": "ko",
            "settings_geometry": "620x520",
            "calendar_opacity": 56,
            "holiday_enabled": True,
            "font_family": "",
            "notes_dir": "",
        }
        self.store = AppStore(self.config, {}, lambda _c: None, lambda _d: None)
        self.icon = QIcon()

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        return

    def startup_enabled(self) -> bool:
        return False

    def set_startup(self, enabled: bool, show_message: bool = True) -> None:
        return

    def set_calendar_opacity(self, value: int) -> None:
        self.config["calendar_opacity"] = value

    def apply_theme(self) -> None:
        return

    def apply_language(self, source=None) -> None:
        return


@pytest.mark.slow  # F4 D3 관례: SettingsWindow 대형 실창 빌드는 slow lane
def test_restore_backup_from_file_calls_confirm_restore_then_restart(qtbot, monkeypatch, tmp_path: Path) -> None:
    """파일 선택 → inspect_backup → _confirm_restore → restore_backup → _notify_restart_required
    → _restart_app 순서로 호출되는지 검증한다(성공 경로). RESTORE1: "나중에" 선택지는 없다 —
    복원 성공 시 app.skip_exit_flush가 True로 설정되고 재시작이 무조건 뒤따라야 한다."""
    app = _RestoreSettingsApp()
    window = SettingsWindow(app)
    qtbot.addWidget(window)

    zip_path = tmp_path / "backup.zip"
    zip_path.write_bytes(b"fake-zip-bytes")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(zip_path), "")))

    info = BackupInfo(ok=True, created_at="2026-01-01T00:00:00", app="ChronoFox", plans_count=1, schedules_count=2, alarms_count=0, recurring_count=0, notes_count=3)
    monkeypatch.setattr(settings_window, "inspect_backup", lambda _path: info)

    confirm_calls: list[BackupInfo] = []
    monkeypatch.setattr(window, "_confirm_restore", lambda received: confirm_calls.append(received) or True)

    restore_result = RestoreResult(ok=True, rollback_path=str(tmp_path / "rollback.zip"))
    restore_calls: list[tuple] = []

    def _fake_restore(path, config):
        restore_calls.append((path, config))
        return restore_result

    monkeypatch.setattr(settings_window, "restore_backup", _fake_restore)

    notified = []
    monkeypatch.setattr(window, "_notify_restart_required", lambda: notified.append(True))
    restarted = []
    monkeypatch.setattr(window, "_restart_app", lambda: restarted.append(True))

    window.restore_backup_from_file()

    assert confirm_calls == [info]
    assert len(restore_calls) == 1
    assert restore_calls[0][0] == Path(zip_path)
    assert notified == [True]
    assert restarted == [True]
    assert app.skip_exit_flush is True


@pytest.mark.slow
def test_restore_backup_from_file_shows_error_and_skips_restore_for_invalid_backup(qtbot, monkeypatch, tmp_path: Path) -> None:
    """inspect_backup이 실패를 보고하면 restore_backup을 호출하지 않고 경고만 띄운다."""
    window = SettingsWindow(_RestoreSettingsApp())
    qtbot.addWidget(window)

    zip_path = tmp_path / "bad.zip"
    zip_path.write_bytes(b"junk")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(zip_path), "")))
    monkeypatch.setattr(settings_window, "inspect_backup", lambda _path: BackupInfo(ok=False, error="invalid_zip"))

    restore_calls: list = []
    monkeypatch.setattr(settings_window, "restore_backup", lambda *a, **k: restore_calls.append(1))

    warnings: list = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a) or QMessageBox.StandardButton.Ok))

    window.restore_backup_from_file()

    assert restore_calls == []
    assert warnings


@pytest.mark.slow
def test_restore_backup_from_file_cancelled_confirmation_skips_restore(qtbot, monkeypatch, tmp_path: Path) -> None:
    """미리보기 확인 다이얼로그에서 취소하면 restore_backup을 호출하지 않는다."""
    window = SettingsWindow(_RestoreSettingsApp())
    qtbot.addWidget(window)

    zip_path = tmp_path / "backup.zip"
    zip_path.write_bytes(b"fake-zip-bytes")

    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(zip_path), "")))
    monkeypatch.setattr(settings_window, "inspect_backup", lambda _path: BackupInfo(ok=True, created_at="x"))
    monkeypatch.setattr(window, "_confirm_restore", lambda _info: False)

    restore_calls: list = []
    monkeypatch.setattr(settings_window, "restore_backup", lambda *a, **k: restore_calls.append(1))

    window.restore_backup_from_file()

    assert restore_calls == []
