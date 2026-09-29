"""일정/계획 데이터를 Google Calendar·Outlook에서 가져올 수 있는 ICS 파일로 내보내는 모듈."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from chronofox.core.app_storage import write_text_atomic


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
    write_text_atomic(destination, "\r\n".join(lines) + "\r\n")
    return destination
