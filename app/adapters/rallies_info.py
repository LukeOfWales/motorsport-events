"""UK rally / motorsport-club events from rallies.info.

rallies.info is the long-running UK rally aggregator. Its homepage is a Vue app
that fetches a JSON payload from `index_get.php`; the `futureevents` list covers
upcoming stage/targa rallies, sprints, hill climbs, trials, motocross, sand
races and touring assemblies — strong coverage of rally and dirt/off-road.

The feed gives each event a name, ISO date (`ra_date`), a short description
(which usually names the location/region), and links. It does not include a
postcode, so most of these events have no distance and show as "location TBC";
that's acceptable — the SPA handles missing locations, and these fill a real
gap in rally/off-road coverage.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime

from ..classify import classify
from ..geo import extract_postcode
from ..models import Event
from .base import Adapter

BASE = "https://www.rallies.info"
FEED = f"{BASE}/index_get.php"

# Strip a leading date prefix like "31st August 2026 - " or "9th/10th October
# 2026 " from names, since the date is carried separately.
DATE_PREFIX = re.compile(
    r"^\s*\d{1,2}(?:st|nd|rd|th)?(?:/\d{1,2}(?:st|nd|rd|th)?)?\s+"
    r"(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+\d{4}\s*[-\u2013]?\s*",
    re.IGNORECASE,
)
# Trailing sanctioning-body tags that add noise, e.g. "- Motorsport UK", "- ACU".
TRAILING_TAG = re.compile(r"\s*[-\u2013]\s*(Motorsport UK|ACU)\s*$", re.IGNORECASE)


def _clean_name(name: str) -> str:
    name = DATE_PREFIX.sub("", name or "").strip()
    name = TRAILING_TAG.sub("", name).strip(" -\u2013")
    return re.sub(r"\s+", " ", name).strip()


class RalliesInfoAdapter(Adapter):
    key = "rallies_info"
    name = "rallies.info"

    def fetch(self) -> list[Event]:
        with self.make_client() as client:
            resp = client.get(FEED, headers={"Referer": BASE + "/"})
            resp.raise_for_status()
            payload = resp.text
        return self.parse(payload)

    def parse(self, payload: str) -> list[Event]:
        data = json.loads(payload)
        events: list[Event] = []
        seen: set[str] = set()

        for item in data.get("futureevents", []):
            iso = item.get("ra_date") or item.get("ev_eventstart")
            if not iso:
                continue  # undated / provisional entries
            try:
                start = date.fromisoformat(iso)
            except (ValueError, TypeError):
                continue
            # Skip anything already in the past (defensive; feed is "future").
            if start < date.today():
                continue

            raw_name = item.get("name") or ""
            # Skip cancelled events (flagged in the name).
            if re.search(r"cancelled|postponed", raw_name, re.IGNORECASE):
                continue
            title = _clean_name(raw_name)
            if not title:
                continue

            end = None
            end_iso = item.get("ev_eventfinish")
            if end_iso:
                try:
                    cand = date.fromisoformat(end_iso)
                    if cand > start:
                        end = cand
                except (ValueError, TypeError):
                    end = None

            description = (item.get("description") or "").strip() or None
            # Classify from the (raw) name plus description for best coverage.
            discipline = classify(f"{raw_name} {description or ''}")

            # No postcode in the feed, but occasionally one is in the text.
            postcode = extract_postcode(description or "") or extract_postcode(raw_name)

            # Build a stable id + a usable link (event page or organiser site).
            eid = item.get("ra_eventid") or item.get("ev_id") or title.lower()
            eid = re.sub(r"[^a-z0-9]+", "-", str(eid).lower()).strip("-")[:50]
            if eid in seen:
                continue
            seen.add(eid)

            url = None
            if item.get("url"):
                u = item["url"]
                url = u if u.startswith("http") else BASE + u
            elif item.get("website"):
                w = item["website"]
                url = w if w.startswith("http") else "https://" + w

            events.append(Event(
                source=self.key,
                source_id=eid,
                title=title,
                discipline=discipline,
                start_date=start,
                end_date=end,
                venue=None,
                postcode=postcode,
                organiser=self.name,
                url=url,
                description=description,
            ))
        return events
