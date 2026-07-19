"""전역 단축키(U1) 조합 문자열 <-> Win32 RegisterHotKey 인자 순수 변환.

`planning/specs/quick-input-parser.md` §4 U1·4b Q3 대상. Qt-free — 실제 ctypes
RegisterHotKey 호출과 숨김 네이티브 창(nativeEvent) 오케스트레이션은
`chronofox.windows.global_hotkey`에 있다(core/에 Qt import 금지 규칙).

지원 범위: ctrl/alt/shift/win 수식키(1개 이상) + 단일 키(A~Z·0~9·SPACE·F1~F12).
그 외 문자열은 파싱 실패(None)로 처리하고, 호출측이 기본값으로 폴백한다
(quick-input-parser.md P1 보수적 해석과 동일 원칙 — 애매하면 구조화하지 않는다).
"""

from __future__ import annotations

# Win32 MOD_* 상수 (RegisterHotKey의 fsModifiers 인자와 동일 값)
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008

# Win32 VK_* 상수 중 이 기능이 지원하는 부분집합
VK_SPACE = 0x20

# 기본값을 space에서 q로 변경(2026-07-18 실기기 검증): Ctrl+Alt+Space는 이 기준 머신에서
# 이미 다른 프로그램(IME 계열 추정)이 선점해 RegisterHotKey가 실패했다 — Q(uick)는 선점
# 빈도가 낮고 기억하기 쉽다. 사용자는 설정에서 변경 가능.
DEFAULT_QUICK_HOTKEY = "ctrl+alt+q"

_MODIFIER_TOKENS: dict[str, int] = {
    "ctrl": MOD_CONTROL,
    "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN,
    "windows": MOD_WIN,
    "meta": MOD_WIN,
}

# VK_0..VK_9 == ord('0')..ord('9'), VK_A..VK_Z == ord('A')..ord('Z') (Win32 관례).
# 토큰은 소문자로 정규화해 조회하므로(위 parse_hotkey_string), 키도 소문자로 등록한다.
_KEY_TOKENS: dict[str, int] = {"space": VK_SPACE}
_KEY_TOKENS.update({chr(code).lower(): code for code in range(ord("A"), ord("Z") + 1)})
_KEY_TOKENS.update({str(digit): ord("0") + digit for digit in range(10)})
_KEY_TOKENS.update({f"f{n}": 0x70 + (n - 1) for n in range(1, 13)})  # VK_F1=0x70 .. VK_F12=0x7B


def parse_hotkey_string(text: str) -> tuple[int, int] | None:
    """"ctrl+alt+space" 같은 조합 문자열을 (modifiers, vk) 튜플로 변환합니다.

    수식키 최소 1개 + 키 1개 형태만 인정한다(수식키 없는 단일 키는 다른 프로그램과의
    충돌 위험이 커 지원 밖). 토큰 하나라도 인식 못 하면 통째로 실패(None) — 부분
    매핑으로 엉뚱한 조합을 등록하지 않는다.
    """
    if not text or not text.strip():
        return None
    parts = [part.strip().lower() for part in text.split("+") if part.strip()]
    if len(parts) < 2:
        return None
    *modifier_parts, key_part = parts
    modifiers = 0
    for part in modifier_parts:
        mod = _MODIFIER_TOKENS.get(part)
        if mod is None:
            return None
        modifiers |= mod
    vk = _KEY_TOKENS.get(key_part)
    if vk is None or modifiers == 0:
        return None
    return modifiers, vk


def format_hotkey_display(text: str) -> str:
    """설정 화면 표시용 사람이 읽는 형태로 바꿉니다: "ctrl+alt+space" -> "Ctrl+Alt+Space"."""
    parts = [part.strip() for part in (text or "").split("+") if part.strip()]
    if not parts:
        return ""
    return "+".join(part.capitalize() for part in parts)
