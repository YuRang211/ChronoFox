"""APP_DIR에 순환(rotating) 로그 파일을 남기도록 표준 logging을 초기화하는 모듈."""

from __future__ import annotations

import logging
import logging.handlers
import os
from copy import copy

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
LOG_MAX_BYTES = 512 * 1024
LOG_BACKUP_COUNT = 3


def _exception_summary(exc_info: tuple) -> str:
    """Keep error types and code locations, never exception text or source lines."""
    current = exc_info[1]
    seen: set[int] = set()
    summaries: list[str] = []
    while isinstance(current, BaseException) and id(current) not in seen and len(summaries) < 16:
        seen.add(id(current))
        summary = type(current).__name__
        tb = current.__traceback__
        if tb is None and current is exc_info[1]:
            tb = exc_info[2]
        if tb is not None:
            while tb.tb_next is not None:
                tb = tb.tb_next
            code = tb.tb_frame.f_code
            summary += f"@{os.path.basename(code.co_filename)}:{code.co_name}:{tb.tb_lineno}"
        summaries.append(summary)
        cause = current.__cause__
        current = cause if cause is not None else (None if current.__suppress_context__ else current.__context__)
    return " <- ".join(summaries)


class PrivacyFormatter(logging.Formatter):
    """Format code metadata only; do not interpolate user values or mutate shared records."""

    def format(self, record: logging.LogRecord) -> str:
        safe = copy(record)
        safe.msg = f"{record.module}.{record.funcName}:{record.lineno}"
        if record.exc_info:
            safe.msg += f" exception={_exception_summary(record.exc_info)}"
        # Other handlers may already have cached a full traceback on the shared record.
        # Clear every standard Formatter input that can append or format original text.
        safe.args = ()
        safe.exc_info = None
        safe.exc_text = None
        safe.stack_info = None
        return super().format(safe)


class PrivacyRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def handleError(self, record: logging.LogRecord) -> None:
        """A failed log sink must not dump raw records or I/O paths to stderr."""
        # Logging is best effort, including disk-full/rotation failures. The default
        # error handler prints the original message and arguments even with a safe formatter.
        return


def setup_logging() -> None:
    """`APP_DIR/logs/chronofox.log` 회전 파일 로거를 루트 로거에 붙입니다.

    로그 폴더를 만들거나 파일을 열 수 없어도 앱은 절대 죽지 않아야 하므로,
    실패하면 조용히 no-op으로 폴백합니다. 개인정보 정책: 메모/일정 본문 등
    사용자 콘텐츠와 경로는 남기지 않고 예외 종류와 코드 위치만 기록한다.
    """
    # APP_DIR은 테스트가 app_constants를 monkeypatch할 수 있으므로 호출 시점에 조회한다.
    from chronofox.core import app_constants

    try:
        log_dir = app_constants.APP_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = PrivacyRotatingFileHandler(
            log_dir / "chronofox.log",
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
    except Exception:
        root = logging.getLogger()
        if not root.handlers:
            # Without a handler, logging.lastResort prints later raw exceptions to stderr.
            root.addHandler(logging.NullHandler())
        return
    handler.setFormatter(PrivacyFormatter(LOG_FORMAT))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # 재호출(테스트 등) 시 같은 파일 핸들러가 중복으로 쌓이지 않게 기존 것을 정리한다.
    for existing in list(root.handlers):
        if isinstance(existing, logging.handlers.RotatingFileHandler) and getattr(existing, "baseFilename", "").endswith("chronofox.log"):
            root.removeHandler(existing)
            existing.close()
    root.addHandler(handler)
