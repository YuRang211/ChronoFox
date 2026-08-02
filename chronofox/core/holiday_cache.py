"""P-2b 공휴일 디스크 캐시 순수 로직(C-D1~D11, `planning/PROJECT.md` §12-I). Qt 비의존.

목표: 두 번째 실행부터 `import holidays`(약 279ms) + 첫 `country_holidays()` 호출(약 582ms)을
0으로 만든다. 답을 바꾸는 것은 국가·연도·언어·라이브러리 버전 넷뿐이므로 이것들을 캐시 키에
넣으면 시간 기반 갱신 없이도 정확하다(C-D4).

**캐시 키의 `language`는 holidays 라이브러리가 실제로 쓰는 언어 코드(`en_US`/`ko` 등)가
아니라 앱 언어 설정값("ko"/"en")이다.** 실측(desktop_note_calendar.holidays_for_year 실장 중
확인, 보고서 참조): 라이브러리 코드로 언어를 해석하려면 `country_holidays(country,
years=[]).supported_languages`를 조회해야 하는데, 이 호출 자체가 이미 `holidays`를
import하고 첫 `country_holidays()` 생성 비용(약 740ms, `years=[]`라도 동일)을 낸다. 캐시
적중 판정에 이 비용이 끼면 C-D5("캐시 적중 시 holidays를 import하지 않는다")가 무의미해진다.
앱 언어는 국가별 `supported_languages`의 부분집합에 대해 결정적으로 매핑되므로(같은 국가에
같은 앱 언어를 넣으면 항상 같은 결과), 앱 언어를 키에 쓰는 것으로 충분하다 — 실제 라이브러리
언어 해석(`resolve_language`)은 캐시 미스일 때만 수행한다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from chronofox.core.app_storage import write_text_atomic

# 캐시 파일 포맷 버전(C-D2) — lib_version과 별개로, 이 모듈 자체의 저장 구조가 바뀌면
# 올린다. 두 값 중 하나라도 안 맞으면 파일 전체를 폐기한다(C-D3/C-D6).
CACHE_FORMAT_VERSION = 1

# C-D8: 항목 수 상한. 675바이트/년이라 크기 자체는 문제가 아니지만 무한 증가는 막는다.
DEFAULT_PRUNE_LIMIT = 128


def cache_key(country: str, year: int, language: str) -> str:
    """캐시 항목 키를 만든다(C-D2): `국가|연도|언어`.

    `language`는 앱 언어 설정값("ko"/"en" 등)이다 — 모듈 docstring 참고.
    """
    return f"{country}|{year}|{language}"


def _parse_cache_key(key: str) -> tuple[str, int | None, str]:
    """캐시 키를 (국가, 연도 또는 None, 언어)로 되돌린다. 형식이 안 맞으면 관대하게 처리한다."""
    parts = key.split("|", 2)
    country = parts[0] if len(parts) > 0 else ""
    language = parts[2] if len(parts) > 2 else ""
    year: int | None = None
    if len(parts) > 1:
        try:
            year = int(parts[1])
        except ValueError:
            year = None
    return country, year, language


def serialize(entries: Mapping[str, Mapping[str, str]], lib_version: str) -> str:
    """entries를 디스크에 쓸 JSON 문자열로 직렬화한다."""
    payload = {
        "version": CACHE_FORMAT_VERSION,
        "lib_version": lib_version,
        "entries": {key: dict(value) for key, value in entries.items()},
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def load_entries(raw: str, lib_version: str) -> dict[str, dict[str, str]]:
    """캐시 JSON 텍스트를 entries(dict)로 역직렬화한다.

    `lib_version`이 현재 값과 다르거나(C-D3) 포맷이 어긋나면(C-D6) **빈 dict**를 반환한다 —
    예외를 던지지 않는다. 손상 격리(`.corrupt-*`)나 사용자 고지는 하지 않는다(C-D6) — 캐시는
    파생 데이터라 지워도 사용자가 잃는 것이 없다.
    """
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("version") != CACHE_FORMAT_VERSION:
        return {}
    if payload.get("lib_version") != lib_version:
        return {}

    raw_entries = payload.get("entries")
    if not isinstance(raw_entries, dict):
        return {}

    entries: dict[str, dict[str, str]] = {}
    for key, value in raw_entries.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        cleaned = {iso: name for iso, name in value.items() if isinstance(iso, str) and isinstance(name, str)}
        entries[key] = cleaned
    return entries


def prune(
    entries: Mapping[str, Mapping[str, str]],
    *,
    country: str,
    language: str,
    today_year: int,
    limit: int = DEFAULT_PRUNE_LIMIT,
) -> dict[str, dict[str, str]]:
    """항목 수가 `limit`을 넘으면 현재 국가·언어의 최근 연도 위주로 결정적으로 정리한다(C-D8).

    정렬 기준(전부 결정적, 무작위/시각 의존 없음):
    1. 현재 국가+언어와 일치하는 항목을 그렇지 않은 항목보다 우선한다.
    2. `today_year`와의 거리가 가까운 연도를 우선한다.
    3. 그래도 동률이면 키 문자열 알파벳 순으로 정렬한다(안정적인 tie-break).
    """
    if len(entries) <= limit:
        return {key: dict(value) for key, value in entries.items()}

    def sort_key(item: tuple[str, Mapping[str, str]]) -> tuple[int, int, str]:
        key, _value = item
        entry_country, entry_year, entry_language = _parse_cache_key(key)
        is_current = 0 if (entry_country == country and entry_language == language) else 1
        year_distance = abs(entry_year - today_year) if entry_year is not None else 10**9
        return (is_current, year_distance, key)

    ranked = sorted(entries.items(), key=sort_key)
    kept = ranked[:limit]
    return {key: dict(value) for key, value in kept}


def entry_from_holidays(holidays_by_date: Mapping[date, str]) -> dict[str, str]:
    """`{date: 이름}`(계산 결과)를 캐시 항목 형태(`{ISO 날짜 문자열: 이름}`)로 바꾼다."""
    return {day.isoformat(): name for day, name in holidays_by_date.items()}


def entry_to_holidays(entry: Mapping[str, str]) -> dict[date, str]:
    """캐시 항목(`{ISO 날짜 문자열: 이름}`)을 `{date: 이름}`으로 되돌린다.

    ISO 형식이 아닌 키는 조용히 건너뛴다(C-D6과 같은 결 — 손상된 개별 항목 때문에 전체를
    실패시키지 않는다)."""
    result: dict[date, str] = {}
    for iso_day, name in entry.items():
        try:
            result[date.fromisoformat(iso_day)] = name
        except ValueError:
            continue
    return result


# ---------------------------------------------------------------------------
# 파일 I/O 얇은 래퍼(C-D9). 위의 순수 함수와 분리해 둔다 — 테스트는 순수 함수를 파일 없이
# 검증하고, 아래 두 함수만 실제 디스크를 만진다.
# ---------------------------------------------------------------------------


def read_cache_file(path: Path, lib_version: str) -> dict[str, dict[str, str]]:
    """디스크에서 캐시 파일을 읽어 entries를 반환한다.

    파일이 없거나 읽기 실패(OSError)해도 예외를 삼키고 빈 dict를 반환한다(C-D6/C-D7).
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    return load_entries(raw, lib_version)


def write_cache_file(path: Path, entries: Mapping[str, Mapping[str, str]], lib_version: str) -> None:
    """entries를 `write_text_atomic`으로 원자적으로 기록한다.

    쓰기가 실패해도(디렉터리 생성 실패·권한 등) 예외를 삼키고 앱은 정상 동작한다(C-D7) —
    캐시는 최적화일 뿐이다.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, serialize(entries, lib_version))
    except OSError:
        pass
