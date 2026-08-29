"""South Wales Land Rover Club (swlrc.co.uk) events adapter.

The events page is a hand-maintained WordPress list, not a structured
calendar. Layout:

    <h2>2026</h2>                          (year)
    <h3>FEBRUARY</h3>                      (month, sometimes split across tags)
    <p><strong>LRM Autojumble</strong> Sun 1 st</p>   (title + day/date line)
    <li>Three Counties Showground ... WR13 6NW</li>    (venue + postcode)
    <li>Camping available from Fri 31 st</li>          (extra notes)
    <li>https://example.org</li>                       (optional URL)

We walk the content in document order, tracking the current year/month, and
build an event each time we hit a title paragraph, attaching the following
list items until the next title/month heading.
"""
from __future__ import annotations

import re
from datetime import date

from ..geo import extract_postcode
from ..models import Discipline, Event
from .base import Adapter

URL = "https://swlrc.co.uk/events/"

MONTHS = {
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9, "OCTOBER": 10, "NOVEMBER": 11,
    "DECEMBER": 12,
}

# "Sun 1 st", "Sat 25 th", "Fri 24 th" -> capture weekday + day number.
DAY_RE = re.compile(
    r"(Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*\s+(\d{1,2})\s*(st|nd|rd|th)?",
    re.IGNORECASE,
)
URL_RE = re.compile(r"https?://\S+")


def _clean(text: str) -> str:
    # Normalise non-breaking spaces and collapse whitespace.
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _parse_month_heading(text: str) -> int | None:
    key = re.sub(r"[^A-Z]", "", text.upper())
    return MONTHS.get(key)


class SWLRCAdapter(Adapter):
    key = "swlrc"
    name = "South Wales Land Rover Club"

    def fetch(self) -> list[Event]:
        html = None
        last_exc: Exception | None = None
        with self.make_client() as client:
            for attempt in range(3):
                try:
                    resp = client.get(URL)
                    resp.raise_for_status()
                    html = resp.text
                    break
                except Exception as exc:  # network/timeout — retry a couple of times
                    last_exc = exc
        if html is None:
            raise last_exc or RuntimeError("failed to fetch SWLRC events")
        return self.parse(html)

    def parse(self, html: str) -> list[Event]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        main = soup.find("main") or soup.body
        if main is None:
            return []

        year: int | None = None
        month: int | None = None
        events: list[Event] = []
        idx = 0

        # Current event being assembled (from a title <p>), plus its notes.
        current: dict | None = None

        def finalise(cur: dict | None) -> None:
            nonlocal idx
            if not cur or cur.get("skip"):
                return
            ev = self._build_event(cur, idx)
            if ev is not None:
                events.append(ev)
                idx += 1

        for el in main.find_all(["h1", "h2", "h3", "h4", "p", "li"]):
            text = _clean(el.get_text(" ", strip=True))
            if not text:
                continue

            # Year heading, e.g. "2026".
            ym = re.fullmatch(r"(20\d{2})", text)
            if ym and el.name in ("h1", "h2", "h3"):
                year = int(ym.group(1))
                continue

            # Month heading.
            if el.name in ("h2", "h3", "h4"):
                m = _parse_month_heading(text)
                if m:
                    finalise(current)
                    current = None
                    month = m
                    continue

            # Title paragraphs: a <p> that contains a <strong> title and a day.
            if el.name == "p" and month:
                strong = el.find("strong")
                day_match = DAY_RE.search(text)
                # Only treat as an event if it has both a title and a day.
                if strong and day_match and not text.lower().startswith("camping"):
                    finalise(current)
                    title = _clean(strong.get_text(" ", strip=True))
                    # Some titles are split across multiple <strong> tags.
                    strongs = [_clean(s.get_text(" ", strip=True)) for s in el.find_all("strong")]
                    strongs = [s for s in strongs if s and s not in ("–", "-")]
                    if len(strongs) > 1:
                        title = " ".join(strongs)
                    postponed = "POSTPONED" in text.upper() or "CANCELLED" in text.upper()
                    current = {
                        "title": title,
                        "day_text": text,
                        "year": year,
                        "month": month,
                        "venue_lines": [],
                        "url": None,
                        "skip": postponed,
                    }
                    continue

            # List items: venue, notes, url — attach to current event.
            if el.name == "li" and current is not None:
                url_m = URL_RE.search(text)
                if url_m:
                    current["url"] = url_m.group(0)
                    continue
                if text.lower().startswith("camping"):
                    continue  # skip camping-availability notes
                current["venue_lines"].append(text)
                continue

        finalise(current)
        return events

    def _build_event(self, cur: dict, idx: int) -> Event | None:
        year = cur["year"]
        month = cur["month"]
        if not year or not month:
            return None

        # Parse day number(s) from the day/date line.
        days = [int(m.group(2)) for m in DAY_RE.finditer(cur["day_text"])]
        if not days:
            return None

        try:
            start = date(year, month, days[0])
        except ValueError:
            return None

        end = None
        if len(days) > 1:
            end_day = days[-1]
            end_month = month
            end_year = year
            # If the end day is earlier in the number than the start, the range
            # likely rolls into the next month (rare here, e.g. Jul 24 - 26).
            if end_day < days[0]:
                end_month += 1
                if end_month > 12:
                    end_month = 1
                    end_year += 1
            try:
                cand = date(end_year, end_month, end_day)
                if cand > start:
                    end = cand
            except ValueError:
                end = None

        venue = ", ".join(cur["venue_lines"]) if cur["venue_lines"] else None
        postcode = extract_postcode(venue or "")

        # The first venue line is the address; keep it as the venue and move any
        # additional prose lines into the description so venue stays clean.
        venue = None
        description = None
        lines = cur["venue_lines"]
        if lines:
            # Prefer the line containing a postcode as the venue/address.
            venue_idx = next(
                (i for i, ln in enumerate(lines) if extract_postcode(ln)), 0
            )
            venue = lines[venue_idx]
            other = [ln for i, ln in enumerate(lines) if i != venue_idx]
            if other:
                description = " ".join(other)
        postcode = extract_postcode(venue or "")

        return Event(
            source=self.key,
            source_id=f"{start.isoformat()}-{re.sub(r'[^a-z0-9]+', '-', cur['title'].lower())[:40]}",
            title=cur["title"],
            discipline=Discipline.OTHER,
            start_date=start,
            end_date=end,
            venue=venue,
            postcode=postcode,
            organiser=self.name,
            url=cur["url"] or URL,
            description=description,
        )
