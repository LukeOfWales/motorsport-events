"""Ingest pipeline: run adapters, geocode, compute distance, store.

Run with:  python -m app.ingest
"""
from __future__ import annotations

import logging

import httpx

from . import config, db, geo
from .adapters import all_adapters
from .models import Event

log = logging.getLogger("mse.ingest")


def _geocode_events(events: list[Event]) -> None:
    """Fill latitude/longitude/distance_km using the postcode geocode cache."""
    client = httpx.Client(
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
    )
    seen: dict[str, tuple[float, float] | None] = {}
    try:
        for e in events:
            # Prefer coordinates the adapter already provided (e.g. Motorsport
            # UK supplies them). Only geocode when we don't have any.
            if e.latitude is not None and e.longitude is not None:
                if e.distance_km is None:
                    e.distance_km = geo.distance_from_home(e.latitude, e.longitude)
                continue
            if not e.postcode:
                continue
            pc = e.postcode
            if pc in seen:
                coords = seen[pc]
            else:
                coords = db.geocache_get(pc)
                if coords is None:
                    coords = geo.geocode_postcode(client, pc)
                    # Cache even a miss (as NULLs) to avoid re-querying.
                    db.geocache_put(pc, coords[0] if coords else None,
                                    coords[1] if coords else None)
                seen[pc] = coords
            if coords:
                e.latitude, e.longitude = coords
                e.distance_km = geo.distance_from_home(*coords)
    finally:
        client.close()


def run() -> int:
    db.init_db()
    total = 0
    for adapter in all_adapters():
        try:
            events = adapter.fetch()
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s] FAILED: %s", adapter.key, exc)
            db.record_ingest_run(adapter.key, ok=False, event_count=0, error=str(exc))
            continue
        _geocode_events(events)
        written = db.replace_source_events(adapter.key, events)
        total += written
        db.record_ingest_run(adapter.key, ok=True, event_count=written)
        log.info("[%s] %s: %s events", adapter.key, adapter.name, written)
    # Drop events that have already finished; we only care about upcoming ones,
    # and this stops stale past-season data (e.g. an adapter falling back to a
    # previous year's calendar) from lingering in the DB.
    purged = db.delete_past_events()
    if purged:
        log.info("Purged %s past events.", purged)
    log.info("Done. %s events written. Total in DB: %s", total, db.count_events())
    return total


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet the very chatty httpx per-request logs.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run()
