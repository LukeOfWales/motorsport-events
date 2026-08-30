"""Static-site data build: run adapters -> geocode -> dedupe -> write JSON.

This is the build-time half of the SPA. It reuses the adapters, classifier,
geocoding, and dedup logic, but instead of a database it writes a single JSON
file the browser loads. Geocoding results are cached in a JSON file so repeat
builds don't re-hit postcodes.io.

Run with:  python -m app.build_site   (writes site/events.json by default)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from pathlib import Path

import httpx

from . import config, geo
from .adapters import all_adapters
from .dedupe import dedupe
from .models import Event

log = logging.getLogger("mse.build")

# Output: the SPA is served from site/, with data at site/events.json.
SITE_DIR = Path(os.environ.get("MSE_SITE_DIR", config.BASE_DIR / "site"))
DATA_DIR = config.BASE_DIR / "data"
GEOCACHE_PATH = DATA_DIR / "geocache.json"

# Flag events first seen within this window as "new" in the built data.
NEW_WINDOW_DAYS = 7


def _load_geocache() -> dict[str, list | None]:
    if GEOCACHE_PATH.exists():
        try:
            return json.loads(GEOCACHE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_geocache(cache: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    GEOCACHE_PATH.write_text(json.dumps(cache, indent=0, sort_keys=True))


def _load_first_seen() -> dict[str, str]:
    """Map of uid -> ISO date first seen, persisted so 'new' badges are stable."""
    path = DATA_DIR / "first_seen.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_first_seen(seen: dict[str, str]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    (DATA_DIR / "first_seen.json").write_text(json.dumps(seen, sort_keys=True))


def _geocode(events: list[Event]) -> None:
    """Fill coordinates from adapter data or postcodes.io (file-cached)."""
    cache = _load_geocache()
    client = httpx.Client(
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.HTTP_TIMEOUT,
        follow_redirects=True,
    )
    try:
        for e in events:
            if e.latitude is not None and e.longitude is not None:
                continue
            if not e.postcode:
                continue
            key = e.postcode
            if key not in cache:
                coords = geo.geocode_postcode(client, key)
                cache[key] = list(coords) if coords else None
            coords = cache[key]
            if coords:
                e.latitude, e.longitude = coords[0], coords[1]
    finally:
        client.close()
    _save_geocache(cache)


def collect() -> list[Event]:
    """Run every adapter and return the combined, geocoded, deduped events."""
    all_events: list[Event] = []
    statuses: list[dict] = []
    for adapter in all_adapters():
        try:
            events = adapter.fetch()
        except Exception as exc:  # noqa: BLE001
            log.warning("[%s] FAILED: %s", adapter.key, exc)
            statuses.append({"source": adapter.key, "ok": False,
                             "event_count": 0, "error": str(exc)})
            continue
        all_events.extend(events)
        statuses.append({"source": adapter.key, "ok": True,
                         "event_count": len(events), "error": None})
        log.info("[%s] %s: %s events", adapter.key, adapter.name, len(events))

    _geocode(all_events)

    # Drop past events (the SPA only shows upcoming).
    today = date.today()
    all_events = [e for e in all_events
                  if (e.end_date or e.start_date) >= today]

    deduped = dedupe(all_events)
    collect.statuses = statuses  # type: ignore[attr-defined]
    return deduped


def build() -> Path:
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    events = collect()

    # Stable "first seen" tracking across builds.
    first_seen = _load_first_seen()
    today_iso = date.today().isoformat()
    for e in events:
        first_seen.setdefault(e.uid, today_iso)
    _save_first_seen(first_seen)

    cutoff = (datetime.now(timezone.utc).date()).toordinal() - NEW_WINDOW_DAYS

    out_events = []
    for e in events:
        d = e.model_dump(mode="json")
        d.pop("fetched_at", None)
        d.pop("first_seen", None)
        fs = first_seen.get(e.uid)
        d["is_new"] = bool(fs and date.fromisoformat(fs).toordinal() >= cutoff)
        out_events.append(d)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "home": {
            "postcode": config.HOME_POSTCODE,
            "lat": config.HOME_LAT,
            "lon": config.HOME_LON,
        },
        "default_radius_km": config.DEFAULT_RADIUS_KM,
        "discipline_radius_km": config.DISCIPLINE_RADIUS_KM,
        "sources": getattr(collect, "statuses", []),
        "count": len(out_events),
        "events": out_events,
    }
    out = SITE_DIR / "events.json"
    out.write_text(json.dumps(payload, separators=(",", ":")))
    log.info("Wrote %s events to %s", len(out_events), out)
    return out


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    build()
