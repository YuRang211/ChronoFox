"""Quick Input 한 줄 텍스트를 초안(Draft)으로 변환하는 Qt-free 순수 파서.

`planning/specs/quick-input-parser.md`(0.9 헤드라인) Q1 구현. 외부 API·ML 없이
정규식/날짜산술만으로 종류(타이머/반복/일정/노트/알람/할 일)를 분류하고 제목·일시·
주기·모호성 플래그를 뽑아낸다. 항상 확인 스텝(UI, Q2 몫)을 거쳐 저장되므로 이 모듈은
"최선의 추정"만 만들고 저장은 하지 않는다 — P0/P1 원칙.

공개 API는 `parse(text, now) -> Draft` 하나뿐이다. 현재 시각은 반드시 `now` 인자로만
받는다(datetime.now() 직접 조회 금지 — 결정적 파서 요건, todo_logic 선례와 동일하게
Qt import 없이 단위 테스트 가능해야 한다).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from datetime import time as dt_time
from enum import StrEnum

# ---------------------------------------------------------------------------
# 공개 타입
# ---------------------------------------------------------------------------


class Kind(StrEnum):
    """Draft.kind — §1 분류 순위표의 여섯 종류."""

    TIMER = "TIMER"
    RECURRING = "RECURRING"
    PLAN = "PLAN"
    NOTE = "NOTE"
    ALARM = "ALARM"
    TASK = "TASK"


@dataclass(frozen=True, slots=True)
class Draft:
    """파싱 결과 초안. UI(Q2)가 미리보기 카드에 그대로 얹어 보여준다."""

    kind: Kind
    title: str
    start: datetime | None
    end: datetime | None
    period: str | None  # daily/weekly/monthly/yearly (RECURRING·TASK 기본값)
    duration_minutes: int | None  # TIMER 전용
    ambiguity_flags: frozenset[str]


# ---------------------------------------------------------------------------
# 내부 매치 표현
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _RecurringMatch:
    span: tuple[int, int]
    period: str


@dataclass(frozen=True, slots=True)
class _DurationMatch:
    span: tuple[int, int]
    minutes: int


@dataclass(frozen=True, slots=True)
class _DateMatch:
    span: tuple[int, int]
    value: date
    needs_time_check: bool  # True면(요일 delta==0) 결합 시각이 이미 지났을 때 +7일


@dataclass(frozen=True, slots=True)
class _TimeMatch:
    span: tuple[int, int]
    hour: int
    minute: int
    end_hour: int | None
    end_minute: int | None
    ampm_flag: bool


# ---------------------------------------------------------------------------
# 정규식 상수
# ---------------------------------------------------------------------------

_HOUR_WORDS: dict[str, int] = {
    "한": 1,
    "두": 2,
    "세": 3,
    "네": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열두": 12,
    "열한": 11,
    "열": 10,
}
# 길이 긴 표기(열한/열두)를 먼저 시도해야 "열"이 먼저 걸려 뒤 글자가 남는 일이 없다.
_HOUR_ALT = "|".join(sorted(_HOUR_WORDS, key=len, reverse=True)) + r"|\d{1,2}"

_AMPM_MOD = r"오전|아침|오후|저녁|밤"

_RECURRING_RE = re.compile(
    r"(?P<daily>매일|every\s+day)"
    r"|(?P<weekly>매주|every\s+week)"
    r"|(?P<monthly>매달|매월|every\s+month)"
    r"|(?P<yearly>매년|every\s+year)",
    re.IGNORECASE,
)

_REL_DURATION_RE = re.compile(
    r"(?P<n1>\d{1,3})\s*(?P<unit1>분|시간)\s*(?:뒤|후)"
    r"|\bin\s+(?P<n2>\d{1,3})\s*(?P<unit2>min(?:ute)?s?|hours?|hrs?)\b",
    re.IGNORECASE,
)

_DURATION_TOKEN_RE = re.compile(r"(?P<n>\d{1,3})\s*(?P<unit>분|시간)\s*동안")

_RELATIVE_DAY_RE = re.compile(r"오늘|내일|모레|글피|\btoday\b|\btomorrow\b", re.IGNORECASE)
_REL_N_DAYS_RE = re.compile(r"(?P<n>\d{1,3})일\s*(?:뒤|후)")

_WEEKDAY_KO: dict[str, int] = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
_WEEKDAY_EN: dict[str, int] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
_WEEKDAY_RE = re.compile(
    r"(?P<nextweek>다음\s*주\s*|next\s+week\s+)?"
    r"\b(?P<wd>월요일|화요일|수요일|목요일|금요일|토요일|일요일"
    r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tue|wed|thu|fri|sat|sun)\b",
    re.IGNORECASE,
)

_YMD_RE = re.compile(r"(?P<y>\d{4})-(?P<m>\d{1,2})-(?P<d>\d{1,2})")
_MD_KOR_RE = re.compile(r"(?P<m>\d{1,2})월\s*(?P<d>\d{1,2})일")
_MD_SLASH_RE = re.compile(r"(?<!\d)(?P<m>\d{1,2})/(?P<d>\d{1,2})(?!\d)")

_RANGE_TIME_RE = re.compile(
    # 첫 시각의 "시"는 생략 가능("3-5시") — 두 번째 시각의 "시"만 필수라 범위 표현임이 확정된다.
    rf"(?P<mod1>{_AMPM_MOD})?\s*(?P<h1>{_HOUR_ALT})\s*시?\s*(?:(?P<half1>반)|(?P<min1>\d{{1,2}})분)?"
    rf"\s*[~-]\s*"
    rf"(?P<mod2>{_AMPM_MOD})?\s*(?P<h2>{_HOUR_ALT})시\s*(?:(?P<half2>반)|(?P<min2>\d{{1,2}})분)?"
)
_SINGLE_TIME_KO_RE = re.compile(
    rf"(?P<mod>{_AMPM_MOD})?\s*(?P<hour>{_HOUR_ALT})시\s*(?:(?P<half>반)|(?P<min>\d{{1,2}})분)?"
)
_COLON_TIME_RE = re.compile(
    rf"(?P<mod>{_AMPM_MOD})?\s*(?P<hour>\d{{1,2}}):(?P<min>\d{{2}})"
)


# ---------------------------------------------------------------------------
# 시각 계산 헬퍼
# ---------------------------------------------------------------------------


def _hour_value(raw: str) -> int:
    if raw in _HOUR_WORDS:
        return _HOUR_WORDS[raw]
    return int(raw)


def _apply_ampm(hour: int, modifier: str | None) -> tuple[int, bool]:
    """(해석된 24시간제 시각, ampm 모호 플래그 필요 여부)를 반환합니다.

    §2: 오전/아침=AM, 오후/저녁/밤=PM은 1~11시에만 적용(12시는 그대로 둔다 — 정오/자정
    경계는 실제로도 모호한 표기라 P1대로 손대지 않는다). 수식어가 전혀 없고 1~7시면
    모호 플래그를 세우고 기본값 PM(+12)을 적용한다. 8~11시 무수식어는 그대로 둔다.
    """
    if modifier in ("오전", "아침") and 1 <= hour <= 11:
        return hour, False
    if modifier in ("오후", "저녁", "밤") and 1 <= hour <= 11:
        return hour + 12, False
    if modifier is None and 1 <= hour <= 7:
        return hour + 12, True
    return hour, False


def _resolve_month_day(month: int, day: int, today: date) -> date | None:
    """연도 없는 M월D일/M-D를 다음 발생일로 해석합니다.

    지난 날짜면 내년으로, 그 연도에 유효하지 않은 날짜(2/29 등)면 유효해질 때까지
    연도를 계속 증가시킵니다(agy#3). 월/일 자체가 범위를 벗어나면 None(실패 — 호출부가
    제목에 원문을 보존).
    """
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    year = today.year
    for _ in range(8):
        try:
            candidate = date(year, month, day)
        except ValueError:
            year += 1
            continue
        if candidate < today:
            year += 1
            continue
        return candidate
    return None


def _resolve_weekday(target_idx: int, today: date, next_week: bool) -> tuple[date, bool]:
    """요일 다음 발생일을 계산합니다.

    "다음주"(next_week=True)는 ISO 주(월요일 시작) 기준 차주의 해당 요일이다 —
    오늘이 일요일이면 이번 ISO 주는 이미 끝나가는 중이므로, 단순히 "다음 발생 + 7일"로
    계산하면 한 주를 더 건너뛰는 오류가 난다(예: 일요일에 "다음주 수요일"은 사흘 뒤 —
    이번 주 수요일은 이미 지났으므로). 이번 주 월요일을 기준으로 삼아 +7일 한 뒤
    target_idx만큼 더한다.
    """
    if next_week:
        this_monday = today - timedelta(days=today.weekday())
        next_monday = this_monday + timedelta(days=7)
        return next_monday + timedelta(days=target_idx), False
    delta = (target_idx - today.weekday()) % 7
    needs_check = delta == 0
    return today + timedelta(days=delta), needs_check


# ---------------------------------------------------------------------------
# 토큰 탐지
# ---------------------------------------------------------------------------


def _find_recurring(text: str) -> _RecurringMatch | None:
    m = _RECURRING_RE.search(text)
    if not m:
        return None
    for period in ("daily", "weekly", "monthly", "yearly"):
        if m.group(period):
            return _RecurringMatch(span=m.span(), period=period)
    return None  # pragma: no cover - 정규식 그룹과 항상 동기화됨


def _find_relative_duration(text: str) -> _DurationMatch | None:
    m = _REL_DURATION_RE.search(text)
    if not m:
        return None
    if m.group("n1"):
        n = int(m.group("n1"))
        minutes = n if m.group("unit1") == "분" else n * 60
    else:
        n = int(m.group("n2"))
        unit = m.group("unit2").lower()
        minutes = n * 60 if unit.startswith(("hour", "hr")) else n
    return _DurationMatch(span=m.span(), minutes=minutes)


def _find_duration_token(text: str) -> _DurationMatch | None:
    m = _DURATION_TOKEN_RE.search(text)
    if not m:
        return None
    n = int(m.group("n"))
    minutes = n if m.group("unit") == "분" else n * 60
    return _DurationMatch(span=m.span(), minutes=minutes)


def _find_date_token(text: str, today: date) -> _DateMatch | None:
    m = _RELATIVE_DAY_RE.search(text)
    if m:
        matched = m.group(0)
        key = matched if matched in ("오늘", "내일", "모레", "글피") else matched.lower()
        offset = {"오늘": 0, "today": 0, "내일": 1, "tomorrow": 1, "모레": 2, "글피": 3}[key]
        return _DateMatch(span=m.span(), value=today + timedelta(days=offset), needs_time_check=False)

    m = _REL_N_DAYS_RE.search(text)
    if m:
        n = int(m.group("n"))
        return _DateMatch(span=m.span(), value=today + timedelta(days=n), needs_time_check=False)

    m = _WEEKDAY_RE.search(text)
    if m:
        next_week = bool(m.group("nextweek"))
        wd = m.group("wd")
        idx = _WEEKDAY_KO[wd[0]] if wd[0] in _WEEKDAY_KO and wd.endswith("요일") else _WEEKDAY_EN[wd.lower()]
        value, needs_check = _resolve_weekday(idx, today, next_week)
        return _DateMatch(span=m.span(), value=value, needs_time_check=needs_check)

    m = _YMD_RE.search(text)
    if m:
        try:
            value = date(int(m.group("y")), int(m.group("m")), int(m.group("d")))
        except ValueError:
            return None
        return _DateMatch(span=m.span(), value=value, needs_time_check=False)

    m = _MD_KOR_RE.search(text)
    if m:
        value = _resolve_month_day(int(m.group("m")), int(m.group("d")), today)
        if value is None:
            return None
        return _DateMatch(span=m.span(), value=value, needs_time_check=False)

    m = _MD_SLASH_RE.search(text)
    if m:
        value = _resolve_month_day(int(m.group("m")), int(m.group("d")), today)
        if value is None:
            return None
        return _DateMatch(span=m.span(), value=value, needs_time_check=False)

    return None


def _minute_from_groups(half: str | None, minute: str | None) -> int:
    if half:
        return 30
    if minute:
        return int(minute)
    return 0


def _find_time_token(text: str) -> _TimeMatch | None:
    m = _RANGE_TIME_RE.search(text)
    if m:
        mod1 = m.group("mod1")
        mod2 = m.group("mod2") or mod1
        raw_h1 = _hour_value(m.group("h1"))
        raw_h2 = _hour_value(m.group("h2"))
        h1, flag1 = _apply_ampm(raw_h1, mod1)
        if mod2 is not None:
            h2, flag2 = _apply_ampm(raw_h2, mod2)
        elif raw_h1 >= 13 or raw_h1 == 0:
            # 첫 시각이 이미 24시간제로 명확하면(예: "23시~1시") 두 번째 시각도 문맥상
            # 리터럴로 취급한다 — 그렇지 않으면 자정 넘김 범위의 종료 시각에 엉뚱하게
            # 무수식어 기본값(PM)이 적용돼 "1시"가 13시로 둔갑하는 버그가 생긴다.
            h2, flag2 = raw_h2, False
        else:
            h2, flag2 = _apply_ampm(raw_h2, None)
        min1 = _minute_from_groups(m.group("half1"), m.group("min1"))
        min2 = _minute_from_groups(m.group("half2"), m.group("min2"))
        return _TimeMatch(
            span=m.span(),
            hour=h1,
            minute=min1,
            end_hour=h2,
            end_minute=min2,
            ampm_flag=flag1 or flag2,
        )

    m = _SINGLE_TIME_KO_RE.search(text)
    if m:
        hour, flag = _apply_ampm(_hour_value(m.group("hour")), m.group("mod"))
        minute = _minute_from_groups(m.group("half"), m.group("min"))
        return _TimeMatch(span=m.span(), hour=hour, minute=minute, end_hour=None, end_minute=None, ampm_flag=flag)

    m = _COLON_TIME_RE.search(text)
    if m:
        hour, flag = _apply_ampm(int(m.group("hour")), m.group("mod"))
        minute = int(m.group("min"))
        return _TimeMatch(span=m.span(), hour=hour, minute=minute, end_hour=None, end_minute=None, ampm_flag=flag)

    return None


# ---------------------------------------------------------------------------
# 제목 재구성
# ---------------------------------------------------------------------------


def _remove_spans(text: str, spans: list[tuple[int, int]]) -> str:
    ordered = sorted(spans)
    pieces: list[str] = []
    cursor = 0
    for start, end in ordered:
        if start < cursor:
            continue  # 겹치는 구간은 이미 처리됨(방어적)
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    title = re.sub(r"\s+", " ", "".join(pieces)).strip()
    return title


# ---------------------------------------------------------------------------
# 종류별 Draft 조립
# ---------------------------------------------------------------------------


def _build_plan(text: str, date_tok: _DateMatch, time_tok: _TimeMatch, now: datetime) -> Draft:
    start_date = date_tok.value
    start_dt = datetime.combine(start_date, dt_time(hour=time_tok.hour, minute=time_tok.minute))

    if date_tok.needs_time_check and start_dt <= now:
        start_date = start_date + timedelta(days=7)
        start_dt = datetime.combine(start_date, dt_time(hour=time_tok.hour, minute=time_tok.minute))

    flags: set[str] = set()
    if time_tok.ampm_flag:
        flags.add("ampm")

    spans = [date_tok.span, time_tok.span]
    if time_tok.end_hour is not None:
        end_dt = datetime.combine(start_date, dt_time(hour=time_tok.end_hour, minute=time_tok.end_minute or 0))
    else:
        dur_tok = _find_duration_token(text)
        if dur_tok is not None:
            end_dt = start_dt + timedelta(minutes=dur_tok.minutes)
            spans.append(dur_tok.span)
        else:
            end_dt = start_dt + timedelta(hours=1)

    if end_dt <= start_dt:
        end_dt += timedelta(days=1)

    if start_dt <= now:
        flags.add("past_time")

    title = _remove_spans(text, spans)
    return Draft(
        kind=Kind.PLAN,
        title=title or text,
        start=start_dt,
        end=end_dt,
        period=None,
        duration_minutes=None,
        ambiguity_flags=frozenset(flags),
    )


def _build_alarm(text: str, time_tok: _TimeMatch, now: datetime) -> Draft:
    today = now.date()
    start_dt = datetime.combine(today, dt_time(hour=time_tok.hour, minute=time_tok.minute))
    if start_dt <= now:
        start_dt += timedelta(days=1)

    flags = {"alarm_or_plan"}
    if time_tok.ampm_flag:
        flags.add("ampm")

    title = _remove_spans(text, [time_tok.span])
    return Draft(
        kind=Kind.ALARM,
        title=title or text,
        start=start_dt,
        end=None,
        period=None,
        duration_minutes=None,
        ambiguity_flags=frozenset(flags),
    )


# ---------------------------------------------------------------------------
# 공개 API
# ---------------------------------------------------------------------------


def parse(text: str, now: datetime) -> Draft:
    """한 줄 텍스트를 초안으로 분류합니다. `now` 이외의 시계열은 조회하지 않는 결정적 함수.

    §1 우선순위(첫 매치 승리)를 그대로 따른다: 상대 지속시간(반복 없을 때만) → 반복 →
    (날짜+시각) → 날짜만 → 시각만 → 무신호.
    """
    stripped = text.strip()
    if not stripped:
        return Draft(
            kind=Kind.TASK,
            title=text,
            start=None,
            end=None,
            period="daily",
            duration_minutes=None,
            ambiguity_flags=frozenset(),
        )

    today = now.date()

    recurring = _find_recurring(stripped)
    rel_dur = _find_relative_duration(stripped)

    if rel_dur is not None and recurring is None:
        title = _remove_spans(stripped, [rel_dur.span])
        return Draft(
            kind=Kind.TIMER,
            title=title or stripped,
            start=None,
            end=None,
            period=None,
            duration_minutes=rel_dur.minutes,
            ambiguity_flags=frozenset(),
        )

    if recurring is not None:
        remainder = _remove_spans(stripped, [recurring.span])
        flags: set[str] = set()
        if _find_time_token(remainder) or _find_relative_duration(remainder):
            flags.add("recurring_time_kept_in_title")
        return Draft(
            kind=Kind.RECURRING,
            title=remainder or stripped,
            start=None,
            end=None,
            period=recurring.period,
            duration_minutes=None,
            ambiguity_flags=frozenset(flags),
        )

    date_tok = _find_date_token(stripped, today)
    time_tok = _find_time_token(stripped)

    if date_tok is not None and time_tok is not None:
        return _build_plan(stripped, date_tok, time_tok, now)

    if date_tok is not None:
        title = _remove_spans(stripped, [date_tok.span])
        return Draft(
            kind=Kind.NOTE,
            title=title or stripped,
            start=datetime.combine(date_tok.value, dt_time.min),
            end=None,
            period=None,
            duration_minutes=None,
            ambiguity_flags=frozenset(),
        )

    if time_tok is not None:
        return _build_alarm(stripped, time_tok, now)

    return Draft(
        kind=Kind.TASK,
        title=stripped,
        start=None,
        end=None,
        period="daily",
        duration_minutes=None,
        ambiguity_flags=frozenset(),
    )
