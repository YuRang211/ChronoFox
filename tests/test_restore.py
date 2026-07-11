"""S4/2 백업 복원 기능 회귀 테스트.

대상: app_restore.inspect_backup/restore_backup (Qt 비의존 코어)와
settings_window.SettingsWindow.restore_backup_from_file의 최소 다이얼로그 배선.

커버 범위: 정상 백업 왕복(라운드트립), Zip Slip 공격 차단, manifest 누락 거부,
복원 전 롤백 백업 생성, 깨진 zip에 대한 예외 없는 오류 결과, 설정창 버튼이
inspect_backup/confirm/restore/restart 흐름을 순서대로 호출하는지.
"""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileDialog, QMessageBox

import settings_window
from app_config import create_backup_archive
from app_restore import BackupInfo, RestoreResult, inspect_backup, restore_backup
from app_store import AppStore
from app_theme import resolve_theme
from settings_window import SettingsWindow

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
    """파일 선택 → inspect_backup → _confirm_restore → restore_backup → _prompt_restart_choice
    → _restart_app 순서로 호출되는지 검증한다(성공 경로)."""
    window = SettingsWindow(_RestoreSettingsApp())
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

    restart_prompted = []
    monkeypatch.setattr(window, "_prompt_restart_choice", lambda: restart_prompted.append(True) or True)
    restarted = []
    monkeypatch.setattr(window, "_restart_app", lambda: restarted.append(True))

    window.restore_backup_from_file()

    assert confirm_calls == [info]
    assert len(restore_calls) == 1
    assert restore_calls[0][0] == Path(zip_path)
    assert restart_prompted == [True]
    assert restarted == [True]


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
