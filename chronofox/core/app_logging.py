"""APP_DIR에 순환(rotating) 로그 파일을 남기도록 표준 logging을 초기화하는 모듈."""

from __future__ import annotations

import logging
import logging.handlers

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3


def setup_logging() -> None:
    """`APP_DIR/logs/chronofox.log` 회전 파일 로거를 루트 로거에 붙입니다.

    로그 폴더를 만들거나 파일을 열 수 없어도 앱은 절대 죽지 않아야 하므로,
    실패하면 조용히 no-op으로 폴백합니다. 개인정보 정책: 메모/일정 본문 등
    사용자 콘텐츠는 어디서도 로그에 남기지 않는다 — 예외와 작업 이름만 기록한다.
    """
    # APP_DIR은 테스트가 app_constants를 monkeypatch할 수 있으므로 호출 시점에 조회한다.
    from chronofox.core import app_constants

    try:
        log_dir = app_constants.APP_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_dir / "chronofox.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except Exception:
        return
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 재호출(테스트 등) 시 같은 파일 핸들러가 중복으로 쌓이지 않게 기존 것을 정리한다.
    for existing in list(root.handlers):
        if isinstance(existing, logging.handlers.RotatingFileHandler) and getattr(existing, "baseFilename", "").endswith("chronofox.log"):
            root.removeHandler(existing)
            existing.close()
    root.addHandler(handler)
