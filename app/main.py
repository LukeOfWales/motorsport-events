"""FastAPI app: JSON API + static calendar frontend.

Run with:  uvicorn app.main:app --reload
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db, geo
from .adapters import all_sources
from .models import Discipline

app = FastAPI(title="Motorsport Events")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _resolve_origin(postcode: Optional[str]) -> Optional[tuple[float, float]]:
    """Turn a user postcode into (lat, lon), using the geocode cache.

    Returns None when no postcode is given (callers then fall back to the
    stored home-relative distances).
    """
    if not postcode or not postcode.strip():
        return None
    pc = geo.normalise_postcode(postcode)
    cached = db.geocache_get(pc)
    if cached:
        return cached
    with httpx.Client(headers={"User-Agent": config.USER_AGENT},
                      timeout=config.HTTP_TIMEOUT, follow_redirects=True) as client:
        coords = geo.geocode_postcode(client, pc)
    # Cache the result (including a miss, stored as NULLs) for next time.
    db.geocache_put(pc, coords[0] if coords else None,
                    coords[1] if coords else None)
    return coords


@app.get("/api/disciplines")
def disciplines() -> list[dict]:
    return [{"value": d.value, "label": d.label} for d in Discipline]


@app.get("/api/sources")
def sources() -> list[dict]:
    # Only list sources that currently have upcoming events, so empty sources
    # (e.g. a seasonal feed that hasn't published next year's dates yet) don't
    # show as filters that return nothing.
    active = db.sources_with_upcoming()
    return [s for s in all_sources() if s["value"] in active]


@app.get("/api/config")
def app_config() -> dict:
    return {
        "home_postcode": config.HOME_POSTCODE,
        "home_lat": config.HOME_LAT,
        "home_lon": config.HOME_LON,
        "default_radius_km": config.DEFAULT_RADIUS_KM,
    }


@app.get("/api/geocode")
def geocode(postcode: str = Query(..., description="UK postcode or outcode")) -> dict:
    """Resolve a UK postcode to coordinates (for the 'near me' origin)."""
    origin = _resolve_origin(postcode)
    if origin is None:
        return {"postcode": geo.normalise_postcode(postcode), "found": False,
                "latitude": None, "longitude": None}
    return {
        "postcode": geo.normalise_postcode(postcode),
        "found": True,
        "latitude": origin[0],
        "longitude": origin[1],
    }


@app.get("/api/events")
def events(
    start: Optional[date] = Query(None, description="Earliest date (default: today)"),
    end: Optional[date] = Query(None, description="Latest start date"),
    discipline: Optional[list[str]] = Query(None),
    source: Optional[list[str]] = Query(None),
    max_distance_km: Optional[float] = Query(None),
    postcode: Optional[str] = Query(None, description="Origin postcode for distance"),
) -> dict:
    if start is None:
        start = date.today()
    origin = _resolve_origin(postcode)
    rows = db.query_events(
        start=start,
        end=end,
        disciplines=discipline,
        sources=source,
        max_distance_km=max_distance_km,
        origin=origin,
    )
    return {
        "count": len(rows),
        "origin_postcode": geo.normalise_postcode(postcode) if postcode else None,
        "events": [e.model_dump(mode="json") for e in rows],
    }


@app.get("/api/summary")
def summary(
    days: int = Query(30, ge=1, le=365),
    postcode: Optional[str] = Query(None),
) -> dict:
    """A quick summary of upcoming events for the next N days."""
    start = date.today()
    end = start + timedelta(days=days)
    origin = _resolve_origin(postcode)
    rows = db.query_events(start=start, end=end, origin=origin)
    by_disc: dict[str, int] = {}
    nearest = None
    for e in rows:
        by_disc[e.discipline.label] = by_disc.get(e.discipline.label, 0) + 1
        if e.distance_km is not None and (nearest is None or e.distance_km < nearest["distance_km"]):
            nearest = {"title": e.title, "distance_km": e.distance_km,
                       "start_date": e.start_date.isoformat()}
    return {
        "days": days,
        "total": len(rows),
        "by_discipline": by_disc,
        "nearest": nearest,
    }


# Serve the frontend. Mount static assets, and return index.html at root.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
