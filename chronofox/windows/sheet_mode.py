"""시트 모드(바탕화면 핀) Qt 통합부 — P2 + P3.

설계 근거: `planning/specs/sheet-mode-v1.md` D2·D3·D5·D6·D7·D9·D11·D16, §2(상태 전이표).
판정 로직은 전부 `chronofox.core.app_desktop_pin`(Qt-free)에 있다 — 이 모듈은 그 판정을
실 win32 호출(ctypes)과 Qt 객체(QTimer/QWidget/신호)에 연결하는 얇은 오케스트레이션만
담당한다. **판정 로직을 재구현하지 않는다** — 새 win32 호출이 필요하면 여기(win32 계층)에
추가하고, 상태·판정 자체는 app_desktop_pin에만 산다.

구성:
  - `RealWin32Desktop`: `Win32Desktop` 프로토콜(+ Qt 통합에 필요한 추가 메서드)의 ctypes
    실구현. `planning/spikes/workerw_spike.py`의 검증된 호출 패턴을 그대로 옮긴다.
    P3에서 WH_MOUSE_LL 훅 설치/해제 + 더블클릭 시스템 값(GetDoubleClickTime 등)도 추가됐다.
  - `SheetInputHook`: D9/D16 더블클릭 입력 훅의 Qt 통합부. 콜백 본문은 판정(core 순수
    함수 재사용)만 하고, 성공 시 `double_click_detected` 시그널로 메인 스레드에 넘긴다.
  - `SheetSentinel`: 숨김 네이티브 창. 2초 가디언 폴링 + `TaskbarCreated` 브로드캐스트 +
    `WM_QUERYENDSESSION`/`WM_ENDSESSION` 수신을 담당한다. 절대 WorkerW에 붙지 않는다
    (메인 창의 파괴 연쇄 밖에 있어야 한다 — D5).
  - `SheetModeController`: 상태 전이표(§2)의 각 액션 이름을 1:1 메서드로 구현하고,
    `chronofox.core.app_desktop_pin.transition()`이 반환한 액션 목록을 순서대로 실행한다.
    P3에서 모든 전이 종료 지점에 `_sync_input_hook()`을 붙여 SHEET(비투과)에서만
    입력 훅이 설치되도록 한다(D6 — 투과와 입력은 상호 배타).
  - `AttachFailedError`: 부착 파이프라인(locate/attach/convert) 중 하나가 실패했을 때
    ENTER_SHEET/GUARDIAN_RECOVER 경로에서 D14 폴백으로 전환시키는 내부 신호.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import logging
from collections.abc import Callable, Sequence

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QWidget

from chronofox.core.app_desktop_pin import (
    ClickRecord,
    Geometry,
    GuardianVerdict,
    Rect,
    SheetEvent,
    SheetState,
    WindowRecord,
    clamp_geometry_to_monitors,
    discover_workerw_target,
    guardian_verdict,
    is_double_click,
    point_in_rect,
    screen_point_to_local,
    screen_to_workerw_local,
    should_ignore_drag,
    transition,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------
# Win32 상수 (planning/spikes/workerw_spike.py와 동일 — 스파이크에서 실측 검증됨)
# --------------------------------------------------------------------------
WM_SPAWN_WORKERW = 0x052C
SMTO_NORMAL = 0x0000

GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CHILD = 0x40000000
WS_POPUP = 0x80000000

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016

LWA_ALPHA = 0x0002

# D9/D16 입력 훅(WH_MOUSE_LL) 상수 — planning/spikes/input_spike.py의 실측 확정안(ⓑ).
WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
HC_ACTION = 0
SM_CXDOUBLECLK = 36
SM_CYDOUBLECLK = 37

_user32 = None
_WNDENUMPROC = None
_HOOKPROC = None
_kernel32 = None


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    """MSDN MSLLHOOKSTRUCT — WH_MOUSE_LL 콜백의 lParam이 가리키는 구조체."""

    _fields_ = [
        ("pt", _POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


def _ensure_ctypes_ready() -> None:
    """user32 ctypes 함수 시그니처를 지연 초기화한다(모듈 import 시점이 아니라 최초
    RealWin32Desktop 생성 시점에 — non-Windows 환경에서의 import 실패를 피하기 위함)."""
    global _user32, _WNDENUMPROC, _HOOKPROC, _kernel32
    if _user32 is not None:
        return
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]

    user32.FindWindowExW.restype = wintypes.HWND
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]

    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_ssize_t),
    ]

    wndenumproc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [wndenumproc, wintypes.LPARAM]

    user32.SetParent.restype = wintypes.HWND
    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]

    user32.GetParent.restype = wintypes.HWND
    user32.GetParent.argtypes = [wintypes.HWND]

    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]

    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, wintypes.UINT,
    ]

    user32.RegisterWindowMessageW.restype = wintypes.UINT
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]

    if hasattr(user32, "GetWindowLongPtrW"):
        get_long = user32.GetWindowLongPtrW
        set_long = user32.SetWindowLongPtrW
    else:  # pragma: no cover - 32비트 빌드 폴백, 이 프로젝트 타깃 밖
        get_long = user32.GetWindowLongW
        set_long = user32.SetWindowLongW
    get_long.restype = ctypes.c_ssize_t
    get_long.argtypes = [wintypes.HWND, ctypes.c_int]
    set_long.restype = ctypes.c_ssize_t
    set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32._cf_get_long = get_long  # type: ignore[attr-defined]
    user32._cf_set_long = set_long  # type: ignore[attr-defined]

    # D9/D16 입력 훅 — WH_MOUSE_LL 설치/해제 + 더블클릭 판정에 필요한 시스템 값.
    hookproc = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
    user32.SetWindowsHookExW.restype = wintypes.HHOOK
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, hookproc, wintypes.HINSTANCE, wintypes.DWORD]

    user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]

    user32.GetDoubleClickTime.restype = wintypes.UINT
    user32.GetDoubleClickTime.argtypes = []

    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]

    # D8 개정: 시트 투명도는 균일 알파(SetLayeredWindowAttributes) — Qt 퍼픽셀 알파는
    # WS_CHILD에서 렌더링이 통째로 무효화되므로 쓸 수 없다(2026-07-18 실기기 발견).
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL
    user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD,
    ]

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]

    _user32 = user32
    _WNDENUMPROC = wndenumproc
    _HOOKPROC = hookproc
    _kernel32 = kernel32


class RealWin32Desktop:
    """`Win32Desktop` 프로토콜(D3 탐색용) + Qt 통합에 필요한 추가 메서드(attach/detach/
    좌표 배치/투과/세션 메시지 등록)의 ctypes 실구현. 스파이크에서 실측 검증된 호출
    패턴을 그대로 옮겼다 — 판정 로직은 없다(단순 win32 API 래퍼)."""

    def __init__(self) -> None:
        _ensure_ctypes_ready()
        self._user32 = _user32
        self._mouse_hook_proc_ref = None  # D16: ctypes 콜백 GC 방지용 보관

    # ---- Win32Desktop 프로토콜 (D3 탐색) ---------------------------------
    def find_progman(self) -> int:
        return int(self._user32.FindWindowW("Progman", None) or 0)

    def spawn_workerw(self, progman_hwnd: int) -> None:
        result = ctypes.c_ssize_t(0)
        self._user32.SendMessageTimeoutW(
            wintypes.HWND(progman_hwnd), WM_SPAWN_WORKERW, 0, 0,
            SMTO_NORMAL, 1000, ctypes.byref(result),
        )

    def enum_workerw(self) -> Sequence[WindowRecord]:
        records: list[WindowRecord] = []
        user32 = self._user32

        @_WNDENUMPROC
        def enum_proc(hwnd: int, _lparam: int) -> bool:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(wintypes.HWND(hwnd), buf, 256)
            defview = user32.FindWindowExW(wintypes.HWND(hwnd), None, "SHELLDLL_DefView", None)
            records.append(WindowRecord(hwnd=hwnd, class_name=buf.value, hosts_defview=bool(defview)))
            return True

        user32.EnumWindows(enum_proc, 0)
        return records

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindow(wintypes.HWND(hwnd)))

    def get_parent(self, hwnd: int) -> int:
        return int(self._user32.GetParent(wintypes.HWND(hwnd)) or 0)

    def get_window_rect(self, hwnd: int) -> Rect | None:
        rect = wintypes.RECT()
        if self._user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            return (rect.left, rect.top, rect.right, rect.bottom)
        return None

    # ---- Qt 통합 확장 (attach/detach/배치/투과/세션 메시지) ------------------
    def _get_long(self, hwnd: int, index: int) -> int:
        return self._user32._cf_get_long(wintypes.HWND(hwnd), index)

    def _set_long(self, hwnd: int, index: int, value: int) -> int:
        return self._user32._cf_set_long(wintypes.HWND(hwnd), index, value)

    def attach_child(self, hwnd: int, parent_hwnd: int) -> int:
        """SetParent + WS_CHILD 적용(WS_POPUP 제거) + SWP_FRAMECHANGED (스파이크 Phase A).
        복원용 원래 GWL_STYLE 값을 반환한다."""
        original_style = self._get_long(hwnd, GWL_STYLE)
        self._user32.SetParent(wintypes.HWND(hwnd), wintypes.HWND(parent_hwnd))
        new_style = (original_style | WS_CHILD) & ~WS_POPUP
        self._set_long(hwnd, GWL_STYLE, new_style)
        self._user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        return original_style

    def detach_child(self, hwnd: int, original_style: int) -> None:
        """attach_child의 역순 복원(스파이크 Phase A cleanup과 동일 절차)."""
        self._set_long(hwnd, GWL_STYLE, original_style)
        self._user32.SetParent(wintypes.HWND(hwnd), None)
        self._user32.SetWindowPos(
            wintypes.HWND(hwnd), None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )

    def set_window_pos_local(self, hwnd: int, x: int, y: int, width: int, height: int) -> None:
        """WorkerW 로컬 좌표로 배치한다(D4 — 화면 좌표는 여기 들어오지 않는다, 호출부가
        이미 screen_to_workerw_local로 변환을 마친 값만 넘겨야 한다)."""
        self._user32.SetWindowPos(
            wintypes.HWND(hwnd), None, x, y, width, height,
            SWP_NOZORDER | SWP_NOACTIVATE,
        )

    def set_passthrough(self, hwnd: int, enabled: bool) -> None:
        """WS_EX_LAYERED|WS_EX_TRANSPARENT 비트 적용/해제(스파이크 Phase B). LAYERED
        비트는 해제 시 건드리지 않는다 — WA_TranslucentBackground가 이미 그 비트를
        필요로 하므로(Qt 자체의 반투명 배경 처리와 충돌 방지)."""
        ex_style = self._get_long(hwnd, GWL_EXSTYLE)
        new_style = ex_style | WS_EX_LAYERED | WS_EX_TRANSPARENT if enabled else ex_style & ~WS_EX_TRANSPARENT
        self._set_long(hwnd, GWL_EXSTYLE, new_style)

    def set_round_region(self, hwnd: int, width: int, height: int, radius_px: int) -> None:
        """D8 개정: 불투명 시트의 모서리 라운드는 알파가 아니라 창 리전으로 깎는다.
        SetWindowRgn은 리전 소유권을 OS에 넘기므로 DeleteObject를 호출하지 않는다."""
        gdi32 = ctypes.windll.gdi32  # type: ignore[attr-defined]
        gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, radius_px * 2, radius_px * 2)
        self._user32.SetWindowRgn.restype = ctypes.c_int
        self._user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        self._user32.SetWindowRgn(wintypes.HWND(hwnd), region, True)

    def clear_region(self, hwnd: int) -> None:
        self._user32.SetWindowRgn.restype = ctypes.c_int
        self._user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        self._user32.SetWindowRgn(wintypes.HWND(hwnd), None, True)

    def set_uniform_alpha(self, hwnd: int, percent: int) -> None:
        """D8 개정: 창 전체 균일 알파(글자 포함). WS_EX_LAYERED 보장 후
        SetLayeredWindowAttributes(LWA_ALPHA). 레이어드 자식 창은 Win8+에서 지원 —
        같은 WorkerW의 Wallpaper Engine 자식들이 동작 증거다."""
        ex_style = self._get_long(hwnd, GWL_EXSTYLE)
        if not (ex_style & WS_EX_LAYERED):
            self._set_long(hwnd, GWL_EXSTYLE, ex_style | WS_EX_LAYERED)
        alpha = max(0, min(255, round(255 * percent / 100)))
        self._user32.SetLayeredWindowAttributes(wintypes.HWND(hwnd), 0, alpha, LWA_ALPHA)

    def register_window_message(self, name: str) -> int:
        return int(self._user32.RegisterWindowMessageW(name))

    # ---- D9/D16 입력 훅 (WH_MOUSE_LL) ---------------------------------------
    def install_mouse_hook(self, on_left_button_down: Callable[[int, int, int], None]) -> int:
        """WH_MOUSE_LL 전역 훅을 설치한다. HC_ACTION의 WM_LBUTTONDOWN마다
        `on_left_button_down(screen_x, screen_y, tick_time_ms)`를 호출하고, 콜백
        예외 여부와 무관하게 항상 CallNextHookEx로 체인을 이어준다(훅 체인을 끊지
        않기 위한 방어). ctypes 콜백 객체 참조를 인스턴스에 보관해 GC 함정을 피한다
        (D16 구현 규칙)."""

        def _raw_proc(n_code: int, w_param: int, l_param: int) -> int:
            if n_code == HC_ACTION and w_param == WM_LBUTTONDOWN:
                try:
                    info = ctypes.cast(l_param, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
                    on_left_button_down(info.pt.x, info.pt.y, info.time)
                except Exception:  # pragma: no cover - 콜백 예외로 훅 체인이 끊기면 안 됨
                    logger.exception("sheet mode: mouse hook 콜백 실패")
            return self._user32.CallNextHookEx(None, n_code, w_param, l_param)

        self._mouse_hook_proc_ref = _HOOKPROC(_raw_proc)
        module_handle = _kernel32.GetModuleHandleW(None)
        handle = self._user32.SetWindowsHookExW(WH_MOUSE_LL, self._mouse_hook_proc_ref, module_handle, 0)
        if not handle:
            self._mouse_hook_proc_ref = None
        return int(handle or 0)

    def uninstall_mouse_hook(self, handle: int) -> bool:
        """UnhookWindowsHookEx 반환값을 그대로 전달한다(호출부가 로그로 확인·검증)."""
        if not handle:
            return True
        result = bool(self._user32.UnhookWindowsHookEx(handle))
        self._mouse_hook_proc_ref = None
        return result

    def get_double_click_time_ms(self) -> int:
        """GetDoubleClickTime() — D16 구현 규칙: 더블클릭 간격은 이 시스템 값을 쓴다."""
        return int(self._user32.GetDoubleClickTime())

    def get_double_click_radius_px(self) -> int:
        """GetSystemMetrics(SM_CXDOUBLECLK/CYDOUBLECLK) 기반 반경(전체 폭/높이의 절반)."""
        cx = self._user32.GetSystemMetrics(SM_CXDOUBLECLK)
        cy = self._user32.GetSystemMetrics(SM_CYDOUBLECLK)
        if not cx or not cy:
            return 4
        return max(1, min(cx, cy) // 2)


# --------------------------------------------------------------------------
# 가디언 실패 신호
# --------------------------------------------------------------------------


class AttachFailedError(RuntimeError):
    """WorkerW 탐색/SetParent/좌표 변환 파이프라인 중 하나가 실패했을 때 발생한다.
    ENTER_SHEET 경로에서는 ENTER_SHEET_FAILED로, GUARDIAN_RECOVER 경로에서는
    GUARDIAN_FALLBACK으로 전환하는 신호로 쓰인다(D14 폴백 불변식)."""


# --------------------------------------------------------------------------
# 입력 훅 (D9/D16) — WH_MOUSE_LL 기반 더블클릭 감지
# --------------------------------------------------------------------------


class SheetInputHook(QObject):
    """D16(P0에서 확정: ⓑ WH_MOUSE_LL 훅)의 Qt 통합부. 실제 ctypes 설치/해제는
    `win32.install_mouse_hook()`/`uninstall_mouse_hook()`(RealWin32Desktop 실구현, 테스트는
    FakeWin32Ext 확장)에 위임한다. 여기서는 더블클릭 판정(`app_desktop_pin.is_double_click`
    재사용)과 시트 사각형 히트(`point_in_rect`)만 한다 — 훅 콜백 본문을 최소로 유지하라는
    D16 요구사항 그대로다. 판정에 성공하면 `double_click_detected`를 emit해 메인 스레드로
    넘긴다(콜백 안에서 직접 UI를 만지지 않는다 — 연결부는 SheetModeController가
    Qt.QueuedConnection으로 맺는다)."""

    double_click_detected = Signal(int, int)  # 화면 좌표 (x, y)

    def __init__(self, win32, get_main_hwnd: Callable[[], int | None]) -> None:
        super().__init__()
        self._win32 = win32
        self._get_main_hwnd = get_main_hwnd
        self._hook_handle: int | None = None
        self._prev_click: ClickRecord | None = None

    def is_installed(self) -> bool:
        return self._hook_handle is not None

    def install(self) -> None:
        """SHEET(비투과) 진입 시 호출된다. 이미 설치돼 있으면 아무것도 하지 않는다
        (idempotent — SHEET를 유지하는 연속 전이가 훅을 중복 설치하지 않는다)."""
        if self.is_installed():
            return
        self._prev_click = None
        handle = self._win32.install_mouse_hook(self._on_left_button_down)
        if not handle:
            logger.warning("sheet mode: WH_MOUSE_LL 훅 설치 실패 — 더블클릭 입력 비활성")
            return
        self._hook_handle = handle
        logger.debug("sheet mode: 입력 훅 설치됨 (handle=%s)", handle)

    def uninstall(self) -> None:
        """EXIT/PASSTHROUGH 전환·detach(종료 포함) 시 즉시 해제한다(D16 구현 규칙)."""
        if not self.is_installed():
            return
        handle = self._hook_handle
        self._hook_handle = None
        self._prev_click = None
        ok = self._win32.uninstall_mouse_hook(handle)
        logger.debug("sheet mode: 입력 훅 해제됨 (handle=%s, ok=%s)", handle, ok)

    # ---- 훅 콜백 (최소 본문 — 더블클릭 판정 + 시트 사각형 히트만) --------------
    def _on_left_button_down(self, x: int, y: int, time_ms: int) -> None:
        hwnd = self._get_main_hwnd()
        if hwnd is None:
            return
        rect = self._win32.get_window_rect(hwnd)
        if rect is None or not point_in_rect(x, y, rect):
            return
        click = ClickRecord(x=x, y=y, timestamp_ms=time_ms)
        doubled = is_double_click(
            self._prev_click,
            click,
            interval_ms=self._win32.get_double_click_time_ms(),
            radius_px=self._win32.get_double_click_radius_px(),
        )
        if doubled:
            self._prev_click = None
            self.double_click_detected.emit(x, y)
        else:
            self._prev_click = click


# --------------------------------------------------------------------------
# 센티널 (D5) — 파괴 연쇄 밖의 숨김 네이티브 창
# --------------------------------------------------------------------------


class SheetSentinel(QWidget):
    """숨김 네이티브 창. 2초 가디언 폴링(QTimer) + TaskbarCreated 브로드캐스트 +
    WM_QUERYENDSESSION/WM_ENDSESSION 수신을 담당한다. **절대 WorkerW에 SetParent되지
    않는다** — 메인 창(WorkerW 자식)이 explorer 재시작으로 파괴돼도 이 창은 살아남아야
    감시자 역할을 할 수 있다(D5)."""

    def __init__(self, controller: SheetModeController) -> None:
        super().__init__()
        self._controller = controller
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DontShowOnScreen, True)
        self.resize(1, 1)
        self.move(-32000, -32000)
        self._taskbar_created_msg = 0
        try:
            self._taskbar_created_msg = controller.win32.register_window_message("TaskbarCreated")
        except Exception:  # pragma: no cover - 방어적: 등록 실패해도 가디언 폴링은 계속 동작
            logger.exception("sheet mode: TaskbarCreated 메시지 등록 실패")

    def nativeEvent(self, event_type, message):  # noqa: N802 - Qt 오버라이드 시그니처
        try:
            msg = wintypes.MSG.from_address(int(message))
            win_message = msg.message
        except Exception:  # pragma: no cover - 플랫폼별 message 표현 차이 방어
            return super().nativeEvent(event_type, message)

        if self._taskbar_created_msg and win_message == self._taskbar_created_msg:
            self._controller.handle_taskbar_created()
        elif win_message in (WM_QUERYENDSESSION, WM_ENDSESSION):
            self._controller.handle_session_ending()
        return super().nativeEvent(event_type, message)


# --------------------------------------------------------------------------
# SheetModeController (§2 상태 전이표의 Qt 통합 실행부)
# --------------------------------------------------------------------------


class SheetModeController(QObject):
    """§2 상태 전이표를 실행한다. 판정(다음 상태·액션 목록)은 전부
    `chronofox.core.app_desktop_pin.transition()`이 내리고, 이 클래스는 액션 이름
    문자열을 1:1 메서드(`_<action>`)에 매핑해 순서대로 실행할 뿐이다."""

    def __init__(
        self,
        window: QWidget,
        win32,
        *,
        get_config: Callable[[str, object], object] | None = None,
        set_config: Callable[[str, object], None] | None = None,
        save_config: Callable[[], None] | None = None,
        notify_fallback: Callable[[], None] | None = None,
        on_session_ending: Callable[[], None] | None = None,
        on_cell_double_click: Callable[[object], None] | None = None,
        guardian_interval_ms: int = 2000,
    ) -> None:
        super().__init__()
        self._window = window
        self.win32 = win32
        self._config_get = get_config or (lambda _key, default: default)
        self._config_set = set_config or (lambda _key, _value: None)
        self._config_save = save_config or (lambda: None)
        self._notify_fallback = notify_fallback or (lambda: None)
        self._on_session_ending = on_session_ending or (lambda: None)
        self._on_cell_double_click = on_cell_double_click

        self.state = SheetState.NORMAL
        self._target_state = SheetState.NORMAL
        self._main_hwnd: int | None = None
        self._workerw_hwnd: int | None = None
        self._original_style: int | None = None
        self._pre_sheet_geometry: Geometry | None = None
        self._current_screen_geometry: Geometry | None = None
        self._retry_count = 0
        self._sentinel: SheetSentinel | None = None

        self._guardian_timer = QTimer(self)
        self._guardian_timer.setInterval(guardian_interval_ms)
        self._guardian_timer.timeout.connect(self._on_guardian_tick)

        # D9/D16: 더블클릭 입력 훅 — SHEET(비투과)에서만 설치된다(_sync_input_hook,
        # _run_transition의 모든 종료 지점에서 호출). 콜백은 QueuedConnection으로 메인
        # 스레드 이벤트 루프에 넘겨받는다(훅 콜백 스택 안에서 직접 UI를 만지지 않는다).
        self.input_hook = SheetInputHook(win32, lambda: self._main_hwnd)
        self.input_hook.double_click_detected.connect(self._on_sheet_double_click, Qt.QueuedConnection)

    # ---- 공개 API ---------------------------------------------------------
    def enter_sheet(self) -> bool:
        """NORMAL -> SHEET. 이미 SHEET/PASSTHROUGH면 아무것도 하지 않고 True를 반환한다.
        실패 시 D14 폴백(NORMAL 유지, config 미변경)하고 False를 반환한다."""
        if self.state is not SheetState.NORMAL:
            return True
        return self._run_transition(SheetEvent.ENTER_SHEET, on_failure=SheetEvent.ENTER_SHEET_FAILED)

    def exit_sheet(self) -> None:
        """SHEET/PASSTHROUGH -> NORMAL. PASSTHROUGH에서 호출되면 전이표에 직행이
        없으므로 DISABLE_PASSTHROUGH -> EXIT_SHEET 순서로 합성한다."""
        if self.state is SheetState.SHEET_PASSTHROUGH:
            self._run_transition(SheetEvent.DISABLE_PASSTHROUGH)
        if self.state is SheetState.SHEET:
            self._run_transition(SheetEvent.EXIT_SHEET)

    def detach_for_exit(self) -> None:
        """D11 종료 경로 전용: 물리 detach만 수행하고 config(sheet_mode·
        sheet_click_through)는 보존한다. exit_sheet()를 그대로 쓰면 save_config 액션이
        sheet_mode=False를 영속시켜 S2(시트 상태로 재시작 -> 시트 복귀)가 깨진다 —
        종료는 사용자의 모드 선택이 아니다."""
        skip = frozenset({"save_config"})
        if self.state is SheetState.SHEET_PASSTHROUGH:
            self._run_transition(SheetEvent.DISABLE_PASSTHROUGH, skip_actions=skip)
        if self.state is SheetState.SHEET:
            self._run_transition(SheetEvent.EXIT_SHEET, skip_actions=skip)

    def set_passthrough(self, enabled: bool) -> None:
        """SHEET <-> SHEET_PASSTHROUGH 토글. NORMAL에서 호출되면 아무것도 하지 않는다
        (D6 — 투과는 항상 SHEET를 거친다, 직행 없음)."""
        if enabled and self.state is SheetState.SHEET:
            self._run_transition(SheetEvent.ENABLE_PASSTHROUGH)
        elif not enabled and self.state is SheetState.SHEET_PASSTHROUGH:
            self._run_transition(SheetEvent.DISABLE_PASSTHROUGH)

    def should_ignore_drag(self) -> bool:
        """D7: SHEET 계열에서 드래그 이동/리사이즈를 막을지 판정한다(순수 로직 재사용)."""
        return should_ignore_drag(self.state)

    def should_block_external_geometry(self) -> bool:
        """D4: SHEET 계열 동안 컨트롤러가 아닌 다른 경로의 지오메트리 쓰기를 막을지
        판정한다(should_ignore_drag와 동일 조건 — NORMAL이 아니면 차단)."""
        return should_ignore_drag(self.state)

    def handle_display_changed(self) -> None:
        """화면 구성/DPI 변경 시그널 핸들러(§2: "화면 구성 변경 시그널" 행)."""
        if self.state is SheetState.NORMAL:
            return
        if self._workerw_hwnd is None or self.win32.get_window_rect(self._workerw_hwnd) is None:
            self._on_guardian_tick()
            return
        self._run_transition(SheetEvent.DISPLAY_CHANGED)

    def handle_taskbar_created(self) -> None:
        """explorer 재시작의 조기 신호(TaskbarCreated 브로드캐스트) — 다음 2초 폴링을
        기다리지 않고 즉시 가디언 판정을 재실행한다."""
        if self.state is SheetState.NORMAL:
            return
        self._on_guardian_tick()

    def handle_session_ending(self) -> None:
        """WM_QUERYENDSESSION/WM_ENDSESSION 수신 — WS_CHILD는 이 메시지를 못 받으므로
        센티널이 대신 수신해 즉시 detach + 데이터 flush를 트리거한다(D11).
        OS 종료도 사용자의 모드 선택이 아니므로 detach_for_exit(설정 보존)를 쓴다."""
        if self.state is not SheetState.NORMAL:
            self.detach_for_exit()
        self._on_session_ending()

    # ---- 전이 실행 ---------------------------------------------------------
    def _run_transition(
        self,
        event: SheetEvent,
        *,
        on_failure: SheetEvent | None = None,
        skip_actions: frozenset[str] = frozenset(),
    ) -> bool:
        next_state, actions = transition(self.state, event)
        self._target_state = next_state
        try:
            for action in actions:
                if action in skip_actions:
                    continue
                getattr(self, f"_{action}")()
        except AttachFailedError:
            if on_failure is None:
                raise
            fallback_state, fallback_actions = transition(self.state, on_failure)
            self._target_state = fallback_state
            for action in fallback_actions:
                getattr(self, f"_{action}")()
            self.state = fallback_state
            self._sync_input_hook()
            return False
        self.state = next_state
        self._sync_input_hook()
        return True

    # ---- 입력 훅 동기화 (D9/D16) --------------------------------------------
    def _sync_input_hook(self) -> None:
        """더블클릭 입력 훅은 SHEET(비투과)에서만 설치된다 — PASSTHROUGH·NORMAL로
        전환되면 즉시 해제한다(D6: 투과와 입력은 상호 배타). 모든 전이가
        `_run_transition`을 거치므로 여기 한 곳에서 동기화하면 충분하다."""
        if self.state is SheetState.SHEET:
            self.input_hook.install()
        else:
            self.input_hook.uninstall()

    def _on_sheet_double_click(self, screen_x: int, screen_y: int) -> None:
        """`SheetInputHook.double_click_detected`의 메인 스레드 핸들러(QueuedConnection).

        화면 좌표를 창 로컬로 변환(win32 GetWindowRect(main_hwnd) 기준, D9 항목3 —
        WS_CHILD에서 Qt mapFromGlobal은 신뢰 불가)한 뒤 `childAt()`으로 위젯을 특정해
        앱이 넘겨준 콜백에 전달한다. 어떤 위젯이 "DayCell"인지는 이 모듈이 모른다 —
        판정은 콜백을 넘긴 쪽(FoxCalendarApp) 책임이다."""
        if self.state is not SheetState.SHEET or self._main_hwnd is None:
            return
        rect = self.win32.get_window_rect(self._main_hwnd)
        if rect is None:
            return
        local_x, local_y = screen_point_to_local(screen_x, screen_y, rect)
        widget = self._window.childAt(local_x, local_y)
        if widget is not None and self._on_cell_double_click is not None:
            self._on_cell_double_click(widget)

    # ---- 가디언 ------------------------------------------------------------
    def _on_guardian_tick(self) -> None:
        if self.state is SheetState.NORMAL:
            return
        is_workerw_valid = self._workerw_hwnd is not None and self.win32.is_window(self._workerw_hwnd)
        is_main_valid = self._main_hwnd is not None and self.win32.is_window(self._main_hwnd)
        parent_hwnd = self.win32.get_parent(self._main_hwnd) if is_main_valid and self._main_hwnd else None
        verdict = guardian_verdict(
            is_workerw_valid=is_workerw_valid,
            is_main_hwnd_valid=is_main_valid,
            parent_hwnd=parent_hwnd,
            workerw_hwnd=self._workerw_hwnd,
            retry_count=self._retry_count,
        )
        self._handle_guardian_verdict(verdict)

    def _handle_guardian_verdict(self, verdict: GuardianVerdict) -> None:
        if verdict is GuardianVerdict.OK:
            self._retry_count = 0
            return
        if verdict is GuardianVerdict.FALLBACK:
            self._retry_count = 0
            self._run_transition(SheetEvent.GUARDIAN_FALLBACK)
            return
        self._retry_count += 1
        if verdict is GuardianVerdict.RECREATE:
            self._recreate_main_handle()
        try:
            self._run_transition(SheetEvent.GUARDIAN_RECOVER)
        except AttachFailedError:
            self._run_transition(SheetEvent.GUARDIAN_FALLBACK)

    def _recreate_main_handle(self) -> None:
        """D5: explorer 재시작의 파괴 연쇄로 메인 창의 네이티브 핸들이 죽었을 때, Qt
        위젯의 네이티브 핸들을 재생성한다(setParent(None) 왕복)."""
        window = self._window
        window.setParent(None)
        window.winId()
        self._main_hwnd = int(window.winId())

    # ---- 액션 (전이표 §2의 각 액션 문자열과 1:1 대응) -------------------------
    def _remember_geometry(self) -> None:
        g = self._window.geometry()
        self._pre_sheet_geometry = (g.x(), g.y(), g.width(), g.height())
        self._current_screen_geometry = self._pre_sheet_geometry

    def _locate_workerw(self) -> None:
        hwnd, strategy = discover_workerw_target(self.win32)
        if hwnd is None:
            raise AttachFailedError("WorkerW 부착 대상을 찾지 못함(D3 ⓒ 완전 부재)")
        self._workerw_hwnd = hwnd
        self._workerw_strategy = strategy

    def _attach_and_restyle(self) -> None:
        window = self._window
        # D8 개정: 반투명(WA_TranslucentBackground) 서피스는 WS_CHILD에서 렌더링이
        # 무효화되므로, 부착 전에 불투명 서피스로 네이티브 창을 재생성한다(훅이 있으면).
        # 재생성으로 hwnd가 바뀌므로 반드시 이 뒤에 winId()를 읽는다.
        surface_hook = getattr(window, "set_sheet_surface", None)
        if callable(surface_hook):
            surface_hook(True)
        window.winId()  # 네이티브 핸들 보장
        hwnd = int(window.winId())
        self._main_hwnd = hwnd
        if self._workerw_hwnd is None:
            raise AttachFailedError("locate_workerw가 먼저 실행되지 않음")
        try:
            self._original_style = self.win32.attach_child(hwnd, self._workerw_hwnd)
        except Exception as exc:  # pragma: no cover - 실 win32 실패는 mock 경계 밖
            raise AttachFailedError(f"SetParent 실패: {exc}") from exc

    def _convert_screen_to_local(self) -> None:
        if self._workerw_hwnd is None or self._main_hwnd is None:
            raise AttachFailedError("attach_and_restyle이 먼저 실행되지 않음")
        rect = self.win32.get_window_rect(self._workerw_hwnd)
        if rect is None:
            raise AttachFailedError("WorkerW GetWindowRect 실패")
        geometry = self._pre_sheet_geometry or self._current_screen_geometry
        if geometry is None:
            g = self._window.geometry()
            geometry = (g.x(), g.y(), g.width(), g.height())
        local = screen_to_workerw_local(geometry, rect)
        self.win32.set_window_pos_local(self._main_hwnd, *local)
        self._current_screen_geometry = geometry

    def _apply_sheet_form(self) -> None:
        """D8 시트 폼 비주얼(그림자/테두리/헤더 숨김 등)은 P3 몫이다. P2는 존재하면
        호출할 훅만 남겨 둔다(없어도 안전한 no-op). D8 개정: 훅 실행 후 균일 알파
        (sheet_opacity)를 win32로 적용한다."""
        hook = getattr(self._window, "apply_sheet_form", None)
        if callable(hook):
            hook()
        # D4/D8 개정: 훅 안의 show()가 Qt의 캐시 지오메트리(화면 좌표)를 그대로 밀어넣어
        # WorkerW 로컬로 오해석된다(샌드박스 실측: +40이 -190으로) — show 후 로컬 좌표를
        # 다시 적용해 배치 주체를 컨트롤러로 되돌린다.
        self._convert_screen_to_local()
        self._apply_sheet_region()
        self._apply_uniform_alpha()

    def _apply_sheet_region(self) -> None:
        """불투명 시트의 모서리 라운드(D8 개정) — 창 리전으로 클리핑. 크기 변경 시마다
        재적용해야 하므로 recalculate 경로에서도 호출된다."""
        if self._main_hwnd is None:
            return
        setter = getattr(self.win32, "set_round_region", None)
        if not callable(setter):
            return
        rect = self.win32.get_window_rect(self._main_hwnd)
        if rect is None:
            return
        width, height = rect[2] - rect[0], rect[3] - rect[1]
        radius = int(getattr(self._window, "radius", 14))
        ratio = getattr(self._window, "devicePixelRatioF", lambda: 1.0)()
        setter(self._main_hwnd, width, height, max(1, round(radius * ratio)))

    def _apply_uniform_alpha(self) -> None:
        if self._main_hwnd is None:
            return
        setter = getattr(self.win32, "set_uniform_alpha", None)
        if not callable(setter):
            return
        try:
            pct = int(self._config_get("sheet_opacity", 45))
        except (TypeError, ValueError):
            pct = 45
        setter(self._main_hwnd, max(0, min(100, pct)))

    def update_opacity(self) -> None:
        """설정 슬라이더 즉시 반영용 공개 API — 시트 계열 상태에서만 재적용한다."""
        if self.state is not SheetState.NORMAL:
            self._apply_uniform_alpha()

    def _start_guardian(self) -> None:
        if self._sentinel is None:
            self._sentinel = SheetSentinel(self)
        self._retry_count = 0
        self._guardian_timer.start()

    def _save_config(self) -> None:
        is_sheet = self._target_state in (SheetState.SHEET, SheetState.SHEET_PASSTHROUGH)
        self._config_set("sheet_mode", is_sheet)
        self._config_set("sheet_click_through", self._target_state is SheetState.SHEET_PASSTHROUGH)
        self._config_save()

    def _show_fallback_notice(self) -> None:
        self._notify_fallback()

    def _stop_guardian(self) -> None:
        self._guardian_timer.stop()

    def _disable_passthrough(self) -> None:
        """EXIT_SHEET는 투과 여부와 무관하게 항상 이 액션을 실행한다(idempotent) —
        SHEET_PASSTHROUGH를 거치지 않고 곧장 SHEET에서 종료해도 안전하다."""
        if self._main_hwnd is not None:
            self.win32.set_passthrough(self._main_hwnd, False)

    def _detach_and_restore_style(self) -> None:
        if self._main_hwnd is not None and self._original_style is not None:
            try:
                self.win32.detach_child(self._main_hwnd, self._original_style)
            except Exception:  # pragma: no cover - D14: detach 실패도 크래시 금지
                logger.exception("sheet mode: detach 실패 — 폴백 절차 계속 진행")
        self._workerw_hwnd = None
        self._original_style = None

    def _restore_screen_geometry(self) -> None:
        geometry = self._current_screen_geometry or self._pre_sheet_geometry
        if geometry is not None:
            QWidget.setGeometry(self._window, *geometry)

    def _restore_chrome(self) -> None:
        hook = getattr(self._window, "restore_sheet_form", None)
        if callable(hook):
            hook()

    def _apply_passthrough_style(self) -> None:
        if self._main_hwnd is not None:
            self.win32.set_passthrough(self._main_hwnd, True)

    def _clear_passthrough_style(self) -> None:
        if self._main_hwnd is not None:
            self.win32.set_passthrough(self._main_hwnd, False)

    def _reattach(self) -> None:
        self._locate_workerw()
        self._attach_and_restyle()
        self._convert_screen_to_local()

    def _recalculate_geometry(self) -> None:
        if self._workerw_hwnd is None or self._main_hwnd is None:
            return
        rect = self.win32.get_window_rect(self._workerw_hwnd)
        if rect is None:
            return  # WorkerW 무효 — 다음 가디언 tick(또는 handle_display_changed의 즉시 판정)이 처리
        base_geometry = self._current_screen_geometry or self._pre_sheet_geometry
        if base_geometry is None:
            return
        monitors, primary = self._current_monitor_rects()
        clamped = clamp_geometry_to_monitors(base_geometry, monitors, primary)
        self._current_screen_geometry = clamped
        local = screen_to_workerw_local(clamped, rect)
        self.win32.set_window_pos_local(self._main_hwnd, *local)
        # 크기가 바뀌었을 수 있으므로 라운드 리전 재적용(D8 개정).
        self._apply_sheet_region()

    def _current_monitor_rects(self) -> tuple[list[Rect], Rect]:
        gui_app = QGuiApplication.instance()
        monitors: list[Rect] = []
        if gui_app is not None:
            for screen in gui_app.screens():
                g = screen.geometry()
                monitors.append((g.x(), g.y(), g.x() + g.width(), g.y() + g.height()))
        primary_screen = QGuiApplication.primaryScreen() if gui_app is not None else None
        if primary_screen is not None:
            g = primary_screen.geometry()
            primary = (g.x(), g.y(), g.x() + g.width(), g.y() + g.height())
        elif monitors:
            primary = monitors[0]
        else:
            primary = (0, 0, 1920, 1080)
        if not monitors:
            monitors = [primary]
        return monitors, primary
