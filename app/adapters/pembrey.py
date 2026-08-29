"""Pembrey Circuit events (pembreycircuit.co.uk).

Pembrey is a circuit in Carmarthenshire, South Wales. Its event and racing
detail pages each embed a schema.org SportsEvent as JSON-LD, which is a clean,
structured source of name/date/location. The listing pages are JS-rendered, so
we enumerate detail pages from the sitemap instead, then read the JSON-LD from
each.

All events are at Pembrey Circuit, so location/postcode come from the JSON-LD
(SA16 0HZ). Past-dated pages in the sitemap are fetched too but filtered out by
the ingest step's past-event purge.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from ..classify import classify
from ..models import Event
from .base import Adapter

BASE = "https://pembreycircuit.co.uk"
SITEMAP = f"{BASE}/sitemap.xml"

# Only these path prefixes hold event detail pages.
DETAIL_PREFIXES = ("/event/", "/racing/")

# Cap how many detail pages we fetch per run (safety against a huge sitemap).
MAX_PAGES = 120

DEFAULT_POSTCODE = "SA16 0HZ"


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        # JSON-LD dates are ISO; may include a time/zone.
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


class PembreyAdapter(Adapter):
    key = "pembrey"
    name = "Pembrey Circuit"

    def fetch(self) -> list[Event]:
        with self.make_client() as client:
            urls = self._detail_urls(client)
            events: list[Event] = []
            seen: set[str] = set()
            for url in urls[:MAX_PAGES]:
                try:
                    resp = client.get(url)
                    if resp.status_code != 200:
                        continue
                    ev = self._parse_detail(resp.text, url)
                except Exception:
                    continue  # skip a broken page, keep going
                if ev and ev.source_id not in seen:
                    seen.add(ev.source_id)
                    events.append(ev)
        return events

    def _detail_urls(self, client) -> list[str]:
        resp = client.get(SITEMAP)
        resp.raise_for_status()
        locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)
        return [
            u for u in locs
            if any(p in u for p in DETAIL_PREFIXES)
        ]

    def parse(self, html: str, url: str) -> Event | None:
        """Public wrapper around detail parsing (used by tests)."""
        return self._parse_detail(html, url)

    def _parse_detail(self, html: str, url: str) -> Event | None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        event_ld = None
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
            except (json.JSONDecodeError, TypeError):
                continue
            items = data.get("@graph", [data]) if isinstance(data, dict) else data
            for it in (items if isinstance(items, list) else [items]):
                if isinstance(it, dict) and "Event" in str(it.get("@type", "")):
                    event_ld = it
                    break
            if event_ld:
                break
        if not event_ld:
            return None

        name = (event_ld.get("name") or "").strip()
        if not name:
            return None

        start = _parse_iso_date(event_ld.get("startDate"))
        end = _parse_iso_date(event_ld.get("endDate"))
        # Some pages only carry endDate; treat it as the date if start missing.
        if start is None:
            start = end
            end = None
        if start is None:
            return None
        if end and end <= start:
            end = None

        location = event_ld.get("location") or {}
        address = location.get("address") or {}
        postcode = address.get("postalCode") or DEFAULT_POSTCODE
        venue = location.get("name") or "Pembrey Circuit"
        locality = address.get("addressLocality")
        if locality and locality.lower() not in venue.lower():
            venue = f"{venue}, {locality}"

        description = (event_ld.get("description") or "").strip() or None

        # Stable id from the URL slug.
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        return Event(
            source=self.key,
            source_id=slug,
            title=name,
            discipline=classify(name),
            start_date=start,
            end_date=end,
            venue=venue,
            postcode=postcode,
            organiser=self.name,
            url=url,
            description=description,
        )
