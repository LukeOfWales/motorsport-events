"""Association of Land Rover Clubs (ALRC) events.

The ALRC events list at alrc.co.uk/calendar/events-list/ is rendered with the
Formidable Forms grid view. All upcoming entries live in one grid block, each
separated by a "|" marker, with a per-entry detail link (.frm-detail-link ->
/entry/{id}). Each entry's text follows a consistent shape:

    September 25, 2026 –
    September 26, 2026        (optional end date)
    Tyro & RTVT               (event type / title)
    Venue:
    Stainby Quarry, NG33 5QP
    Organising Club:
    Leics & Rutland LRC
    http://www.lrlrc.co.uk    (optional club URL)
    See FULL DETAILS
    Posted by: ALRC Secretary

The plugin only lists events from today forward, which is exactly what we want.
"""
from __future__ import annotations

import re
from datetime import date

from dateutil import parser as dateparser

from ..classify import classify
from ..geo import extract_postcode
from ..models import Discipline, Event
from .base import Adapter

URL = "https://alrc.co.uk/calendar/events-list/"

DATE_RE = re.compile(
    r"^[A-Z][a-z]+\s+\d{1,2},\s+\d{4}\s*[–\-]?\s*$"
)


def _parse_date(text: str) -> date | None:
    cleaned = text.rstrip(" –-").strip()
    try:
        return dateparser.parse(cleaned).date()
    except (ValueError, OverflowError):
        return None


class ALRCAdapter(Adapter):
    key = "alrc"
    name = "Association of Land Rover Clubs"

    def fetch(self) -> list[Event]:
        with self.make_client() as client:
            resp = client.get(URL)
            resp.raise_for_status()
            html = resp.text
        return self.parse(html)

    def parse(self, html: str) -> list[Event]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        block = soup.select_one("div.with_frm_style.frm-grid-view")
        if block is None:
            return []

        # Detail-link ids, in document order, to pair with each entry.
        entry_ids = [
            re.search(r"/entry/(\d+)", a.get("href", "")).group(1)
            for a in block.select("a.frm-detail-link")
            if re.search(r"/entry/(\d+)", a.get("href", ""))
        ]
        detail_urls = [
            a.get("href") for a in block.select("a.frm-detail-link")
        ]

        text = block.get_text("\n", strip=True)
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

        # Split into per-event chunks on the "|" separator.
        chunks: list[list[str]] = []
        cur: list[str] = []
        for ln in lines:
            if ln == "|":
                if cur:
                    chunks.append(cur)
                    cur = []
                continue
            cur.append(ln)
        if cur:
            chunks.append(cur)

        events: list[Event] = []
        for i, chunk in enumerate(chunks):
            eid = entry_ids[i] if i < len(entry_ids) else str(i)
            url = detail_urls[i] if i < len(detail_urls) else URL
            ev = self._build(chunk, eid, url)
            if ev:
                events.append(ev)
        return events

    def _build(self, chunk: list[str], eid: str, url: str | None) -> Event | None:
        # First line is always the start date. A second date line (end) is
        # present for multi-day events.
        if not chunk:
            return None
        start = _parse_date(chunk[0])
        if not start:
            return None

        idx = 1
        end = None
        if idx < len(chunk) and DATE_RE.match(chunk[idx] + " "):
            end = _parse_date(chunk[idx])
            if end and end <= start:
                end = None
            idx += 1
        elif idx < len(chunk):
            maybe_end = _parse_date(chunk[idx])
            # Only treat as end date if it parses AND the line looks like a date.
            if maybe_end and re.match(r"^[A-Z][a-z]+\s+\d", chunk[idx]):
                end = maybe_end if maybe_end > start else None
                if end:
                    idx += 1

        # Title is the next non-label line.
        title = None
        while idx < len(chunk):
            if chunk[idx].rstrip(":").lower() in ("venue", "organising club", "posted by"):
                break
            title = chunk[idx]
            idx += 1
            break
        if not title:
            return None

        # Pull labelled fields from the remaining lines.
        venue = None
        organiser = None
        rest = chunk[idx:]
        for j, ln in enumerate(rest):
            low = ln.rstrip(":").lower()
            if low == "venue" and j + 1 < len(rest):
                venue = rest[j + 1]
            elif low == "organising club" and j + 1 < len(rest):
                organiser = rest[j + 1]

        postcode = extract_postcode(venue or "")

        # ALRC titles are terse type codes ("CCVT", "Tyro & RTVT"); prefix the
        # organising club so the calendar entry is readable.
        display_title = title
        if organiser and organiser.lower() not in title.lower():
            display_title = f"{organiser} - {title}"

        return Event(
            source=self.key,
            source_id=eid,
            title=display_title,
            discipline=classify(title),
            start_date=start,
            end_date=end,
            venue=venue,
            postcode=postcode,
            organiser=organiser or self.name,
            url=url or URL,
            description=None,
        )
