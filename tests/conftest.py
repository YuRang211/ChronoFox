from __future__ import annotations

import os

# 오프스크린 환경 설정은 이 파일 한 곳에서만 한다 (F4 D1) — 각 테스트 파일의
# 반복된 os.environ.setdefault(...) 호출을 제거한다. QApplication 임포트보다 먼저 실행돼야
# 하므로 이 파일 최상단에 둔다.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QIcon  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app_config  # noqa: E402
import app_constants  # noqa: E402
import app_restore  # noqa: E402
from app_store import AppStore  # noqa: E402
from app_theme import resolve_theme  # noqa: E402


@pytest.fixture(autouse=True)
def _no_fsync(monkeypatch):
    """F4 D2: 테스트에서 os.fsync를 no-op으로 만든다. 내구성 보장은 프로덕션 관심사이고,
    F1의 write_text_atomic이 추가한 fsync 호출이 Windows 테스트를 느리게 만들 가능성을 차단한다."""
    monkeypatch.setattr(os, "fsync", lambda fd: None)


@pytest.fixture(autouse=True)
def _reset_recovery_state(monkeypatch):
    """app_config의 프로세스 전역 상태(_recovery_notices/_startup_bak_done/_save_blocked)가
    테스트 사이에 누출되는 것을 막는다.

    F4 측정 중 실제로 재현된 버그: test_config_safety.py의 일부 테스트는 CONFIG_PATH를
    tmp_path로 패치해 corrupt/non-dict 루트를 로드시키지만 consume_recovery_notices()를
    호출하지 않아 _recovery_notices에 알림이 남는다. 이후 경로를 패치하지 않고 실제
    FoxCalendarApp()을 생성하는 테스트(test_background_alarm.py / test_notification_engine.py /
    test_menu_corners.py)가 같은 프로세스에서 뒤이어 실행되면, __init__이 그 잔여 알림을
    소비해 실제 QMessageBox.warning 모달을 띄우고, offscreen 플랫폼에서는 아무도 닫아주지
    않아 exec()가 영구 대기한다 — pytest tests/test_config_safety.py tests/test_menu_corners.py
    조합으로 100% 재현 확인. 이 fixture는 모든 테스트 시작 전 상태를 초기화해 이 클래스의
    행(hang)을 원천 차단한다."""
    monkeypatch.setattr(app_config, "_recovery_notices", [])
    monkeypatch.setattr(app_config, "_startup_bak_done", False)
    monkeypatch.setattr(app_config, "_save_blocked", set())


@pytest.fixture
def app_paths(tmp_path: Path, monkeypatch):
    """CONFIG_PATH/DATA_PATH/APP_DIR을 tmp_path 하위로 표준화한다 — 실제 사용자 데이터
    (%USERPROFILE%\\.desktop_note_calendar)는 절대 건드리지 않는다.

    app_config.py가 `from app_constants import APP_DIR, ...`로 심볼을 자기 네임스페이스에
    복사해 두므로, app_constants만 패치하면 app_config 안의 참조는 바뀌지 않는다. 이미
    import된 사용처(app_config)도 함께 패치해야 실제로 효과가 있다 — 기존
    test_config_safety.py / test_data_layer_v2.py의 _patch_paths 패턴을 표준화한 것이다.
    """
    app_dir = tmp_path / "app"
    default_notes = app_dir / "Notes"
    config_path = app_dir / "config.json"
    data_path = app_dir / "data.json"
    legacy_notes = tmp_path / "legacy"

    for module in (app_constants, app_config):
        monkeypatch.setattr(module, "APP_DIR", app_dir)
        monkeypatch.setattr(module, "CONFIG_PATH", config_path)
        monkeypatch.setattr(module, "DATA_PATH", data_path)
        monkeypatch.setattr(module, "DEFAULT_NOTES_DIR", default_notes)
        monkeypatch.setattr(module, "LEGACY_NOTES_DIR", legacy_notes)

    # app_restore도 app_config처럼 APP_DIR/CONFIG_PATH/DATA_PATH/DEFAULT_NOTES_DIR을
    # 자기 네임스페이스로 복사해 두므로(S4/2 백업 복원), 여기서도 함께 패치해야
    # 복원 테스트가 실제 사용자 데이터 폴더를 건드리지 않는다.
    monkeypatch.setattr(app_restore, "APP_DIR", app_dir)
    monkeypatch.setattr(app_restore, "CONFIG_PATH", config_path)
    monkeypatch.setattr(app_restore, "DATA_PATH", data_path)
    monkeypatch.setattr(app_restore, "DEFAULT_NOTES_DIR", default_notes)

    return app_dir


class _FakeMemoStore:
    """MemoStore 계약의 읽기 위주 부분집합(memo_ids/load/has_content)만 구현한 인메모리 페이크."""

    def __init__(self, memos: dict[str, str] | None = None) -> None:
        self._memos = dict(memos or {})

    def memo_ids(self) -> list[str]:
        return sorted(self._memos)

    def load(self, memo_id: str) -> str:
        return self._memos.get(memo_id, "")

    def has_content(self, memo_id: str) -> bool:
        return bool(self.load(memo_id).strip())


class _FakeApp:
    """파일별로 복붙되던 SearchApp/TodoApp류 최소 페이크 앱의 단일 표현.
    계약: config/data/icon/memo_store/save()/dialog_colors() + 각 창 슬롯을 None으로 노출.
    특수한 계약(예: opened_memos 추적, 초기 plans 데이터)이 필요한 테스트는 이관하지 말고
    로컬 페이크를 유지한다 (spec §5 이관 규칙)."""

    def __init__(self, config: dict, data: dict, memos: dict[str, str] | None) -> None:
        self.config = config
        self.data = data
        self.store = AppStore(self.config, self.data, lambda _cfg: None, lambda _dat: None)
        self.icon = QIcon()
        self.memo_store = _FakeMemoStore(memos)
        self.search_window = None
        self.repeat_window = None
        self.detail_window = None
        self.settings_window = None
        self.clock_window = None
        self.schedule_windows: dict = {}
        self.memo_windows: dict = {}
        self.save_calls = 0

    def dialog_colors(self) -> dict[str, str]:
        return resolve_theme(self.config)

    def save(self) -> None:
        self.save_calls += 1


@pytest.fixture
def fake_app():
    """파일별 복붙 페이크의 단일 팩토리 (F4 D1). F3에서 AppStore가 도입되면 내부를
    실제 store로 교체해 페이크-실앱 계약 드리프트를 제거할 예정."""

    def make(*, language: str = "ko", theme: str = "light", plans=(), alarms=(), memos=None, **config_extra):
        config = {
            "theme_mode": theme,
            "language": language,
            "font_family": "",
            **config_extra,
        }
        data = {
            "schedules": {},
            "plans": list(plans),
            "recurring_tasks": {"daily": [], "weekly": [], "monthly": [], "yearly": []},
            "alarms": list(alarms),
        }
        return _FakeApp(config, data, memos)

    return make


@pytest.fixture(autouse=True)
def _stop_leftover_timers():
    """[Fable 검수 보강] 테스트 종료 시 살아남은 최상위 위젯들의 QTimer를 전부 멈춘다.

    qtbot.addWidget의 deleteLater는 다음 이벤트 처리 때까지 지연되므로, 직전 테스트가 만든
    실제 FoxCalendarApp의 1초 scheduler_timer가 다음 테스트의 이벤트 루프에서 계속 발화한다.
    그 시점에는 monkeypatch(경로/전역)가 이미 풀려 있어 ① 테스트 알람이 due로 판정되면 실제
    모달을 띄워 offscreen에서 영구 대기(간헐 행 — 5파일 slow 단일 실행에서 발화 지점이 매번
    다른 형태로 재현) ② stale 앱의 save()가 실사용자 경로에 쓸 위험까지 있다. teardown에서
    타이머를 즉시 멈춰 두 경로를 모두 차단한다."""
    yield
    qapp = QApplication.instance()
    if qapp is None:
        return
    for widget in qapp.topLevelWidgets():
        for timer in widget.findChildren(QTimer):
            timer.stop()


@pytest.fixture(autouse=True)
def no_modal(monkeypatch):
    """QMessageBox 계열 모달을 무해화한다 — offscreen 플랫폼에서 exec()가 사용자 상호작용
    없이 영구 대기해 테스트가 멎는 것을 막는다(F4 D1).

    [Fable 검수 보강] opt-in에서 autouse로 승격: offscreen 스위트에서 실제 모달 exec는
    어떤 테스트에서도 정당하게 블로킹할 수 없고(닫아줄 사용자가 없음), 모달 동작을 검증하는
    테스트들은 전부 show_alert 등 상위 계층을 직접 monkeypatch한다."""
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok))
