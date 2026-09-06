"""Qt와 독립된 공휴일 디스크 캐시 정책과 파일 I/O를 제공합니다.

국가·연도·앱 언어·라이브러리 버전을 키로 사용합니다. 공급자 언어 조회 자체가 비싸므로
캐시 적중 여부는 앱 언어만으로 결정하고 실제 언어 해석은 캐시 미스 때 수행합니다.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path

from chronofox.core.app_storage import write_text_atomic

# 파일 포맷이나 공휴일 라이브러리 버전이 달라지면 파생 캐시 전체를 폐기한다.
CACHE_FORMAT_VERSION = 1

# 연도별 항목은 작지만 무한 증가를 막기 위해 상한을 둔다.
DEFAULT_PRUNE_LIMIT = 128


def cache_key(country: str, year: int, language: str) -> str:
    """`국가|연도|앱 언어` 형식의 캐시 키를 만듭니다.

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
    """상한을 넘으면 현재 국가·언어의 최근 연도 위주로 결정적으로 정리합니다.

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


# 파일 I/O를 순수 변환 함수와 분리해 파일 없이 정책을 검증할 수 있게 한다.


def read_cache_file(path: Path, lib_version: str) -> dict[str, dict[str, str]]:
    """디스크에서 캐시 파일을 읽어 entries를 반환한다.

    파일이 없거나 읽기 실패(OSError)해도 예외를 삼키고 빈 dict를 반환합니다.
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
