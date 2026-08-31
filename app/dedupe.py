"""Cross-source de-duplication and weekend detection (pure, DB-free).

Shared by the DB query layer and the static-site build so the same rules apply
everywhere. Kept free of any storage dependency.
"""
from __future__ import annotations

from datetime import timedelta

from .models import Event

# Source preference for dedup: discipline-specific clubs win over the generic
# aggregators, since their titles/venues are cleaner. Lower index = preferred.
SOURCE_PRIORITY = [
    "awdc", "alrc", "swlrc", "hillclimb_uk", "rallies_info", "pembrey", "msv", "msuk",
]


def source_rank(source: str) -> int:
    try:
        return SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(SOURCE_PRIORITY)


def spans_weekend(e: Event) -> bool:
    """True if the event falls on or spans a Saturday or Sunday."""
    end = e.end_date or e.start_date
    d = e.start_date
    while d <= end:
        if d.weekday() >= 5:  # 5=Sat, 6=Sun
            return True
        d += timedelta(days=1)
    return False


def dedupe(events: list[Event]) -> list[Event]:
    """Collapse the same real-world event listed by multiple sources.

    Two events are duplicates when they share a start date and a normalised
    postcode. Events without a postcode are never merged. The preferred source
    (see SOURCE_PRIORITY) is kept; the others are recorded in `alt_sources`.
    Result is sorted by (start_date, distance).
    """
    groups: dict[tuple, list[Event]] = {}
    singles: list[Event] = []
    for e in events:
        if not e.postcode:
            singles.append(e)
            continue
        key = (e.start_date, e.postcode.replace(" ", "").upper())
        groups.setdefault(key, []).append(e)

    merged: list[Event] = []
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda e: source_rank(e.source))
        primary = group[0]
        primary.alt_sources = sorted({e.source for e in group[1:]} - {primary.source})
        merged.append(primary)

    result = merged + singles
    result.sort(key=lambda e: (
        e.start_date,
        e.distance_km if e.distance_km is not None else 1e9,
    ))
    return result
