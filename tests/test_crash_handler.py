"""S5 Task 1: app_crash.install_crash_handler(R9) 회귀 테스트.

- app_paths 픽스처로 APP_DIR을 tmp로 샌드박스하고, app_logging.setup_logging()으로 실제
  회전 파일 핸들러를 붙여 로그 기록을 검증한다.
- sys.excepthook은 프로세스 전역 상태이므로 테스트마다 저장/복원한다.
- no_modal(conftest, autouse)이 이미 QMessageBox.critical을 no-op으로 막아 두지만,
  호출 횟수를 세야 하는 테스트는 그 위에 monkeypatch로 다시 덮어써 카운터를 붙인다.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

import pytest
from PySide6.QtWidgets import QMessageBox

import app_crash
import app_logging


def _remove_chronofox_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler) and getattr(handler, "baseFilename", "").endswith("chronofox.log"):
            root.removeHandler(handler)
            handler.close()


@pytest.fixture(autouse=True)
def _sandbox_excepthook_and_handling():
    """sys.excepthook과 app_crash의 재진입 가드는 프로세스 전역 상태이므로 테스트 간에
    누출되지 않게 저장/복원한다.

    pytest-qt는 자체 excepthook을 설치해 Qt 콜백 중 발생한 예외를 잡아 테스트를 실패시킨다.
    이 테스트들은 sys.excepthook을 '의도적으로' 직접 호출하므로, install_crash_handler가
    체이닝 대상으로 pytest-qt의 캡처 훅을 잡지 않도록 기본 훅(sys.__excepthook__)으로
    바꿔둔 뒤 테스트를 실행하고, 종료 시 원래 훅으로 복원한다."""
    previous_hook = sys.excepthook
    sys.excepthook = sys.__excepthook__
    app_crash._handling = False
    yield
    sys.excepthook = previous_hook
    app_crash._handling = False
    _remove_chronofox_handlers()


def _synthetic_exc_info():
    try:
        raise ValueError("synthetic crash for test")
    except ValueError:
        return sys.exc_info()


def test_crash_handler_writes_traceback_to_log(app_paths) -> None:
    app_logging.setup_logging()
    app_crash.install_crash_handler(lambda: None)

    exc_type, exc_value, exc_tb = _synthetic_exc_info()
    sys.excepthook(exc_type, exc_value, exc_tb)

    for handler in logging.getLogger().handlers:
        handler.flush()

    log_path = app_paths / "logs" / "chronofox.log"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "synthetic crash for test" in content
    assert "ValueError" in content


def test_crash_handler_shows_dialog_exactly_once_when_called_recursively(app_paths, monkeypatch) -> None:
    app_logging.setup_logging()
    app_crash.install_crash_handler(lambda: None)

    calls: list[tuple] = []

    def fake_critical(parent, title, body):
        calls.append((title, body))
        if len(calls) == 1:
            # 크래시 처리 도중(대화상자 표시 시점) 재귀적으로 다시 크래시가 나는 상황을 흉내낸다.
            exc_type, exc_value, exc_tb = _synthetic_exc_info()
            sys.excepthook(exc_type, exc_value, exc_tb)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(fake_critical))

    exc_type, exc_value, exc_tb = _synthetic_exc_info()
    sys.excepthook(exc_type, exc_value, exc_tb)

    assert len(calls) == 1
    title, body = calls[0]
    assert title  # crash.title 번역 결과가 비어있지 않아야 한다
    assert body


def test_crash_handler_calls_app_save_best_effort(app_paths, fake_app) -> None:
    app_logging.setup_logging()
    app = fake_app()
    app_crash.install_crash_handler(lambda: app)

    exc_type, exc_value, exc_tb = _synthetic_exc_info()
    sys.excepthook(exc_type, exc_value, exc_tb)

    assert app.save_calls == 1


def test_crash_handler_never_raises_even_if_everything_fails(app_paths, monkeypatch) -> None:
    app_logging.setup_logging()

    class ExplodingApp:
        def save(self) -> None:
            raise RuntimeError("save exploded")

    def exploding_app_getter():
        raise RuntimeError("app_getter exploded")

    def exploding_critical(*_args, **_kwargs):
        raise RuntimeError("dialog exploded")

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(exploding_critical))
    monkeypatch.setattr(app_crash._crash_logger, "exception", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("log exploded")))

    app_crash.install_crash_handler(exploding_app_getter)

    exc_type, exc_value, exc_tb = _synthetic_exc_info()
    # 로그/저장/대화상자가 전부 실패해도 excepthook 호출 자체는 예외를 내지 않아야 한다.
    sys.excepthook(exc_type, exc_value, exc_tb)


def test_crash_handler_chains_to_previous_hook(app_paths) -> None:
    app_logging.setup_logging()

    previous_calls: list[tuple] = []

    def previous_hook(exc_type, exc_value, exc_tb):
        previous_calls.append((exc_type, exc_value, exc_tb))

    sys.excepthook = previous_hook
    app_crash.install_crash_handler(lambda: None)

    exc_type, exc_value, exc_tb = _synthetic_exc_info()
    sys.excepthook(exc_type, exc_value, exc_tb)

    assert len(previous_calls) == 1
    assert previous_calls[0][0] is exc_type
