"""Motorsport UK events, via the Sport80 public event locator.

Motorsport UK runs its event/permit calendar on the Sport80 platform at
motorsportuk.sport80.com. The event locator page is an Inertia.js app: sending
the `X-Inertia: true` header returns the page data as JSON instead of HTML.
Each event includes name, date(s), latitude/longitude, full location (with
postcode), organiser and a details URL.

Results are paginated (16 per page). We request from today's date forward and
walk the pages. Discipline is inferred from the event name, since Sport80
doesn't expose a discipline field on the locator payload.
"""
from __future__ import annotations

import re
from datetime import date

from ..classify import classify
from ..geo import extract_postcode
from ..models import Discipline, Event
from .base import Adapter

BASE = "https://motorsportuk.sport80.com"
FIND_URL = f"{BASE}/pub/e_locator/events/find"

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _parse_date(part: dict | None, fallback_year: int | None = None) -> date | None:
    if not part:
        return None
    try:
        day = int(part["day"])
        month = MONTHS.get(str(part["month"]).strip().lower()[:3])
        year = int(part.get("year") or fallback_year or 0)
        if not month or not year:
            return None
        return date(year, month, day)
    except (KeyError, ValueError, TypeError):
        return None


class MotorsportUKAdapter(Adapter):
    key = "msuk"
    name = "Motorsport UK"

    #: Safety cap so a change upstream can't make us loop forever.
    max_pages = 120

    def _inertia_headers(self) -> dict:
        return {
            "User-Agent": "Mozilla/5.0",
            "X-Inertia": "true",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/html, application/xhtml+xml",
        }

    def fetch(self) -> list[Event]:
        from_date = date.today().isoformat()
        events: list[Event] = []
        seen_ids: set[str] = set()

        with self.make_client() as client:
            page = 1
            total_pages = 1
            while page <= total_pages and page <= self.max_pages:
                resp = client.get(
                    FIND_URL,
                    params={"from_date": from_date, "page": page},
                    headers=self._inertia_headers(),
                )
                resp.raise_for_status()
                data = resp.json()
                props = data.get("props", {})
                total_pages = int(props.get("total_pages") or 1)
                items = props.get("events") or []
                if not items:
                    break
                for item in items:
                    ev = self._build(item, seen_ids)
                    if ev:
                        events.append(ev)
                page += 1

        return events

    def parse_pages(self, pages: list[dict]) -> list[Event]:
        """Parse a list of Inertia JSON payloads into events (for tests)."""
        events: list[Event] = []
        seen_ids: set[str] = set()
        for data in pages:
            items = (data.get("props", {}) or {}).get("events") or []
            for item in items:
                ev = self._build(item, seen_ids)
                if ev:
                    events.append(ev)
        return events

    def _build(self, item: dict, seen_ids: set[str]) -> Event | None:
        eid = str(item.get("id") or "")
        if not eid or eid in seen_ids:
            return None

        name = (item.get("name") or "").strip()
        if not name:
            return None

        d = item.get("date") or {}
        start = _parse_date(d)
        if not start:
            return None
        end = _parse_date(d.get("to_date"), fallback_year=start.year)
        if end and end <= start:
            end = None

        location = (item.get("location") or "").strip() or None
        postcode = extract_postcode(location or "")

        lat = item.get("latitude")
        lon = item.get("longitude")
        # Sport80 uses 0/0 as "unknown"; treat that as no coordinates so the
        # ingest step geocodes from the postcode instead.
        if not lat or not lon:
            lat = lon = None

        seen_ids.add(eid)
        return Event(
            source=self.key,
            source_id=eid,
            title=name,
            discipline=classify(name),
            start_date=start,
            end_date=end,
            venue=location,
            postcode=postcode,
            latitude=lat,
            longitude=lon,
            organiser=item.get("organiser_name") or None,
            url=item.get("full_details_url") or item.get("main_action_url"),
            description=None,
        )
