"""All Wheel Drive Club (AWDC) events.

AWDC publish their calendars as static files that change URL each season:

  - Trials calendar (image):
    https://www.awdc.co.uk/wp-content/uploads/2026/02/trials-cal-2.jpg
  - Comp Safari championship (PDF, has a text layer):
    https://www.awdc.co.uk/wp-content/uploads/2026/03/Saf-Cal-2026-1.pdf

Because these are a JPG and a PDF (no structured feed, URLs change yearly),
the calendar data is transcribed into the tables below. When AWDC publish new
files for a new season, update SOURCE_URLS and the two data tables.

The Comp Safari PDF has a real text layer, so its dates are also verifiable by
downloading and running `pdftotext -layout` on the URL above.
"""
from __future__ import annotations

from datetime import date

from ..models import Discipline, Event
from .base import Adapter

SEASON = 2026

SOURCE_URLS = {
    "trials": "https://www.awdc.co.uk/wp-content/uploads/2026/02/trials-cal-2.jpg",
    "safari": "https://www.awdc.co.uk/wp-content/uploads/2026/03/Saf-Cal-2026-1.pdf",
}

# --- AWDC Trials calendar 2026 -------------------------------------------
# (month, day, venue, postcode). Multi-day meetings appear as separate rows
# in the source and are kept as separate day entries here.
TRIALS = [
    (1, 18, "Weston Coyney", "ST11 9EX"),
    (2, 1, "Binegar", "BA3 4TJ"),
    (2, 15, "Corwen", "LL21 9SD"),
    (3, 1, "Upperboat", "CF37 5BJ"),
    (3, 15, "Corwen", "LL21 9SD"),
    (4, 4, "Coney Green", "DY13 0TE"),
    (4, 5, "Coney Green", "DY13 0TE"),
    (4, 19, "Mow Cop", "ST7 3PR"),
    (5, 3, "West Harptree", "BS40 6EN"),
    (5, 4, "West Harptree", "BS40 6EN"),
    (5, 24, "Corwen", "LL21 9SD"),
    (5, 25, "Corwen", "LL21 9SD"),
    (6, 7, "Beechtrees", "TA23 0SU"),
    (6, 21, "Briercliffe", "BB10 3PL"),
    (7, 5, "Cross Ash", "NP7 8PH"),
    (7, 19, "Briercliffe", "BB10 3PL"),
    (8, 9, "Pontardawe", "SA8 4RR"),
    (9, 6, "Ozleworth", "GL12 7QA"),
    (9, 20, "Weston Coyney", "ST11 9EX"),
    (10, 3, "Mannington", "BH21 7JS"),
    (10, 4, "Mannington", "BH21 7JS"),
    (10, 18, "Mow Cop", "ST7 3PR"),
    (11, 1, "Aggs Hill", "GL54 4ET"),
    (11, 15, "Corwen", "LL21 9SD"),
    (12, 6, "Binegar", "BA3 4TJ"),
    (12, 13, "Weston Coyney", "ST11 9EX"),
]

# --- AWDC Comp Safari Championship 2026 ----------------------------------
# (round, start_month, start_day, end_month, end_day|None, venue, postcode)
SAFARI = [
    (1, 3, 22, None, None, "Walters Arena", "SA11 5TU"),
    (2, 4, 12, None, None, "Bovington, Dorset", "BH20 7NQ"),
    (3, 5, 3, None, None, "Otterham, Cornwall", "PL32 9YN"),
    (4, 5, 24, None, None, "Ebbw Vale", "NP13 2ER"),
    (5, 6, 21, None, None, "Minehead, Somerset", "TA24 8SW"),
    (6, 8, 2, None, None, "Whaddon, Buckinghamshire", "MK17 0NQ"),
    (7, 9, 6, None, None, "Ilfracombe, North Devon", "EX34 9RW"),
    (8, 10, 10, 10, 11, "Walters Arena (2 day event)", "SA11 5TU"),
]


class AWDCAdapter(Adapter):
    key = "awdc"
    name = "All Wheel Drive Club"

    def fetch(self) -> list[Event]:
        events: list[Event] = []

        # Trials
        for month, day, venue, postcode in TRIALS:
            try:
                start = date(SEASON, month, day)
            except ValueError:
                continue
            events.append(Event(
                source=self.key,
                source_id=f"trial-{start.isoformat()}-{postcode.replace(' ', '')}",
                title=f"AWDC Trial - {venue}",
                discipline=Discipline.TRIALS,
                start_date=start,
                venue=venue,
                postcode=postcode,
                organiser=self.name,
                url=SOURCE_URLS["trials"],
                description="AWDC RTV / trials calendar event.",
            ))

        # Comp Safari championship
        for rnd, sm, sd, em, ed, venue, postcode in SAFARI:
            try:
                start = date(SEASON, sm, sd)
            except ValueError:
                continue
            end = None
            if em and ed:
                try:
                    cand = date(SEASON, em, ed)
                    if cand > start:
                        end = cand
                except ValueError:
                    end = None
            events.append(Event(
                source=self.key,
                source_id=f"safari-r{rnd}-{start.isoformat()}",
                title=f"AWDC Comp Safari R{rnd} - {venue}",
                discipline=Discipline.OFF_ROAD,
                start_date=start,
                end_date=end,
                venue=venue,
                postcode=postcode,
                organiser=self.name,
                url=SOURCE_URLS["safari"],
                description="AWDC Comp Safari Championship round.",
            ))

        return events
