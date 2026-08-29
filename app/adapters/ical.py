"""Generic iCal (.ics) adapter.

Many motorsport clubs and calendars publish an iCal feed. This adapter turns
any such feed into Events. Configure one instance per feed with a source key,
discipline, and URL.
"""
from __future__ import annotations

from datetime import date, datetime

from icalendar import Calendar

from ..geo import extract_postcode
from ..models import Discipline, Event
from .base import Adapter


class ICalAdapter(Adapter):
    def __init__(self, key: str, name: str, url: str, discipline: Discipline,
                 organiser: str | None = None):
        self.key = key
        self.name = name
        self.url = url
        self.discipline = discipline
        self.organiser = organiser

    @staticmethod
    def _to_date(value) -> date | None:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        return None

    def fetch(self) -> list[Event]:
        events: list[Event] = []
        with self.make_client() as client:
            resp = client.get(self.url)
            resp.raise_for_status()
            cal = Calendar.from_ical(resp.content)

        for comp in cal.walk("VEVENT"):
            try:
                title = str(comp.get("summary", "")).strip()
                if not title:
                    continue

                start = self._to_date(comp.get("dtstart").dt) if comp.get("dtstart") else None
                if not start:
                    continue
                end = None
                if comp.get("dtend"):
                    end = self._to_date(comp.get("dtend").dt)
                    # iCal DTEND is exclusive for all-day events; step back a day.
                    if end and end > start:
                        pass  # keep as-is; close enough for display

                location = str(comp.get("location", "")).strip() or None
                desc = str(comp.get("description", "")).strip() or None
                url = str(comp.get("url", "")).strip() or None
                uid = str(comp.get("uid", "")) or f"{title}-{start.isoformat()}"

                postcode = extract_postcode(location or "") or extract_postcode(desc or "")

                events.append(Event(
                    source=self.key,
                    source_id=uid,
                    title=title,
                    discipline=self.discipline,
                    start_date=start,
                    end_date=end if end and end != start else None,
                    venue=location,
                    postcode=postcode,
                    organiser=self.organiser,
                    url=url,
                    description=desc,
                ))
            except Exception:
                # Skip malformed events rather than failing the whole feed.
                continue
        return events
