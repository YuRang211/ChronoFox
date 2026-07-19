"""Quick Input(0.9) Q3 — 전역 단축키(U1) Win32 통합부.

`planning/specs/quick-input-parser.md` §4 U1 / §4b Q3 구현. 조합 문자열 파싱(순수
로직)은 `chronofox.core.app_hotkey`에 있다 — 이 모듈은 그 결과를 실제
RegisterHotKey(ctypes) 호출과 Qt 숨김 네이티브 창(nativeEvent)에 연결하는 얇은
오케스트레이션만 담당한다(시트 모드 센티널 선례 패턴 — 판정과 실행을 분리).

구성:
  - `HotkeyBackend`: register/unregister 두 메서드만 요구하는 프로토콜. offscreen
    테스트에서 실제 RegisterHotKey 동작이 불확실하므로 주입 가능하게 설계했다.
  - `Win32HotkeyBackend`: user32.RegisterHotKey/UnregisterHotKey ctypes 실구현
    (argtypes/restypes 명시).
  - `FakeHotkeyBackend`: 테스트용 — 호출 기록 + 등록 성공/실패를 강제할 수 있다.
  - `GlobalHotkeySentinel`: 숨김 네이티브 QWidget. nativeEvent로 WM_HOTKEY(0x0312)를
    받아 `activated` 시그널을 발화한다. 절대 화면에 나타나지 않는다
    (WA_DontShowOnScreen — 메인 창과 독립된 별도 핸들).
  - `GlobalHotkeyController`: config(quick_hotkey_enabled/quick_hotkey)를 읽어
    등록/해제/재등록을 오케스트레이션하고, 등록 실패 시 트레이 풍선 1회 고지(U1
    근거)를 담당한다. 핫키 발화 시 `app.window_manager.open_quick_input()`을
    **동기적으로** 호출한다 — 핫키 처리 중에는 OS가 포그라운드 전환을 허용하므로
    (U1 근거), 지연 없이 그 자리에서 activateWindow까지 끝내야 한다.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
from typing import Protocol

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QObject, Signal

from chronofox.core.app_hotkey import DEFAULT_QUICK_HOTKEY, parse_hotkey_string
from chronofox.ui.app_i18n import translate

logger = logging.getLogger(__name__)

WM_HOTKEY = 0x0312
_HOTKEY_ID = 1  # 이 앱은 단축키를 하나만 쓰므로 상수 id 하나로 충분하다.

_user32 = None


def _ensure_ctypes_ready() -> None:
    """user32 RegisterHotKey/UnregisterHotKey ctypes 시그니처를 지연 초기화합니다
    (모듈 import 시점이 아니라 최초 호출 시점에 — non-Windows 환경 import 실패 방지)."""
    global _user32
    if _user32 is not None:
        return
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32 = user32


class HotkeyBackend(Protocol):
    """RegisterHotKey/UnregisterHotKey 계약 — 실제 Win32 호출과 테스트 페이크가 공유한다."""

    def register(self, hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool: ...
    def unregister(self, hwnd: int, hotkey_id: int) -> bool: ...


class Win32HotkeyBackend:
    """user32.RegisterHotKey/UnregisterHotKey ctypes 실구현."""

    def register(self, hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
        _ensure_ctypes_ready()
        return bool(_user32.RegisterHotKey(hwnd, hotkey_id, modifiers, vk))

    def unregister(self, hwnd: int, hotkey_id: int) -> bool:
        _ensure_ctypes_ready()
        return bool(_user32.UnregisterHotKey(hwnd, hotkey_id))


class FakeHotkeyBackend:
    """테스트용 훅 계층. offscreen에서 실제 RegisterHotKey 성공/실패가 불확실하므로,
    시그널→open_quick_input 배선과 등록 실패 폴백 경로를 이 페이크로 검증한다.
    실기기 확인은 별도(스펙 Q3-5)로 수행한다."""

    def __init__(self, register_result: bool = True) -> None:
        self.register_result = register_result
        self.register_calls: list[tuple[int, int, int, int]] = []
        self.unregister_calls: list[tuple[int, int]] = []

    def register(self, hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
        self.register_calls.append((hwnd, hotkey_id, modifiers, vk))
        return self.register_result

    def unregister(self, hwnd: int, hotkey_id: int) -> bool:
        self.unregister_calls.append((hwnd, hotkey_id))
        return True


class _HotkeyNativeFilter(QAbstractNativeEventFilter):
    """앱 전역 네이티브 이벤트 필터 — Qt 이벤트 디스패처가 꺼내는 **모든** 스레드
    메시지에 대해 호출되므로 WM_HOTKEY 수신이 보장된다. (최초 구현은 WA_DontShowOnScreen
    숨김 QWidget의 nativeEvent였는데, 실기기 검증에서 WM_HOTKEY가 한 번도 도달하지
    않았다 — 등록은 성공하는데 미표시 위젯의 창 메시지 경로가 발화를 전달하지 못함.
    스레드 바인딩 등록(hwnd=NULL) + 전역 필터가 정석 레시피다.)"""

    def __init__(self, owner: GlobalHotkeySentinel) -> None:
        super().__init__()
        self._owner = owner

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt 오버라이드 시그니처
        try:
            msg = wintypes.MSG.from_address(int(message))
        except Exception:  # pragma: no cover - 플랫폼별 message 표현 차이 방어
            return False, 0
        if msg.message == WM_HOTKEY and int(msg.wParam) == _HOTKEY_ID and self._owner.is_registered:
            logger.info("quick input hotkey: WM_HOTKEY 수신")
            self._owner.activated.emit()
        return False, 0


class GlobalHotkeySentinel(QObject):
    """단축키 등록 상태를 소유하고 WM_HOTKEY 수신 시 `activated`를 발화한다.
    등록은 hwnd=NULL(현재 스레드 큐 바인딩)로 하고, 수신은 앱 전역 네이티브 이벤트
    필터가 담당한다 — 창 핸들에 의존하지 않으므로 메인 창 재생성(핀 모드 등)과 무관."""

    activated = Signal()

    def __init__(self, backend: HotkeyBackend) -> None:
        super().__init__()
        self.backend = backend
        self._registered = False
        self._filter = _HotkeyNativeFilter(self)
        app = QCoreApplication.instance()
        if app is not None:
            app.installNativeEventFilter(self._filter)

    @property
    def is_registered(self) -> bool:
        return self._registered

    def register(self, modifiers: int, vk: int) -> bool:
        """이미 등록된 상태면 먼저 해제한 뒤 새 조합으로 등록한다. hwnd=0(스레드 바인딩)."""
        if self._registered:
            self.unregister()
        ok = self.backend.register(0, _HOTKEY_ID, modifiers, vk)
        self._registered = ok
        return ok

    def unregister(self) -> None:
        if not self._registered:
            return
        self.backend.unregister(0, _HOTKEY_ID)
        self._registered = False


class GlobalHotkeyController:
    """config(quick_hotkey_enabled/quick_hotkey)를 읽어 등록/해제/재등록을
    오케스트레이션한다. 재시도 루프 없음(스펙 U1/Q3-3) — 등록 실패는 트레이 풍선
    1회 고지 후 그대로 둔다. 사용자가 설정에서 다시 시도(토글 또는 리셋)하면 그때
    한 번 더 시도한다."""

    def __init__(self, app, backend: HotkeyBackend | None = None) -> None:
        self.app = app
        self.backend = backend or Win32HotkeyBackend()
        self._sentinel: GlobalHotkeySentinel | None = None
        self.registered = False

    def attach(self) -> None:
        """앱 시작 시 1회 호출: 센티널을 만들고, 설정이 활성화면 등록을 시도한다."""
        if self._sentinel is None:
            self._sentinel = GlobalHotkeySentinel(self.backend)
            self._sentinel.activated.connect(self._on_activated)
        if self.app.store.get("quick_hotkey_enabled", True):
            self._register_from_config()

    def reregister(self) -> bool:
        """설정 변경(활성화 토글/조합 리셋) 후 재등록한다. attach() 전에 불려도
        안전하게 센티널을 만든다."""
        if self._sentinel is None:
            self.attach()
            return self.registered
        self._sentinel.unregister()
        self.registered = False
        if self.app.store.get("quick_hotkey_enabled", True):
            return self._register_from_config()
        return True

    def detach(self) -> None:
        """앱 종료 시 보장 해제(aboutToQuit 경유). 등록 안 된 상태면 no-op."""
        if self._sentinel is not None:
            self._sentinel.unregister()
        self.registered = False

    def _register_from_config(self) -> bool:
        text = self.app.store.get("quick_hotkey", DEFAULT_QUICK_HOTKEY)
        parsed = parse_hotkey_string(text) or parse_hotkey_string(DEFAULT_QUICK_HOTKEY)
        assert parsed is not None  # DEFAULT_QUICK_HOTKEY는 항상 파싱 가능
        modifiers, vk = parsed
        ok = self._sentinel.register(modifiers, vk)
        self.registered = ok
        if not ok:
            self._notify_registration_failed()
        return ok

    def _on_activated(self) -> None:
        """U1: 핫키 처리 중에는 OS가 포그라운드 전환을 허용하므로, 그 핸들러에서
        동기적으로 입력바를 열고 activate까지 끝낸다(open_quick_input이 이미 수행)."""
        logger.info("quick input hotkey: 입력바 열기")
        self.app.window_manager.open_quick_input()

    def _notify_registration_failed(self) -> None:
        tray = getattr(self.app, "tray", None)
        if tray is None:
            return
        tray.showMessage(
            self._tr("quick.hotkey.balloon_title", "빠른 입력 단축키"),
            self._tr(
                "quick.hotkey.register_failed",
                "단축키가 다른 프로그램에서 이미 사용 중이라 등록하지 못했습니다. 설정 > 프로그램에서 바꿀 수 있어요.",
            ),
            msecs=5000,
        )

    def _tr(self, key: str, fallback: str) -> str:
        tr = getattr(self.app, "tr", None)
        if callable(tr):
            return tr(key, fallback)
        return translate(self.app.store.get("language", "ko"), key, fallback)
