"""TEST1 커버리지 갭 회귀 테스트.

대상(QA.md TEST1): create_backup_archive의 자기제외/symlink 제외/notes_dir 밖 파일 제외,
export_ics의 UID/DTSTART/SUMMARY/이스케이프 라운드트립, MemoStore의 경로 탈출 차단,
set_startup의 시작 프로그램 아티팩트 생성/제거.

F1이 이미 잠근 원자성(zip .tmp 무잔류, ICS atomic write)은 여기서 중복하지 않는다
(tests/test_data_layer_v2.py T10~T12 참고). check_alarms의 발화 매칭 로직(정각 매칭 T1,
스누즈 T5, date-kind 1회성 비활성 T6)은 tests/test_notification_engine.py(F2)가 이미
커버하므로 여기서 중복하지 않는다.
"""

from __future__ import annotations

import subprocess
import zipfile
from pathlib import Path

import pytest
from PySide6.QtWidgets import QMessageBox

from app_config import create_backup_archive
from app_integrations import export_ics
from app_models import MemoStore
from desktop_note_calendar import FoxCalendarApp

# ---------------------------------------------------------------------------
# create_backup_archive: 자기제외 / symlink 제외 / notes_dir 밖 파일 제외
# ---------------------------------------------------------------------------


def test_backup_excludes_destination_zip_when_saved_inside_notes_dir(tmp_path: Path) -> None:
    """백업 zip을 메모 폴더(notes_dir) 안에 저장해도 백업 파일 자기 자신(및 .tmp)이
    아카이브 안에 포함되지 않아야 한다."""
    notes_dir = tmp_path / "Notes"
    (notes_dir / "Memos").mkdir(parents=True)
    (notes_dir / "Memos" / "memo-1.md").write_text("hello", encoding="utf-8")
    config = {"notes_dir": str(notes_dir)}
    destination = notes_dir / "backup.zip"  # 백업 대상이 notes_dir 내부

    result = create_backup_archive(config, destination)

    assert result == destination
    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert "Notes/Memos/memo-1.md" in names
        assert "Notes/backup.zip" not in names
        assert "Notes/backup.zip.tmp" not in names
        assert not any(name.endswith("backup.zip") or name.endswith("backup.zip.tmp") for name in names)


def test_backup_excludes_symlinked_file_inside_notes_dir(tmp_path: Path) -> None:
    """notes_dir 안의 심볼릭 링크 파일은 백업에서 제외된다."""
    notes_dir = tmp_path / "Notes"
    (notes_dir / "Memos").mkdir(parents=True)
    real_file = tmp_path / "outside_secret.md"
    real_file.write_text("secret content", encoding="utf-8")
    link = notes_dir / "Memos" / "linked.md"
    try:
        link.symlink_to(real_file)
    except OSError as exc:
        pytest.skip(f"이 환경은 심볼릭 링크 생성 권한이 없다: {exc}")

    config = {"notes_dir": str(notes_dir)}
    destination = tmp_path / "backup.zip"

    create_backup_archive(config, destination)

    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert "Notes/Memos/linked.md" not in names
        assert not any("secret" in name for name in names)


def test_backup_excludes_files_reached_via_directory_junction_outside_notes_root(tmp_path: Path) -> None:
    """notes_dir 안에 디렉터리 접합점(junction)으로 notes_dir 밖 폴더를 연결해도,
    그 안의 파일은 resolve() 후 notes_root 밖으로 판정돼 백업에서 제외된다.

    Windows 디렉터리 junction은 `Path.is_symlink()`가 True를 반환하지 않으므로
    (일반 심볼릭 링크 체크로는 걸러지지 않음), create_backup_archive의
    `path_resolved.relative_to(notes_root)` 가드가 실제로 이 경로를 방어하는지 확인한다.
    관리자 권한이 필요한 일반 심볼릭 링크와 달리 `mklink /J`는 일반 권한으로 동작한다.
    """
    notes_dir = tmp_path / "Notes"
    notes_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside_target"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("outside content", encoding="utf-8")
    junction = notes_dir / "escape_link"

    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not junction.exists():
        pytest.skip(f"이 환경은 디렉터리 junction을 만들 수 없다: {result.stderr or result.stdout}")

    config = {"notes_dir": str(notes_dir)}
    destination = tmp_path / "backup.zip"

    create_backup_archive(config, destination)

    with zipfile.ZipFile(destination) as archive:
        names = archive.namelist()
        assert not any("secret" in name for name in names)
        assert not any("escape_link" in name for name in names)


# ---------------------------------------------------------------------------
# export_ics: schedules / timed plan / long(all-day) plan 라운드트립 + UID/이스케이프
# ---------------------------------------------------------------------------


def test_export_ics_schedule_note_round_trip(tmp_path: Path) -> None:
    data = {"schedules": {"2026-07-08": "회의\n오후 3시"}, "plans": []}
    destination = tmp_path / "cal.ics"

    export_ics(data, destination)
    text = destination.read_text(encoding="utf-8")

    assert "UID:fox-calendar-schedule-2026-07-08@fox-calendar" in text
    assert "DTSTART;VALUE=DATE:20260708" in text
    assert "SUMMARY:회의" in text
    assert "DESCRIPTION:회의\\n오후 3시" in text


def test_export_ics_timed_plan_round_trip(tmp_path: Path) -> None:
    data = {
        "schedules": {},
        "plans": [
            {
                "id": "p1",
                "kind": "day",
                "title": "Standup",
                "start": "2026-07-10T09:00:00",
                "end": "2026-07-10T09:30:00",
                "description": "daily sync",
            }
        ],
    }
    destination = tmp_path / "cal.ics"

    export_ics(data, destination)
    text = destination.read_text(encoding="utf-8")

    assert "UID:fox-calendar-plan-p1@fox-calendar" in text
    assert "DTSTART:20260710T090000" in text
    assert "DTEND:20260710T093000" in text
    assert "SUMMARY:Standup" in text
    assert "DESCRIPTION:daily sync" in text


def test_export_ics_long_all_day_plan_uses_date_only_range(tmp_path: Path) -> None:
    """kind='long'(종일/여러 날) 일정은 DTSTART/DTEND가 시간 없이 VALUE=DATE로,
    종료일은 iCalendar 관례대로 마지막 날 다음날(exclusive)로 내보내진다."""
    data = {
        "schedules": {},
        "plans": [
            {
                "id": "p2",
                "kind": "long",
                "title": "Sprint week",
                "start": "2026-07-06T00:00:00",
                "end": "2026-07-10T23:59:00",
            }
        ],
    }
    destination = tmp_path / "cal.ics"

    export_ics(data, destination)
    text = destination.read_text(encoding="utf-8")

    assert "UID:fox-calendar-plan-p2@fox-calendar" in text
    assert "DTSTART;VALUE=DATE:20260706" in text
    assert "DTEND;VALUE=DATE:20260711" in text  # 마지막 날(07-10) 다음날 = exclusive 종료
    assert "SUMMARY:Sprint week" in text
    assert "DTSTART:2026" not in text  # 시간 포함 포맷이 아니어야 한다


def test_export_ics_escapes_special_characters() -> None:
    from app_integrations import _ics_escape

    raw = "쉼표,세미콜론;백슬래시\\줄바꿈\n윈도우줄바꿈\r\n"
    escaped = _ics_escape(raw)

    assert "\\," in escaped
    assert "\\;" in escaped
    assert "\\\\" in escaped
    assert "\\n" in escaped
    assert "\r\n" not in escaped or escaped.count("\\n") >= 2


# ---------------------------------------------------------------------------
# MemoStore: path_for/load/delete 탈출 차단
# ---------------------------------------------------------------------------


def test_memo_store_path_for_blocks_parent_traversal(tmp_path: Path) -> None:
    store = MemoStore(tmp_path)

    with pytest.raises(ValueError):
        store.path_for("../outside")

    with pytest.raises(ValueError):
        store.path_for("../../etc/passwd")


def test_memo_store_path_for_blocks_absolute_like_id(tmp_path: Path) -> None:
    store = MemoStore(tmp_path)
    outside = tmp_path.parent / "should_not_be_touched.md"

    # 절대 경로 형태의 id가 memo_dir 밖으로 벗어나면 차단돼야 한다.
    with pytest.raises(ValueError):
        store.path_for(str(outside.with_suffix("")))


def test_memo_store_load_returns_empty_string_for_escaping_id_without_raising(tmp_path: Path) -> None:
    """load()는 path_for의 ValueError를 삼키고 빈 문자열을 반환해 호출부를 깨뜨리지 않는다."""
    store = MemoStore(tmp_path)

    assert store.load("../outside") == ""


def test_memo_store_delete_is_noop_for_escaping_id(tmp_path: Path) -> None:
    """delete()가 탈출 id에 대해 예외 없이 조용히 무시하고, memo_dir 밖 파일은 절대
    지워지지 않는다."""
    notes_dir = tmp_path / "notes"
    store = MemoStore(notes_dir)
    victim = tmp_path / "victim.md"
    victim.write_text("do not delete me", encoding="utf-8")

    # "../victim" 같은 id로 memo_dir 밖의 파일을 지우려는 시도는 무시돼야 한다.
    store.delete("../victim")

    assert victim.exists()
    assert victim.read_text(encoding="utf-8") == "do not delete me"


def test_memo_store_save_and_load_round_trip_stays_inside_memo_dir(tmp_path: Path) -> None:
    """정상 id는 평소대로 memo_dir 안에만 파일을 만든다(회귀 방지용 대조군)."""
    store = MemoStore(tmp_path)
    store.save("normal-id", "content")

    saved_files = list((tmp_path / "Memos").glob("*.md"))
    assert len(saved_files) == 1
    assert saved_files[0].name == "normal-id.md"
    assert store.load("normal-id") == "content\n"


# ---------------------------------------------------------------------------
# set_startup: 시작 프로그램 아티팩트 생성/제거 (실제 시작프로그램 폴더 절대 미접근)
# ---------------------------------------------------------------------------


@pytest.fixture
def startup_app(tmp_path: Path, monkeypatch):
    """STARTUP_PATH/LEGACY_STARTUP_PATH를 tmp_path 하위로 패치한 뒤 __init__ 없이
    FoxCalendarApp 인스턴스를 만든다(Qt 전체 부팅 없이 set_startup만 단위 테스트)."""
    startup_path = tmp_path / "startup" / "ChronoFox.bat"
    legacy_path = tmp_path / "startup" / "FoxCalendar.bat"
    monkeypatch.setattr("desktop_note_calendar.STARTUP_PATH", startup_path)
    monkeypatch.setattr("desktop_note_calendar.LEGACY_STARTUP_PATH", legacy_path)

    app = FoxCalendarApp.__new__(FoxCalendarApp)
    app.config = {"language": "ko"}
    return app, startup_path, legacy_path


def test_set_startup_enabled_creates_startup_script(startup_app) -> None:
    app, startup_path, _legacy_path = startup_app
    assert not startup_path.exists()

    app.set_startup(True, show_message=False)

    assert startup_path.exists()
    content = startup_path.read_text(encoding="utf-8")
    assert "start" in content
    assert "desktop_note_calendar.py" in content.replace("\\", "/")


def test_set_startup_disabled_removes_startup_script(startup_app) -> None:
    app, startup_path, _legacy_path = startup_app
    startup_path.parent.mkdir(parents=True, exist_ok=True)
    startup_path.write_text("stale", encoding="utf-8")

    app.set_startup(False, show_message=False)

    assert not startup_path.exists()


def test_set_startup_removes_legacy_bat_regardless_of_enabled_value(startup_app) -> None:
    app, _startup_path, legacy_path = startup_app
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("old FoxCalendar.bat", encoding="utf-8")

    app.set_startup(False, show_message=False)

    assert not legacy_path.exists()


def test_startup_enabled_true_when_either_artifact_exists(startup_app) -> None:
    app, startup_path, legacy_path = startup_app
    assert app.startup_enabled() is False

    startup_path.parent.mkdir(parents=True, exist_ok=True)
    startup_path.write_text("x", encoding="utf-8")
    assert app.startup_enabled() is True

    startup_path.unlink()
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text("x", encoding="utf-8")
    assert app.startup_enabled() is True


def test_set_startup_shows_message_only_when_requested(startup_app, monkeypatch) -> None:
    app, _startup_path, _legacy_path = startup_app
    calls: list[tuple] = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: calls.append(a)))

    app.set_startup(True, show_message=False)
    assert calls == []

    app.set_startup(True, show_message=True)
    assert len(calls) == 1
