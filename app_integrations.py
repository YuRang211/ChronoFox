from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from pathlib import Path


def _ics_escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _date_text(value: date) -> str:
    return value.strftime("%Y%m%d")


def _datetime_text(value: datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def _parse_datetime(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


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
        "PRODID:-//Fox Calendar//Desktop Calendar//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]

    for day_text, schedule in sorted(data.setdefault("schedules", {}).items()):
        try:
            day = date.fromisoformat(day_text)
        except ValueError:
            continue
        title = next((line.strip() for line in schedule.splitlines() if line.strip()), "Fox Calendar 일정")
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

    for plan in data.setdefault("plans", []):
        title = str(plan.get("title", "")).strip()
        if not title:
            continue
        start = _parse_datetime(str(plan.get("start", "")))
        end = _parse_datetime(str(plan.get("end", "")))
        if start is None:
            continue
        plan_id = str(plan.get("id", id(plan)))
        lines.extend(
            [
                "BEGIN:VEVENT",
                f"UID:fox-calendar-plan-{plan_id}@fox-calendar",
                f"DTSTAMP:{now}",
            ]
        )
        if plan.get("kind") == "long":
            end_day = (end or start).date() + timedelta(days=1)
            lines.append(f"DTSTART;VALUE=DATE:{_date_text(start.date())}")
            lines.append(f"DTEND;VALUE=DATE:{_date_text(end_day)}")
        else:
            lines.append(f"DTSTART:{_datetime_text(start)}")
            lines.append(f"DTEND:{_datetime_text(end or start)}")
        lines.extend(
            [
                f"SUMMARY:{_ics_escape(title)}",
                f"DESCRIPTION:{_ics_escape(str(plan.get('description', '')).strip())}",
                "END:VEVENT",
            ]
        )

    lines.append("END:VCALENDAR")
    destination.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    return destination
