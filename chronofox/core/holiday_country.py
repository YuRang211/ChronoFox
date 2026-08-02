"""P-2 다국가 공휴일 판정 순수 로직(HL-D1~D11, `planning/PROJECT.md` §12-H). Qt 비의존.

국가 코드 해석(`resolve_country`)과 언어 해석(`resolve_language`)은 순수 함수로 감지값을
인자로 받는다 — Windows `GetUserDefaultGeoName()` 같은 실제 OS 호출은 `detect_country_windows()`
하나에만 몰아 두고, 판정 함수는 그 결과값을 주입받게 해 ctypes 없이 테스트한다(HL-D10).

`holidays.registry.COUNTRIES`는 국가 250개를 `module_name -> (ClassName, alpha2, alpha3, ...)`
형태로 담고 있다. `holidays.list_supported_countries()`(alpha-2 250 + alpha-3 250 + "UK" =
501키)를 쓰면 같은 나라가 두 번 나오므로 목록 생성에는 반드시 `registry.COUNTRIES`만 쓴다(HL-D4).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence

FALLBACK_COUNTRY = "KR"  # HL-D3: 자동 감지 실패 시 폴백
AUTO_COUNTRY_SETTING = "auto"  # HL-D1: holiday_country 설정값 중 "자동 감지"를 뜻하는 값

# CamelCase 국가 클래스명을 띄어쓰기로 분리하는 2단계 정규식(HL-D5).
# 1단계: 소문자/숫자 뒤에 오는 대문자 앞에 공백을 넣는다 ("SouthKorea" -> "South Korea").
# 2단계: 대문자 뒤에 "대문자+소문자"가 이어지면 그 경계에 공백을 넣는다 — 연속된 대문자를
#        약어(acronym)로 보고 마지막 한 글자만 다음 단어로 넘긴다 ("DRCongo" -> "DR Congo").
_CAMEL_LOWER_TO_UPPER = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_CAMEL_ACRONYM_BOUNDARY = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")

# HL-D6: 앱 언어(ko/en) -> 국가별 supported_languages에서 찾을 후보 코드(우선순위 순).
_LANGUAGE_CANDIDATES: dict[str, tuple[str, ...]] = {
    "ko": ("ko", "ko_KR"),
    "en": ("en_US", "en_GB", "en"),
}


def _normalize_code(value: object) -> str:
    """국가 코드류 문자열을 대문자·공백 제거로 정규화합니다(빈 값이면 "")."""
    return str(value or "").strip().upper()


def split_camel_name(name: str) -> str:
    """CamelCase 국가 클래스명을 띄어쓰기로 분리합니다.

    `SouthKorea` -> `South Korea`, `DRCongo` -> `DR Congo`(연속 대문자는 약어로 보고
    한 단어로 유지한다), `UnitedArabEmirates` -> `United Arab Emirates`.
    """
    spaced = _CAMEL_LOWER_TO_UPPER.sub(" ", name)
    spaced = _CAMEL_ACRONYM_BOUNDARY.sub(" ", spaced)
    return spaced


def detect_country_windows() -> str | None:
    """Windows `GetUserDefaultGeoName()`으로 오프라인 지역 코드를 얻습니다(HL-D3).

    IP 조회 등 온라인 폴백은 쓰지 않는다 — 실패(예외·빈 값)하면 None을 반환하고,
    호출부는 `resolve_country`의 두 번째 인자로 이 반환값을 그대로 넘긴다.
    """
    try:
        import ctypes

        buf = ctypes.create_unicode_buffer(9)  # ISO 3166-1 alpha-2 + 여유
        length = ctypes.windll.kernel32.GetUserDefaultGeoName(buf, len(buf))
        if length <= 1:  # 실패 시 0, 널 종단 문자만 있으면 1
            return None
        code = _normalize_code(buf.value)
        return code or None
    except Exception:
        logging.getLogger(__name__).exception("GetUserDefaultGeoName failed")
        return None


def resolve_country(setting: object, detected: str | None) -> str:
    """`holiday_country` 설정값을 실제 국가 코드로 해석합니다.

    우선순위(HL-D2/D3): 설정값("auto" 제외) > 감지값 > "KR" 폴백. `setting`이 `"auto"`
    (대소문자 무관)이거나 비어 있으면 `detected`를 쓰고, `detected`도 비어 있으면
    `FALLBACK_COUNTRY`("KR")로 떨어진다.
    """
    normalized_setting = _normalize_code(setting)
    if normalized_setting and normalized_setting != AUTO_COUNTRY_SETTING.upper():
        return normalized_setting
    normalized_detected = _normalize_code(detected)
    return normalized_detected or FALLBACK_COUNTRY


def resolve_language(app_lang: object, supported: Sequence[str] | None) -> str | None:
    """앱 언어(ko/en)를 국가별 `supported_languages`에 맞는 코드로 해석합니다(HL-D6).

    맞는 항목이 없으면 None을 반환한다 — 호출부는 `language` 인자를 생략해 그 나라
    기본 언어(`default_language`)로 자연 폴백하게 둔다. `holidays` 라이브러리는 실제로
    미지원 언어를 넘겨도 예외 없이 그 나라 기본 언어로 폴백하지만(실측 확인, DE에
    language="ko" -> "Neujahr"), 이 함수는 그 의도를 코드에 명시적으로 드러낸다.
    """
    normalized = str(app_lang or "").strip().lower()
    if not supported:
        return None
    supported_list = list(supported)
    for candidate in _LANGUAGE_CANDIDATES.get(normalized, ()):
        if candidate in supported_list:
            return candidate
    if normalized:
        for lang in supported_list:
            if lang.lower().startswith(normalized):
                return lang
    return None


def supported_country_rows() -> list[tuple[str, str]]:
    """`registry.COUNTRIES` 기반 (코드, 표시명) 목록을 만듭니다(HL-D4/D5).

    alpha-2 코드만 쓰고(`list_supported_countries()`의 alpha-3 별칭·"UK"는 배제) 코드
    기준 중복을 걸러 250개를 보장한다. 표시명은 CamelCase 클래스명을 띄어쓰기로 분리한
    뒤 코드를 괄호로 덧붙인다(`SouthKorea`/`KR` -> `South Korea (KR)`). 250개국 이름은
    번역하지 않는다(HL-D5) — 표시명 정렬은 알파벳 순.

    P-2b(C-D5의 연장): `holidays.registry`를 여기 안에서만 지연 import한다 — 이 함수는
    설정 화면에서 국가 콤보박스를 열 때만 호출되므로, 모듈 최상단에서 import하면
    `holiday_country`를 그저 import하기만 해도(=거의 항상, `desktop_note_calendar.py`가
    시작 시 이 모듈을 불러온다) `holidays` 패키지 전체 초기화 비용(약 279~400ms)이
    무조건 발생해 공휴일 디스크 캐시가 적중해도 그 비용을 되찾지 못한다.
    """
    from holidays.registry import COUNTRIES

    rows: list[tuple[str, str]] = []
    seen_codes: set[str] = set()
    for entry in COUNTRIES.values():
        class_name, alpha2 = entry[0], entry[1]
        if alpha2 in seen_codes:
            continue
        seen_codes.add(alpha2)
        display = f"{split_camel_name(class_name)} ({alpha2})"
        rows.append((alpha2, display))
    rows.sort(key=lambda row: row[1])
    return rows
