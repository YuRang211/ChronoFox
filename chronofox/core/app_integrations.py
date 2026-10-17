"""일정/계획 데이터를 Google Calendar·Outlook에서 가져올 수 있는 ICS 파일로 내보내는 모듈."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from chronofox.core.app_storage import write_text_atomic


def _ics_escape(value: str) -> str:
    # 홀로 남은 CR이 원문 그대로 출력되지 않도록 줄바꿈을 먼저 LF로 통일한다.
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def _fold_line(line: str) -> str:
    """RFC 5545 §3.1에 따라 내용 줄을 75옥텟 이하로 접는다(다중 바이트 문자는 쪼개지 않음)."""
    if len(line.encode("utf-8")) <= 75:
        return line
    parts: list[str] = []
    current = ""
    size = 0
    limit = 75
    for char in line:
        char_size = len(char.encode("utf-8"))
        if size + char_size > limit:
            parts.append(current)
            current, size, limit = "", 0, 74  # 이어지는 줄은 앞 공백 1옥텟을 제외한다.
        current += char
        size += char_size
    parts.append(current)
    return "\r\n ".join(parts)


def _date_text(value: date) -> str:
    return value.strftime("%Y%m%d")


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is not None:
        return value.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    return value.strftime("%Y%m%dT%H%M%S")


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _timed_end(start: datetime, end: datetime | None) -> datetime:
    """종료가 시작보다 빠르거나 같거나 없는 시간 계획도 유효한 DTEND가 되도록 보정한다."""
    if end is not None and end > start:
        return end
    if end is not None and end.date() == start.date() and end.time() < start.time():
        return end + timedelta(days=1)  # 같은 날 종료 시각이 더 이르면 자정을 넘기는 일정으로 본다.
    return start + timedelta(hours=1)


def _plan_export_ids(plans: list[dict]) -> list[str]:
    """기존 ID를 보존하고 ID 없는 계획에만 안정적인 내보내기 ID를 부여합니다."""
    occurrences: dict[str, int] = {}
    export_ids = []
    for plan in plans:
        existing = plan.get("id")
        if existing is not None and str(existing).strip():
            export_ids.append(str(existing))
            continue
        canonical = {key: plan.get(key, "") for key in ("kind", "start", "end", "title", "description")}
        payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
        base_id = f"sha256-{digest}"
        occurrences[base_id] = occurrences.get(base_id, 0) + 1
        occurrence = occurrences[base_id]
        export_ids.append(base_id if occurrence == 1 else f"{base_id}-{occurrence}")
    return export_ids


def export_ics(data: dict, destination: Path) -> Path:
    """Google Calendar와 Microsoft Outlook이 가져올 수 있는 ICS 파일을 만듭니다."""
    destination = Path(destination)
    if destination.suffix.lower() != ".ics":
        destination = destination.with_suffix(".ics")
    destination.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ChronoFox//Desktop Calendar//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for day_text, schedule in sorted(data.get("schedules", {}).items()):
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        title = next((line.strip() for line in schedule.splitlines() if line.strip()), "ChronoFox 일정")
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:fox-calendar-schedule-{day_text}@fox-calendar",
                f"DTSTAMP:{now}",
                f"DTSTART;VALUE=DATE:{_date_text(day)}",
                f"SUMMARY:{_ics_escape(title)}",
                f"DESCRIPTION:{_ics_escape(schedule.strip())}",
                "END:VEVENT",
            ]
        )

    plans = data.get("plans", [])
    for plan, plan_id in zip(plans, _plan_export_ids(plans), strict=True):
        title = str(plan.get("title", "")).strip()
        if not title:
            continue
        start = _parse_datetime(str(plan.get("start", "")))
        end = _parse_datetime(str(plan.get("end", "")))
        if start is None:
            continue
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:fox-calendar-plan-{plan_id}@fox-calendar",
                f"DTSTAMP:{now}",
            ]
        )
        if plan.get("kind") == "long":
            end_day = max(start.date(), (end or start).date()) + timedelta(days=1)
            lines.append(f"DTSTART;VALUE=DATE:{_date_text(start.date())}")
            lines.append(f"DTEND;VALUE=DATE:{_date_text(end_day)}")
        else:
            # 원래 날짜를 유지해야 자정을 넘기는 종료 시각 보정이 달라지지 않는다.
            # 혼합 데이터의 naive 시각만 로컬로 해석하고, 출력 시 UTC로 변환한다.
            if start.tzinfo is not None or (end is not None and end.tzinfo is not None):
                if start.tzinfo is None:
                    start = start.astimezone()
                if end is not None and end.tzinfo is None:
                    end = end.astimezone()
            lines.append(f"DTSTART:{_datetime_text(start)}")
            lines.append(f"DTEND:{_datetime_text(_timed_end(start, end))}")
        lines.extend(
            [
                f"SUMMARY:{_ics_escape(title)}",
                f"DESCRIPTION:{_ics_escape(str(plan.get('description', '')).strip())}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    write_text_atomic(destination, "\r\n".join(_fold_line(line) for line in lines) + "\r\n")
    return destination
