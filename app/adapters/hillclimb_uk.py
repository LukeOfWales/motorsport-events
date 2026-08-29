"""UK hill climb fixtures from hillclimb.uk.

This site publishes a single page per season (e.g. /2026-hillclimb-dates/)
that aggregates dates for all the major UK speed hill climb venues — Prescott,
Shelsley Walsh, Loton Park, Gurston Down, Harewood, Doune, Wiscombe Park and
more. It's far more reliable than scraping each venue's own (Wix / page-builder)
site individually.

Page structure (per venue):

    Prescott 2026 Hillclimb Dates          <- venue section heading
    29 March                               <- single-day date
    26/27 April : British / Midland        <- date range + championship note

We parse the per-venue sections (ignoring the championship summary sections at
the top, which duplicate the same dates in a messier form) and geocode by
venue name using a lookup of known venue postcodes.
"""
from __future__ import annotations

import re
from datetime import date

from ..geo import extract_postcode
from ..models import Discipline, Event
from .base import Adapter

BASE = "https://hillclimb.uk"

MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Known hill climb / speed venues -> (full venue name, postcode) for geocoding.
# Postcodes are the venue location so distance-from-home works.
VENUE_INFO = {
    "prescott": ("Prescott Hill Climb, Gotherington, Gloucestershire", "GL52 9RD"),
    "shelsley walsh": ("Shelsley Walsh, Worcestershire", "WR6 6RP"),
    "loton park": ("Loton Park, Alberbury, Shropshire", "SY5 9AN"),
    "gurston down": ("Gurston Down, Broad Chalke, Wiltshire", "SP5 5DR"),
    "gurston": ("Gurston Down, Broad Chalke, Wiltshire", "SP5 5DR"),
    "harewood": ("Harewood Hill Climb, Leeds", "LS17 9LG"),
    "doune": ("Doune Hill Climb, Stirling", "FK16 6BX"),
    "wiscombe park": ("Wiscombe Park, Southleigh, Devon", "EX24 6JF"),
    "barbon manor": ("Barbon Manor, Cumbria", "LA6 2LL"),
    "bouley bay": ("Bouley Bay, Jersey", None),
    "val des terres": ("Val des Terres, Guernsey", None),
    "craigantlet": ("Craigantlet, County Down", "BT23 4TB"),
    "manx classic": ("Manx Classic, Isle of Man", None),
}

VENUE_HEAD = re.compile(r"^(.+?)\s+20\d{2}\s+Hillclimb Dates$", re.IGNORECASE)
# A date line: "29 March" or "26/27 April" optionally "... : championship note"
DATE_LINE = re.compile(
    r"^(\d{1,2})(?:/(\d{1,2}))?\s+"
    r"([A-Za-z]+)"
    r"(?:\s*[:\-]\s*(.+))?$"
)


class HillclimbUKAdapter(Adapter):
    key = "hillclimb_uk"
    name = "UK Hill Climb Fixtures (hillclimb.uk)"

    def _fetch_page(self, client, year: int):
        resp = client.get(f"{BASE}/{year}-hillclimb-dates/")
        if resp.status_code == 200:
            return resp.text
        return None

    def fetch(self) -> list[Event]:
        year = date.today().year
        html = None
        used_year = year
        with self.make_client() as client:
            # Try current year, then next year (published early), then last year.
            for y in (year, year + 1, year - 1):
                page = self._fetch_page(client, y)
                if page:
                    html, used_year = page, y
                    break
        if html is None:
            return []
        return self.parse(html, used_year)

    def parse(self, html: str, used_year: int) -> list[Event]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        main = soup.find("main") or soup.find("article") or soup.body
        if main is None:
            return []

        text = main.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        events: list[Event] = []
        current_venue: str | None = None
        idx = 0

        for line in lines:
            head = VENUE_HEAD.match(line)
            if head:
                current_venue = head.group(1).strip()
                continue
            if current_venue is None:
                continue

            m = DATE_LINE.match(line)
            if not m:
                # A non-date line ends the current venue block until the next
                # venue heading (avoids parsing stray prose).
                continue

            start_day = int(m.group(1))
            end_day = int(m.group(2)) if m.group(2) else None
            month_name = m.group(3).lower()
            note = (m.group(4) or "").strip()
            month = MONTHS.get(month_name)
            if not month:
                continue

            try:
                start = date(used_year, month, start_day)
            except ValueError:
                continue
            end = None
            if end_day:
                try:
                    cand = date(used_year, month, end_day)
                    if cand > start:
                        end = cand
                except ValueError:
                    end = None

            ev = self._build(current_venue, start, end, note, idx)
            if ev:
                events.append(ev)
                idx += 1

        return events

    def _build(self, venue: str, start: date, end: date | None,
               note: str, idx: int) -> Event | None:
        key = venue.lower().strip()
        full_name, postcode = VENUE_INFO.get(key, (venue, None))
        if postcode is None:
            postcode = extract_postcode(full_name)

        # Championship note shapes the title, e.g. "British / Midland".
        champ = re.sub(r"\(.*?\)", "", note).strip(" /") if note else ""
        title = f"{venue} Hill Climb"
        if champ:
            title = f"{venue} Hill Climb ({champ})"

        return Event(
            source=self.key,
            source_id=f"{start.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', key)}",
            title=title,
            discipline=Discipline.HILLCLIMB,
            start_date=start,
            end_date=end,
            venue=full_name,
            postcode=postcode,
            organiser=self.name,
            url=f"{BASE}/",
            description=note or None,
        )
