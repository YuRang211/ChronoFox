"""잡히지 않은 예외를 로그에 남기고, 최선을 다해 현재 데이터를
저장한 뒤, 사용자에게 안내 대화상자를 한 번만 보여준다.

이 모듈은 이미 크래시가 난 상황에서 동작하므로 스스로 다시 예외를 던지면 안 된다.
로그 기록·데이터 저장·대화상자 표시 중 어느 하나가 실패해도 나머지는 최선을 다해
계속 시도한다. 파일 로그에는 예외 종류와 코드 위치만 남기고 기본 표준 에러 출력의
원문 재출력은 막는다. 명시적으로 설치된 외부 훅은 호환성을 위해 호출하며, 그 훅의
출력 정책은 이 모듈이 통제하지 않는다.
"""

from __future__ import annotations

import contextlib
import logging
import sys
from collections.abc import Callable
from typing import Any

from chronofox.core.app_constants import APP_DIR
from chronofox.ui.app_i18n import translate

_crash_logger = logging.getLogger("crash")

# 크래시 처리 도중(로그/저장/대화상자 어느 단계에서든) 재귀적으로 다시 호출돼도
# 대화상자가 중첩으로 뜨지 않도록 막는 재진입 가드. 최상위 호출이 끝나면 원상복구되므로,
# 이후 별개의 새 크래시에는 정상적으로 다시 안내한다.
_handling = False


def _language_for(app: Any) -> str:
    """app 인스턴스의 store에서 현재 언어를 읽는다. 실패하면 기본값 'ko'."""
    store = getattr(app, "store", None)
    if store is not None:
        try:
            return store.get("language", "ko")
        except Exception:
            return "ko"
    return "ko"


def _log_path_text() -> str:
    try:
        return str(APP_DIR / "logs" / "chronofox.log")
    except Exception:
        return ""


def _try_save(app: Any) -> None:
    """app.save()를 최선을 다해 호출한다 — F1 원자적 쓰기 덕분에 이 시점에 저장이
    실패해도 기존 파일은 깨지지 않는다."""
    if app is None:
        return
    save = getattr(app, "save", None)
    if save is None:
        return
    try:
        save()
    except Exception:
        with contextlib.suppress(Exception):
            _crash_logger.exception("crash handler: best-effort save() failed")


def _show_dialog(app: Any) -> None:
    from PySide6.QtWidgets import QMessageBox

    language = _language_for(app)
    title = translate(language, "crash.title", "크로노폭스 오류")
    body_template = translate(
        language,
        "crash.body",
        "예기치 않은 오류가 발생했습니다. 현재 데이터 저장을 시도했습니다.\n\n오류 기록: {log_path}",
    )
    try:
        body = body_template.format(log_path=_log_path_text())
    except (KeyError, IndexError, ValueError):
        body = body_template
    parent = app if hasattr(app, "isVisible") else None
    QMessageBox.critical(parent, title, body)


def _handle_uncaught_exception(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any, app_getter: Callable[[], Any | None]) -> None:
    global _handling
    if _handling:
        # 크래시 처리 도중 재귀적으로 다시 불렸다 — 대화상자를 중복으로 띄우지 않고 조용히 반환한다.
        return
    _handling = True
    try:
        with contextlib.suppress(Exception):
            _crash_logger.exception("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))

        app = None
        try:
            app = app_getter()
        except Exception:
            app = None

        _try_save(app)

        with contextlib.suppress(Exception):
            _show_dialog(app)
    finally:
        _handling = False


def install_crash_handler(app_getter: Callable[[], Any | None]) -> None:
    """sys.excepthook을 설치한다.

    `app_getter`는 인자 없이 호출되며, 아직 창이 만들어지지 않았으면 None을 반환해도
    된다(예: main()에서 나중에 채워지는 mutable holder를 클로저로 참조). 기존 훅은
    보관해 두었다가, 로그/저장/대화상자 처리 뒤 사용자 정의 훅만 체이닝한다.
    기본 훅은 민감한 예외 메시지를 stderr에 재출력하므로 호출하지 않는다.
    handler 자체는 어떤 경우에도 예외를 다시 던지지 않는다.
    """
    previous_hook = sys.excepthook

    def _hook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any) -> None:
        with contextlib.suppress(Exception):
            _handle_uncaught_exception(exc_type, exc_value, exc_tb, app_getter)
        if previous_hook is not None and previous_hook is not sys.__excepthook__:
            with contextlib.suppress(Exception):
                previous_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook
