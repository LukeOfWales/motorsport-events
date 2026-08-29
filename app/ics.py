"""iCalendar (.ics) serialisation for events.

Produces RFC 5545 VCALENDAR text for one or more events. All-day events are
emitted with DATE values (no times), since our sources give dates, not times.
DTEND for all-day events is exclusive per the spec, so we add one day to the
event's (inclusive) end date.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from .models import Event

PRODID = "-//motorsport-events//EN"


def _fold(line: str) -> str:
    """Fold long lines to <=75 octets per RFC 5545 (simple char-based fold)."""
    if len(line) <= 75:
        return line
    parts = [line[:75]]
    rest = line[75:]
    while rest:
        parts.append(" " + rest[:74])
        rest = rest[74:]
    return "\r\n".join(parts)


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
        .replace("\r", "")
    )


def _dt_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _event_lines(e: Event) -> list[str]:
    start = e.start_date
    # All-day DTEND is exclusive: use end_date + 1 day (or start + 1 for
    # single-day events).
    end_inclusive = e.end_date or start
    dtend = end_inclusive + timedelta(days=1)

    location_parts = [p for p in (e.venue, e.postcode) if p]
    # Avoid repeating the postcode when it's already in the venue string.
    if e.venue and e.postcode and e.postcode.replace(" ", "").upper() in \
            e.venue.replace(" ", "").upper():
        location_parts = [e.venue]
    location = ", ".join(location_parts)

    summary = e.title
    desc_parts = []
    if e.organiser:
        desc_parts.append(f"Organiser: {e.organiser}")
    if e.distance_km is not None:
        desc_parts.append(f"~{round(e.distance_km)} km away")
    if e.description:
        desc_parts.append(e.description)
    if e.url:
        desc_parts.append(e.url)
    description = "\n".join(desc_parts)

    lines = [
        "BEGIN:VEVENT",
        f"UID:{e.uid}@motorsport-events",
        f"DTSTAMP:{_dt_stamp()}",
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{dtend.strftime('%Y%m%d')}",
        f"SUMMARY:{_escape(summary)}",
    ]
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if e.url:
        lines.append(f"URL:{_escape(e.url)}")
    lines.append("END:VEVENT")
    return lines


def build_ics(events: list[Event], name: str = "Motorsport Events") -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for e in events:
        lines.extend(_event_lines(e))
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(ln) for ln in lines) + "\r\n"
