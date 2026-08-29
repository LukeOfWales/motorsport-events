"""FastAPI app: JSON API + static calendar frontend.

Run with:  uvicorn app.main:app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, db, geo
from .adapters import all_sources
from .ics import build_ics as _build_ics
from .models import Discipline, Event


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure schema/migrations are applied even if the server starts before
    # the first ingest run.
    db.init_db()
    yield


app = FastAPI(title="Motorsport Events", lifespan=lifespan)

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
        "discipline_radius_km": config.DISCIPLINE_RADIUS_KM,
    }


@app.get("/api/health")
def health() -> dict:
    """Per-source ingest status and freshness, for the data-health view."""
    return {
        "sources": db.latest_ingest_status(),
        "total_events": db.count_events(),
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


def _query_from_params(
    start, end, discipline, source, max_distance_km, postcode, search, weekend,
    per_discipline_radius=False,
):
    """Shared query builder used by both the JSON and ICS event endpoints."""
    if start is None:
        start = date.today()
    origin = _resolve_origin(postcode)
    disc_radius = None
    if per_discipline_radius:
        disc_radius = config.DISCIPLINE_RADIUS_KM
        # Per-discipline filtering needs distances; use home origin if the user
        # hasn't set one, and ignore the single max_distance_km slider.
        if origin is None:
            origin = (config.HOME_LAT, config.HOME_LON)
        max_distance_km = None
    rows = db.query_events(
        start=start,
        end=end,
        disciplines=discipline,
        sources=source,
        max_distance_km=max_distance_km,
        origin=origin,
        search=search,
        weekend_only=weekend,
        discipline_radius=disc_radius,
    )
    return rows


# Events first seen within this window are flagged "new" in the UI.
NEW_WINDOW = timedelta(days=7)


def _mark_new(rows: list[Event]) -> list[dict]:
    cutoff = datetime.now().astimezone() - NEW_WINDOW
    out = []
    for e in rows:
        d = e.model_dump(mode="json")
        is_new = False
        if e.first_seen is not None:
            fs = e.first_seen
            if fs.tzinfo is None:
                fs = fs.astimezone()
            is_new = fs >= cutoff
        d["is_new"] = is_new
        out.append(d)
    return out


@app.get("/api/events")
def events(
    start: Optional[date] = Query(None, description="Earliest date (default: today)"),
    end: Optional[date] = Query(None, description="Latest start date"),
    discipline: Optional[list[str]] = Query(None),
    source: Optional[list[str]] = Query(None),
    max_distance_km: Optional[float] = Query(None),
    postcode: Optional[str] = Query(None, description="Origin postcode for distance"),
    search: Optional[str] = Query(None, description="Free-text title/venue/organiser"),
    weekend: bool = Query(False, description="Only events on/spanning a weekend"),
    per_discipline_radius: bool = Query(False, description="Use per-discipline radii"),
) -> dict:
    rows = _query_from_params(
        start, end, discipline, source, max_distance_km, postcode, search, weekend,
        per_discipline_radius,
    )
    return {
        "count": len(rows),
        "origin_postcode": geo.normalise_postcode(postcode) if postcode else None,
        "events": _mark_new(rows),
    }


@app.get("/api/events.ics")
def events_ics(
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    discipline: Optional[list[str]] = Query(None),
    source: Optional[list[str]] = Query(None),
    max_distance_km: Optional[float] = Query(None),
    postcode: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    weekend: bool = Query(False),
) -> Response:
    """Subscribable iCalendar feed of the current (filtered) events.

    Point a calendar app at this URL (with the same query params as the UI) to
    keep an always-updating subscription of matching events.
    """
    rows = _query_from_params(
        start, end, discipline, source, max_distance_km, postcode, search, weekend,
    )
    ics = _build_ics(rows, name="Motorsport Events")
    return Response(content=ics, media_type="text/calendar",
                    headers={"Content-Disposition": "inline; filename=motorsport-events.ics"})


@app.get("/api/event/{source}/{source_id}.ics")
def event_ics(source: str, source_id: str) -> Response:
    """Single-event iCalendar file (the per-event 'add to calendar' link)."""
    rows = db.query_events(start=date(2000, 1, 1), sources=[source], dedupe=False)
    match = [e for e in rows if e.source_id == source_id]
    if not match:
        return Response(status_code=404, content="Not found")
    ics = _build_ics(match[:1], name=match[0].title)
    fname = f"{source}-{source_id}.ics".replace("/", "-")
    return Response(content=ics, media_type="text/calendar",
                    headers={"Content-Disposition": f"attachment; filename={fname}"})


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
