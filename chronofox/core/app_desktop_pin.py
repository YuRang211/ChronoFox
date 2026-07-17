"""시트 모드(바탕화면 핀) 순수 로직 — WorkerW 탐색 판정 · 좌표 변환 · 상태 전이 · 가디언 판정.

설계 근거: `planning/specs/sheet-mode-v1.md` D1~D16, §0(용어/상태), §2(상태 전이표).
이 모듈은 **Qt-free**다 (PySide6 없이 import 가능해야 한다 — Working Rules "신규 로직은
Qt-free 순수 함수로 먼저"). win32 호출은 전부 `Win32Desktop` 프로토콜로 주입받고, 이
파일 자체는 ctypes를 직접 호출하지 않는다 — 실제 ctypes 구현은 P2의 `SheetModeController`
몫이다.

구성:
  - `Win32Desktop` 프로토콜 + `WindowRecord`: P2 실구현과 테스트 FakeWin32가 공유하는
    최소 표면. `planning/spikes/workerw_spike.py`의 `find_workerw()`가 실제로 쓰는 win32
    호출 집합(FindWindowW/SendMessageTimeoutW/EnumWindows/FindWindowExW 등)을 참고해
    "질의 결과를 데이터로 받아 판정만 하는" 형태로 추상화했다.
  - `locate_workerw_target` (D3): WorkerW 탐색 3분기 순수 판정.
  - `screen_to_workerw_local`/`workerw_local_to_screen`/`clamp_geometry_to_monitors` (D4):
    좌표 변환 + 모니터 소실 클램프.
  - `SheetState`/`SheetEvent`/`transition` (§0·§2): 상태 머신. 합법 전이만 허용.
  - `GuardianVerdict`/`guardian_verdict` (D5): 가디언 판정.
  - `SHEET_CONFIG_DEFAULTS`/`apply_sheet_defaults` (D10): config additive 기본값.
  - `should_ignore_drag` (D7): SHEET 계열에서 드래그/리사이즈 무시 판정.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

# --------------------------------------------------------------------------
# Win32Desktop 프로토콜 (D2) — 실 win32 호출은 전부 여기로 주입된다.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowRecord:
    """`enum_workerw()` 원시 질의 한 항목 — EnumWindows가 돌려주는 z-order 순서를
    유지한 채(위→아래), 판정에 필요한 최소 정보만 담는다."""

    hwnd: int
    class_name: str
    hosts_defview: bool  # 이 창이 SHELLDLL_DefView를 직속 자식으로 갖는가 (spike 참고)


class Win32Desktop(Protocol):
    """P2 `SheetModeController`의 실 ctypes 구현과 테스트 `FakeWin32`가 공유하는 최소 표면.
    이 프로토콜 자체는 아무 win32 API도 호출하지 않는다 — 타입 계약일 뿐이다."""

    def find_progman(self) -> int:
        """Progman 톱레벨 창 hwnd를 반환한다(없으면 0)."""
        ...

    def spawn_workerw(self, progman_hwnd: int) -> None:
        """Progman에 WM_SPAWN_WORKERW를 보내 WorkerW 생성을 요청한다(멱등)."""
        ...

    def enum_workerw(self) -> Sequence[WindowRecord]:
        """톱레벨 창을 z-order(위→아래) 순서로 열거해 DefView 소유 창·WorkerW 탐색에
        필요한 원시 질의 결과를 반환한다."""
        ...

    def is_window(self, hwnd: int) -> bool:
        """IsWindow(hwnd) — 핸들이 아직 유효한지."""
        ...

    def get_parent(self, hwnd: int) -> int:
        """GetParent(hwnd) — 없으면 0."""
        ...

    def get_window_rect(self, hwnd: int) -> tuple[int, int, int, int] | None:
        """GetWindowRect(hwnd) — (left, top, right, bottom). 실패 시 None."""
        ...


class WorkerwStrategy(StrEnum):
    """D3 탐색 3분기 중 성공한 두 갈래(ⓐ/ⓑ). 완전 부재(ⓒ)는 strategy=None으로 표현."""

    BEHIND_DEFVIEW = "behind_defview"  # ⓐ DefView 소유 창 뒤 WorkerW
    DIRECT_DEFVIEW = "direct_defview"  # ⓑ DefView 소유 창(Progman 포함) 직접


def locate_workerw_target(
    records: Sequence[WindowRecord],
) -> tuple[int | None, WorkerwStrategy | None]:
    """D3 탐색 판정 — z-order 순서의 원시 질의 결과만으로 부착 대상을 고른다.

    ⓐ DefView를 직속 자식으로 가진 첫 창(defview owner) 바로 뒤에 있는 WorkerW가 있으면
       그 WorkerW를 대상으로 한다(스파이크의 FindWindowExW(None, defview_container,
       "WorkerW", None)와 동일한 의미 — z-order상 defview owner 다음에 오는 WorkerW).
    ⓑ 그런 WorkerW가 없으면(Win11 24H2 등) defview owner 자신(Progman이 직접 호스팅하는
       경우 포함)을 대상으로 한다.
    ⓒ defview owner 자체가 전혀 없으면 (None, None) — 폴백 신호(D14).
    """
    defview_index = -1
    for index, record in enumerate(records):
        if record.hosts_defview:
            defview_index = index
            break

    if defview_index == -1:
        return None, None

    for record in records[defview_index + 1 :]:
        if record.class_name == "WorkerW":
            return record.hwnd, WorkerwStrategy.BEHIND_DEFVIEW

    return records[defview_index].hwnd, WorkerwStrategy.DIRECT_DEFVIEW


def discover_workerw_target(win32: Win32Desktop) -> tuple[int | None, WorkerwStrategy | None]:
    """Win32Desktop을 통해 실제로 탐색을 수행하는 얇은 오케스트레이션.
    판정 로직 자체는 `locate_workerw_target`에 있다(단위 테스트는 그쪽을 직접 부른다)."""
    progman = win32.find_progman()
    if progman:
        win32.spawn_workerw(progman)
    return locate_workerw_target(win32.enum_workerw())


# --------------------------------------------------------------------------
# 좌표 변환 + 모니터 소실 클램프 (D4)
# --------------------------------------------------------------------------

# 창 지오메트리: (x, y, width, height) — Qt geometry 관례.
Geometry = tuple[int, int, int, int]
# 사각형(창/모니터): (left, top, right, bottom) — win32 RECT 관례(GetWindowRect와 동일).
Rect = tuple[int, int, int, int]


def screen_to_workerw_local(geometry: Geometry, workerw_rect: Rect) -> Geometry:
    """화면 좌표 지오메트리를 WorkerW 로컬 좌표로 변환한다(부착 후 배치 시점).

    스파이크 실측: WorkerW 원점은 (0,0)이 아닐 수 있다(이 PC에서 (0,-230)) — 모니터
    배치(위/왼쪽에 다른 모니터가 있으면 가상 데스크톱 원점이 음수가 됨) 때문이다.
    """
    x, y, width, height = geometry
    left, top, _right, _bottom = workerw_rect
    return (x - left, y - top, width, height)


def workerw_local_to_screen(local_geometry: Geometry, workerw_rect: Rect) -> Geometry:
    """WorkerW 로컬 좌표를 화면 좌표로 역변환한다(detach 시 — 화면 좌표로 저장하기 위해)."""
    x, y, width, height = local_geometry
    left, top, _right, _bottom = workerw_rect
    return (x + left, y + top, width, height)


def clamp_geometry_to_monitors(
    geometry: Geometry, monitors: Sequence[Rect], primary_monitor: Rect
) -> Geometry:
    """S8: 지오메트리의 좌상단이 현재 모니터 목록 중 어느 하나에도 속하지 않으면(대상
    모니터가 분리/제거됨) 주 모니터 안으로 클램프한다. 하나라도 속하면 그대로 반환한다."""
    x, y, width, height = geometry
    for left, top, right, bottom in monitors:
        if left <= x < right and top <= y < bottom:
            return geometry

    p_left, p_top, p_right, p_bottom = primary_monitor
    max_x = max(p_left, p_right - width)
    max_y = max(p_top, p_bottom - height)
    new_x = min(max(x, p_left), max_x)
    new_y = min(max(y, p_top), max_y)
    return (new_x, new_y, width, height)


# --------------------------------------------------------------------------
# 입력 판정 (D9/D16) — 더블클릭 감지 + 시트 사각형 히트. Qt-free 순수 함수만.
# 실 WH_MOUSE_LL 훅(ctypes)은 P3의 windows/sheet_mode.py 몫 — 여기서는 판정만 한다.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ClickRecord:
    """WH_MOUSE_LL 훅이 관측한 WM_LBUTTONDOWN 한 건 — 화면 좌표 + 훅이 보고한 시각
    (MSLLHOOKSTRUCT.time, GetTickCount 계열 ms 단위)."""

    x: int
    y: int
    timestamp_ms: int


def point_in_rect(x: int, y: int, rect: Rect) -> bool:
    """점(화면 좌표)이 사각형(left, top, right, bottom) 안에 있는지 판정한다(D9 "시트
    사각형 히트" — 우측/하단 경계는 배타적, win32 RECT 관례와 동일하게 다룬다)."""
    left, top, right, bottom = rect
    return left <= x < right and top <= y < bottom


def screen_point_to_local(x: int, y: int, rect: Rect) -> tuple[int, int]:
    """화면 좌표 점 하나를 rect(예: GetWindowRect(main_hwnd)) 기준 로컬 좌표로 변환한다.

    D9 항목3: WS_CHILD 상태에서 Qt의 mapFromGlobal은 신뢰할 수 없으므로 win32
    GetWindowRect 기준으로 계산해야 한다 — `screen_to_workerw_local`과 같은 변환을
    점 하나에 대해 재사용한다(기존 함수 재사용, 새 산술 금지)."""
    local_x, local_y, _width, _height = screen_to_workerw_local((x, y, 0, 0), rect)
    return local_x, local_y


def is_double_click(
    prev_click: ClickRecord | None,
    click: ClickRecord,
    *,
    interval_ms: int,
    radius_px: int,
) -> bool:
    """D9/D16: 이전 클릭과 이번 클릭이 시스템 더블클릭 간격(GetDoubleClickTime())과
    반경(radius_px) 안에 모두 들어오면 더블클릭으로 판정한다.

    - prev_click이 없으면(첫 클릭) 항상 False.
    - 시각이 역행하면(GetTickCount 오버플로 등 방어) 단일 클릭으로 취급한다.
    - 간격 초과 또는 반경 초과 중 하나라도 있으면 False.
    """
    if prev_click is None:
        return False
    if click.timestamp_ms < prev_click.timestamp_ms:
        return False
    if click.timestamp_ms - prev_click.timestamp_ms > interval_ms:
        return False
    return abs(click.x - prev_click.x) <= radius_px and abs(click.y - prev_click.y) <= radius_px


# --------------------------------------------------------------------------
# 상태 머신 (§0 · §2)
# --------------------------------------------------------------------------


class SheetState(StrEnum):
    NORMAL = "normal"
    SHEET = "sheet"
    SHEET_PASSTHROUGH = "sheet_passthrough"


class SheetEvent(StrEnum):
    ENTER_SHEET = "enter_sheet"  # NORMAL -> SHEET (트레이/설정 "시트 모드 켜기")
    ENTER_SHEET_FAILED = "enter_sheet_failed"  # NORMAL -> NORMAL (탐색/부착 실패, D14)
    EXIT_SHEET = "exit_sheet"  # SHEET -> NORMAL ("시트 모드 끄기")
    ENABLE_PASSTHROUGH = "enable_passthrough"  # SHEET -> SHEET_PASSTHROUGH ("클릭 투과 켜기")
    DISABLE_PASSTHROUGH = "disable_passthrough"  # SHEET_PASSTHROUGH -> SHEET ("클릭 투과 끄기")
    GUARDIAN_RECOVER = "guardian_recover"  # 가디언: 재탐색·재부착 성공(동일 상태 유지)
    GUARDIAN_FALLBACK = "guardian_fallback"  # 가디언: 재부착 실패 -> NORMAL (D14 폴백)
    DISPLAY_CHANGED = "display_changed"  # 화면 구성 변경 시그널(동일 상태 유지, 좌표 재계산)


class IllegalTransitionError(ValueError):
    """§2 표에 없는 전이를 시도했을 때 발생 — 특히 NORMAL↔SHEET_PASSTHROUGH 직행 금지(D2 서두)."""

    def __init__(self, state: SheetState, event: SheetEvent) -> None:
        super().__init__(f"illegal sheet-mode transition: {state.value} + {event.value}")
        self.state = state
        self.event = event


# (state, event) -> (next_state, actions). actions는 순서가 있는 순수 데이터 —
# 실제 수행(win32 호출·config 저장 등)은 P2 SheetModeController의 몫이다.
_TRANSITIONS: dict[tuple[SheetState, SheetEvent], tuple[SheetState, tuple[str, ...]]] = {
    (SheetState.NORMAL, SheetEvent.ENTER_SHEET): (
        SheetState.SHEET,
        (
            "remember_geometry",
            "locate_workerw",
            "attach_and_restyle",
            "convert_screen_to_local",
            "apply_sheet_form",
            "start_guardian",
            "save_config",
        ),
    ),
    (SheetState.NORMAL, SheetEvent.ENTER_SHEET_FAILED): (
        SheetState.NORMAL,
        ("show_fallback_notice",),
    ),
    (SheetState.SHEET, SheetEvent.EXIT_SHEET): (
        SheetState.NORMAL,
        (
            "stop_guardian",
            "disable_passthrough",
            "detach_and_restore_style",
            "restore_screen_geometry",
            "restore_chrome",
            "save_config",
        ),
    ),
    (SheetState.SHEET, SheetEvent.ENABLE_PASSTHROUGH): (
        SheetState.SHEET_PASSTHROUGH,
        ("apply_passthrough_style", "save_config"),
    ),
    (SheetState.SHEET_PASSTHROUGH, SheetEvent.DISABLE_PASSTHROUGH): (
        SheetState.SHEET,
        ("clear_passthrough_style", "save_config"),
    ),
    (SheetState.SHEET, SheetEvent.GUARDIAN_RECOVER): (
        SheetState.SHEET,
        ("reattach",),
    ),
    (SheetState.SHEET_PASSTHROUGH, SheetEvent.GUARDIAN_RECOVER): (
        SheetState.SHEET_PASSTHROUGH,
        ("reattach",),
    ),
    (SheetState.SHEET, SheetEvent.GUARDIAN_FALLBACK): (
        SheetState.NORMAL,
        ("show_fallback_notice",),
    ),
    (SheetState.SHEET_PASSTHROUGH, SheetEvent.GUARDIAN_FALLBACK): (
        SheetState.NORMAL,
        ("show_fallback_notice",),
    ),
    (SheetState.SHEET, SheetEvent.DISPLAY_CHANGED): (
        SheetState.SHEET,
        ("recalculate_geometry",),
    ),
    (SheetState.SHEET_PASSTHROUGH, SheetEvent.DISPLAY_CHANGED): (
        SheetState.SHEET_PASSTHROUGH,
        ("recalculate_geometry",),
    ),
}


def transition(state: SheetState, event: SheetEvent) -> tuple[SheetState, list[str]]:
    """§2 표의 합법 전이만 허용한다. 표에 없는 (state, event) 조합은
    `IllegalTransitionError`를 던진다 — 특히 NORMAL↔SHEET_PASSTHROUGH 직행은 항상 거부된다
    (투과는 반드시 SHEET를 거친다)."""
    key = (state, event)
    entry = _TRANSITIONS.get(key)
    if entry is None:
        raise IllegalTransitionError(state, event)
    next_state, actions = entry
    return next_state, list(actions)


def should_ignore_drag(state: SheetState) -> bool:
    """D7: SHEET/SHEET_PASSTHROUGH 중에는 드래그 이동·리사이즈를 무시한다.
    (`RoundedWindow.mousePressEvent`/`ResizeHandle`의 실제 무시 처리는 Qt 통합부인
    P3 몫 — 여기서는 상태만 보고 판정하는 순수 술어만 제공한다.)"""
    return state is not SheetState.NORMAL


# --------------------------------------------------------------------------
# 가디언 판정 (D5)
# --------------------------------------------------------------------------


class GuardianVerdict(StrEnum):
    OK = "ok"
    REATTACH = "reattach"
    RECREATE = "recreate"
    FALLBACK = "fallback"


def guardian_verdict(
    *,
    is_workerw_valid: bool,
    is_main_hwnd_valid: bool,
    parent_hwnd: int | None,
    workerw_hwnd: int | None,
    retry_count: int,
    max_retries: int = 1,
) -> GuardianVerdict:
    """D5 가디언 판정.

    - OK: WorkerW와 메인 핸들이 모두 유효하고 GetParent(main)==workerw.
    - retry_count가 max_retries(기본 1, D14 "세션 내 자동 재시도는 1회") 이상이면 더 이상
      재시도하지 않고 FALLBACK(1회 고지) — 메인 핸들 유효성과 무관하게 우선한다(무한 재시도
      루프 방지).
    - 메인 창 핸들 사망(explorer 재시작의 DestroyWindow 연쇄, S17)이면 RECREATE(핸들
      재생성이 재부착보다 먼저 필요).
    - 그 외(WorkerW만 무효거나 parent 불일치)는 REATTACH.
    """
    if is_workerw_valid and is_main_hwnd_valid and parent_hwnd == workerw_hwnd:
        return GuardianVerdict.OK
    if retry_count >= max_retries:
        return GuardianVerdict.FALLBACK
    if not is_main_hwnd_valid:
        return GuardianVerdict.RECREATE
    return GuardianVerdict.REATTACH


# --------------------------------------------------------------------------
# config 기본값 (D10)
# --------------------------------------------------------------------------

SHEET_CONFIG_DEFAULTS: dict[str, object] = {
    "sheet_mode": False,
    "sheet_click_through": False,
    "sheet_opacity": 45,
}


def apply_sheet_defaults(config: dict) -> None:
    """schema_version 범프 없이 additive+setdefault로 시트 모드 config 키를 채운다
    (app_config.load_config의 defaults.setdefault 패턴과 동형). 구버전 config가 읽혀도
    이 세 키가 없을 뿐 무시되고, 여기서 기본값으로 채워진다."""
    for key, value in SHEET_CONFIG_DEFAULTS.items():
        config.setdefault(key, value)
