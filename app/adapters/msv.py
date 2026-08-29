"""MotorSport Vision (MSV) race calendar from msv.com/calendar.

MSV operates Brands Hatch, Oulton Park, Snetterton, Cadwell Park, Donington
Park and Circuito de Navarra. The calendar is server-rendered: each event is a
`.calendar-item` with four text lines (title, date/range, circuit, config) and
a "Book Now" link to the circuit's booking page. The booking URL carries the
year and month, e.g. .../2026/august/gold-cup.

Date formats:
    "Sat 29 Aug"                  single day
    "Sat 29 - Mon 31 Aug"         range within one month
    "Sat 31 Oct - Sun 01 Nov"     range across two months
"""
from __future__ import annotations

import re
from datetime import date

from ..classify import classify
from ..models import Discipline, Event
from .base import Adapter

URL = "https://www.msv.com/calendar"

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}

# MSV circuits -> postcode for geocoding. Keyed by the base venue name (config
# suffix like "(GP)" / "(300)" is stripped before lookup).
VENUE_POSTCODES = {
    "brands hatch": "DA3 8NG",
    "oulton park": "CW6 9BW",
    "snetterton": "NR16 2JU",
    "cadwell park": "LN11 9SE",
    "donington park": "DE74 2RP",
    "circuito de navarra": None,   # Spain — no UK postcode
}

# Circuit-race discipline classification is handled by app.classify.classify().

DATE_RE = re.compile(
    r"(?:[A-Za-z]{3}\s+)?(\d{1,2})(?:\s+([A-Za-z]{3,}))?"       # start day + optional start month
    r"(?:\s*[–\-]\s*(?:[A-Za-z]{3}\s+)?(\d{1,2})\s+([A-Za-z]{3,}))?"  # optional end day + month
    r"(?:\s+([A-Za-z]{3,}))?"                                    # trailing month (single-day case)
)


class MSVAdapter(Adapter):
    key = "msv"
    name = "MotorSport Vision (MSV Circuits)"

    def fetch(self) -> list[Event]:
        with self.make_client() as client:
            resp = client.get(URL)
            resp.raise_for_status()
            html = resp.text
        return self.parse(html)

    def parse(self, html: str) -> list[Event]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        items = soup.select(".calendar-item")
        events: list[Event] = []
        seen: set[str] = set()

        for it in items:
            lines = [ln.strip() for ln in it.get_text("\n", strip=True).split("\n") if ln.strip()]
            # Drop the "Book Now" call-to-action line if present (list layout).
            lines = [ln for ln in lines if ln.lower() != "book now"]
            if len(lines) < 3:
                continue

            # The item appears in two layouts: grid [title, date, venue, config]
            # and list [date, title, "venue (config)"]. Find the date line by
            # pattern rather than assuming its position.
            date_idx = next(
                (i for i, ln in enumerate(lines) if self._looks_like_date(ln)),
                None,
            )
            if date_idx is None:
                continue
            date_text = lines[date_idx]
            other = [ln for i, ln in enumerate(lines) if i != date_idx]
            if not other:
                continue
            # Grid: [title, venue, config]. List: [title, "venue (config)"].
            title = other[0]
            venue, config = self._split_venue_config(other[1:])

            link = it.select_one("a[href]")
            href = link.get("href") if link else None
            year, month_from_url = self._year_month_from_url(href)
            if year is None:
                continue

            start, end = self._parse_dates(date_text, year, month_from_url)
            if not start:
                continue

            venue_full = venue
            if config and config.lower() not in ("national", "international"):
                venue_full = f"{venue} ({config})"
            base_venue = venue.lower().strip()
            postcode = VENUE_POSTCODES.get(base_venue)

            # De-duplicate the grid + list views (same event appears twice).
            key = f"{start.isoformat()}|{title.lower()}|{base_venue}"
            if key in seen:
                continue
            seen.add(key)

            events.append(Event(
                source=self.key,
                source_id=key.replace(" ", "-")[:80],
                title=title,
                discipline=classify(title),
                start_date=start,
                end_date=end,
                venue=venue_full,
                postcode=postcode,
                organiser=self.name,
                url=href or URL,
                description=f"{venue}{f' ({config})' if config else ''}",
            ))

        return events

    _DATE_HINT = re.compile(
        r"\b\d{1,2}\b.*\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)",
        re.IGNORECASE,
    )

    @classmethod
    def _looks_like_date(cls, text: str) -> bool:
        """True for lines like 'Sat 29 Aug' or 'Sat 31 Oct - Sun 01 Nov'."""
        return bool(cls._DATE_HINT.search(text))

    @staticmethod
    def _split_venue_config(parts: list[str]) -> tuple[str, str | None]:
        """From the non-title, non-date lines, return (venue, config).

        Grid layout gives [venue, config] as two lines; list layout gives a
        single 'Venue (config)' line.
        """
        if not parts:
            return "", None
        if len(parts) >= 2:
            return parts[0], (parts[1].strip("()") or None)
        m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", parts[0])
        if m:
            return m.group(1).strip(), (m.group(2).strip() or None)
        return parts[0], None

    @staticmethod
    def _year_month_from_url(href: str | None) -> tuple[int | None, int | None]:
        if not href:
            return None, None
        m = re.search(r"/(20\d{2})/([a-z]+)/", href, re.IGNORECASE)
        if not m:
            m2 = re.search(r"/(20\d{2})/", href)
            return (int(m2.group(1)) if m2 else None), None
        return int(m.group(1)), MONTHS.get(m.group(2).lower())

    def _parse_dates(self, text: str, year: int, url_month: int | None):
        """Parse '29 Aug', '29 - 31 Aug', '31 Oct - 01 Nov' into dates."""
        # Collect (day, month) tokens in order.
        tokens = re.findall(r"(\d{1,2})(?:\s+([A-Za-z]{3,}))?", text)
        # Resolve months left-to-right; a day without a month inherits the
        # next month found to its right (matches how MSV writes ranges).
        parsed: list[tuple[int, int | None]] = []
        for day_s, mon_s in tokens:
            month = MONTHS.get(mon_s.lower()) if mon_s else None
            parsed.append((int(day_s), month))
        if not parsed:
            return None, None

        # Fill missing months: back-fill from the right; final fallback = URL month.
        last_month = url_month
        for i in range(len(parsed) - 1, -1, -1):
            d, mth = parsed[i]
            if mth is None:
                mth = last_month
                parsed[i] = (d, mth)
            else:
                last_month = mth

        def make(day: int, mth: int | None) -> date | None:
            if not mth:
                return None
            yr = year
            # If the range rolls from Dec into Jan, bump the year for Jan.
            return self._safe_date(yr, mth, day)

        start = make(*parsed[0])
        end = None
        if len(parsed) > 1:
            end = make(*parsed[-1])
            # Cross-year rollover (Dec -> Jan).
            if start and end and end < start and parsed[0][1] == 12 and parsed[-1][1] == 1:
                end = self._safe_date(year + 1, 1, parsed[-1][0])
            if end and (start is None or end <= start):
                end = None
        return start, end

    @staticmethod
    def _safe_date(year: int, month: int, day: int) -> date | None:
        try:
            return date(year, month, day)
        except ValueError:
            return None
