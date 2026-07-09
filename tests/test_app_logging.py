"""S2P1 Task 2: app_logging.setup_logging 회귀 테스트.

- app_paths 픽스처로 APP_DIR을 tmp로 샌드박스한다 (실사용자 경로 접근 금지 하드룰).
- Windows에서 열린 로그 파일 핸들이 tmp_path 정리를 막지 않도록 teardown에서 핸들러를 닫는다.
"""
from __future__ import annotations

import logging
import logging.handlers

import pytest

import app_logging


def _remove_chronofox_handlers() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler) and getattr(handler, "baseFilename", "").endswith("chronofox.log"):
            root.removeHandler(handler)
            handler.close()


@pytest.fixture(autouse=True)
def _cleanup_handlers():
    yield
    _remove_chronofox_handlers()


def test_setup_logging_creates_log_file_and_writes(app_paths) -> None:
    app_logging.setup_logging()

    log_path = app_paths / "logs" / "chronofox.log"
    assert log_path.exists()

    logging.getLogger("test.chronofox").info("hello from test")
    for handler in logging.getLogger().handlers:
        handler.flush()

    content = log_path.read_text(encoding="utf-8")
    assert "hello from test" in content
    assert "INFO" in content


def test_setup_logging_unwritable_dir_does_not_raise(tmp_path, monkeypatch) -> None:
    # APP_DIR의 부모 자리를 '파일'로 만들어 logs 디렉터리 생성이 반드시 실패하게 한다.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    import app_constants

    monkeypatch.setattr(app_constants, "APP_DIR", blocker / "app")

    before = list(logging.getLogger().handlers)
    app_logging.setup_logging()  # 예외 없이 no-op으로 폴백해야 한다.
    assert list(logging.getLogger().handlers) == before
