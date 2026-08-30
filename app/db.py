"""DuckDB storage for events and a postcode geocode cache.

DuckDB is used as a single local file (data/events.duckdb). Connections are
opened per operation because a DuckDB connection object is not safe to share
across threads, and FastAPI may serve requests from a threadpool.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Iterable, Iterator, Optional

import duckdb

from . import config
from .models import Discipline, Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    uid          VARCHAR PRIMARY KEY,
    source       VARCHAR NOT NULL,
    source_id    VARCHAR NOT NULL,
    title        VARCHAR NOT NULL,
    discipline   VARCHAR NOT NULL,
    start_date   DATE NOT NULL,
    end_date     DATE,
    venue        VARCHAR,
    postcode     VARCHAR,
    latitude     DOUBLE,
    longitude    DOUBLE,
    distance_km  DOUBLE,
    organiser    VARCHAR,
    url          VARCHAR,
    description  VARCHAR,
    fetched_at   TIMESTAMP NOT NULL,
    first_seen   TIMESTAMP
);

CREATE TABLE IF NOT EXISTS geocache (
    postcode   VARCHAR PRIMARY KEY,
    latitude   DOUBLE,
    longitude  DOUBLE,
    updated_at TIMESTAMP NOT NULL
);

-- One row per source per ingest run, for the data-health view.
CREATE TABLE IF NOT EXISTS ingest_runs (
    source      VARCHAR NOT NULL,
    run_at      TIMESTAMP NOT NULL,
    ok          BOOLEAN NOT NULL,
    event_count INTEGER NOT NULL,
    error       VARCHAR
);
"""


@contextmanager
def connect() -> Iterator[duckdb.DuckDBPyConnection]:
    conn = duckdb.connect(str(config.DB_PATH))
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.execute(SCHEMA)
        _migrate(conn)


def _migrate(conn) -> None:
    """Lightweight, idempotent migrations for pre-existing databases.

    Adds columns/tables introduced after the initial schema. Safe to run on
    every startup. (A full migration framework is overkill for a rebuildable
    local DB, but this keeps existing .duckdb files working after upgrades.)
    """
    cols = {row[0] for row in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'events'"
    ).fetchall()}
    if "first_seen" not in cols:
        conn.execute("ALTER TABLE events ADD COLUMN first_seen TIMESTAMP")


# Column order used everywhere we read a full event row.
_COLS = [
    "uid", "source", "source_id", "title", "discipline", "start_date",
    "end_date", "venue", "postcode",
    "latitude", "longitude", "distance_km", "organiser", "url",
    "description", "fetched_at", "first_seen",
]


def _event_from_row(row: tuple) -> Event:
    d = dict(zip(_COLS, row))
    d["discipline"] = Discipline(d["discipline"])
    # DuckDB returns date/datetime objects already; be tolerant of strings.
    if isinstance(d["start_date"], str):
        d["start_date"] = date.fromisoformat(d["start_date"])
    if d["end_date"] and isinstance(d["end_date"], str):
        d["end_date"] = date.fromisoformat(d["end_date"])
    if isinstance(d["fetched_at"], str):
        d["fetched_at"] = datetime.fromisoformat(d["fetched_at"])
    if d.get("first_seen") and isinstance(d["first_seen"], str):
        d["first_seen"] = datetime.fromisoformat(d["first_seen"])
    d.pop("uid", None)
    return Event(**d)


def upsert_events(events: Iterable[Event]) -> int:
    """Insert or update events by uid.

    Geocode fields (latitude/longitude/distance_km) are preserved from the
    existing row when the incoming event doesn't supply them, so re-scraping
    doesn't discard geocoding work.
    """
    events = list(events)
    if not events:
        return 0

    with connect() as conn:
        # Preload existing geocodes AND first_seen for the incoming uids.
        uids = [e.uid for e in events]
        placeholders = ",".join("?" for _ in uids)
        existing: dict[str, tuple] = {}
        rows = conn.execute(
            f"SELECT uid, latitude, longitude, distance_km, first_seen FROM events "
            f"WHERE uid IN ({placeholders})",
            uids,
        ).fetchall()
        for uid, lat, lon, dist, first_seen in rows:
            existing[uid] = (lat, lon, dist, first_seen)

        now = datetime.now(timezone.utc)
        for e in events:
            lat, lon, dist = e.latitude, e.longitude, e.distance_km
            first_seen = e.first_seen or now
            if e.uid in existing:
                old_lat, old_lon, old_dist, old_first = existing[e.uid]
                lat = lat if lat is not None else old_lat
                lon = lon if lon is not None else old_lon
                dist = dist if dist is not None else old_dist
                # Preserve the original first_seen for events we've seen before.
                first_seen = old_first or first_seen

            conn.execute("DELETE FROM events WHERE uid = ?", [e.uid])
            conn.execute(
                """INSERT INTO events (
                    uid, source, source_id, title, discipline, start_date,
                    end_date, venue, postcode,
                    latitude, longitude, distance_km, organiser, url,
                    description, fetched_at, first_seen
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    e.uid, e.source, e.source_id, e.title, e.discipline.value,
                    e.start_date, e.end_date, e.venue, e.postcode,
                    lat, lon, dist, e.organiser, e.url,
                    e.description, e.fetched_at, first_seen,
                ],
            )
    return len(events)


def query_events(
    *,
    start: Optional[date] = None,
    end: Optional[date] = None,
    disciplines: Optional[list[str]] = None,
    sources: Optional[list[str]] = None,
    max_distance_km: Optional[float] = None,
    origin: Optional[tuple[float, float]] = None,
    search: Optional[str] = None,
    weekend_only: bool = False,
    discipline_radius: Optional[dict[str, float]] = None,
    dedupe: bool = True,
) -> list[Event]:
    """Query events, optionally ranked/filtered by distance from `origin`.

    When `origin` (lat, lon) is given, each event's `distance_km` is recomputed
    from its stored coordinates relative to that origin, and distance filtering
    applies to the recomputed value. Without an origin, the stored
    home-relative `distance_km` is used.

    `search` matches (case-insensitive) against title, venue, and organiser.
    `weekend_only` keeps events that fall on (or span) a Saturday or Sunday.
    """
    clauses = []
    params: list = []
    if start is not None:
        clauses.append("(COALESCE(end_date, start_date) >= ?)")
        params.append(start)
    if end is not None:
        clauses.append("start_date <= ?")
        params.append(end)
    if disciplines:
        placeholders = ",".join("?" for _ in disciplines)
        clauses.append(f"discipline IN ({placeholders})")
        params.extend(disciplines)
    if sources:
        placeholders = ",".join("?" for _ in sources)
        clauses.append(f"source IN ({placeholders})")
        params.extend(sources)
    if search:
        term = f"%{search.lower()}%"
        clauses.append(
            "(LOWER(title) LIKE ? OR LOWER(COALESCE(venue,'')) LIKE ? "
            "OR LOWER(COALESCE(organiser,'')) LIKE ?)"
        )
        params.extend([term, term, term])
    # Distance filtering is applied in SQL only when using the stored (home)
    # distance. With a custom origin we filter in Python after recomputing.
    # When a distance limit is set we exclude events with no known location
    # (they can't be "near" anywhere), so the near-me view isn't diluted.
    if max_distance_km is not None and origin is None:
        clauses.append("(distance_km IS NOT NULL AND distance_km <= ?)")
        params.append(max_distance_km)

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    cols = ", ".join(_COLS)
    sql = f"SELECT {cols} FROM events {where} ORDER BY start_date"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    events = [_event_from_row(r) for r in rows]

    if weekend_only:
        events = [e for e in events if _spans_weekend(e)]

    if origin is not None:
        from .geo import distance_between
        for e in events:
            if e.latitude is not None and e.longitude is not None:
                e.distance_km = distance_between(origin, e.latitude, e.longitude)
            else:
                e.distance_km = None
        if max_distance_km is not None:
            events = [
                e for e in events
                if e.distance_km is not None and e.distance_km <= max_distance_km
            ]

    # Per-discipline radius: keep an event only if it's within its discipline's
    # own limit. Events with unknown distance are dropped (can't be "near").
    if discipline_radius:
        kept = []
        for e in events:
            limit = discipline_radius.get(e.discipline.value)
            if limit is None:
                kept.append(e)
            elif e.distance_km is not None and e.distance_km <= limit:
                kept.append(e)
        events = kept

    if dedupe:
        events = _dedupe(events)
    else:
        events.sort(key=lambda e: (
            e.start_date,
            e.distance_km if e.distance_km is not None else 1e9,
        ))
    return events


# Source preference for dedup: discipline-specific clubs win over the generic
# aggregators, since their titles/venues are cleaner. Lower index = preferred.
_SOURCE_PRIORITY = ["awdc", "alrc", "swlrc", "hillclimb_uk", "msv", "msuk"]


def _source_rank(source: str) -> int:
    try:
        return _SOURCE_PRIORITY.index(source)
    except ValueError:
        return len(_SOURCE_PRIORITY)


def _spans_weekend(e: Event) -> bool:
    """True if the event falls on or spans a Saturday or Sunday."""
    from datetime import timedelta
    end = e.end_date or e.start_date
    d = e.start_date
    while d <= end:
        if d.weekday() >= 5:  # 5=Sat, 6=Sun
            return True
        d += timedelta(days=1)
    return False


def _dedupe(events: list[Event]) -> list[Event]:
    """Collapse the same real-world event listed by multiple sources.

    Two events are considered duplicates when they share a start date and a
    normalised postcode. Events without a postcode are never merged (we can't
    be confident they're the same). The preferred source (see _SOURCE_PRIORITY)
    is kept; the others are recorded in `alt_sources`.
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
    for key, group in groups.items():
        if len(group) == 1:
            merged.append(group[0])
            continue
        group.sort(key=lambda e: _source_rank(e.source))
        primary = group[0]
        alts = sorted({e.source for e in group[1:]} - {primary.source})
        primary.alt_sources = alts
        merged.append(primary)

    result = merged + singles
    result.sort(key=lambda e: (e.start_date, e.distance_km if e.distance_km is not None else 1e9))
    return result


def count_events() -> int:
    with connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]


def sources_with_upcoming(start: Optional[date] = None) -> set[str]:
    """Return the set of source keys that have at least one upcoming event."""
    cutoff = start or date.today()
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT source FROM events "
            "WHERE COALESCE(end_date, start_date) >= ?",
            [cutoff],
        ).fetchall()
    return {r[0] for r in rows}


def delete_source(source: str) -> int:
    """Remove all events belonging to a given source. Returns rows deleted."""
    with connect() as conn:
        before = conn.execute(
            "SELECT COUNT(*) FROM events WHERE source = ?", [source]
        ).fetchone()[0]
        conn.execute("DELETE FROM events WHERE source = ?", [source])
    return before


def replace_source_events(source: str, events: list[Event]) -> int:
    """Make `events` the authoritative set for `source`.

    Deletes the source's existing rows and inserts the new ones in one
    transaction, so events the source no longer produces (renamed, cancelled,
    or removed by a bug fix) don't linger as orphans. Geocode data for events
    that still exist (matched by uid) is preserved via upsert semantics.

    No-op if `events` is empty, to avoid wiping good data on a transient empty
    fetch. Returns the number of events written.
    """
    if not events:
        return 0
    # Preserve geocodes by reading them before the delete.
    upsert_events(events)  # writes/updates rows, preserving coords by uid
    keep_uids = {e.uid for e in events}
    with connect() as conn:
        rows = conn.execute(
            "SELECT uid FROM events WHERE source = ?", [source]
        ).fetchall()
        stale = [r[0] for r in rows if r[0] not in keep_uids]
        for uid in stale:
            conn.execute("DELETE FROM events WHERE uid = ?", [uid])
    return len(events)


def delete_past_events(before: Optional[date] = None) -> int:
    """Remove events that finished before `before` (default: today).

    Uses the end date for multi-day events so an event still running today is
    kept. Returns the number of rows removed.
    """
    cutoff = before or date.today()
    with connect() as conn:
        n = conn.execute(
            "SELECT COUNT(*) FROM events WHERE COALESCE(end_date, start_date) < ?",
            [cutoff],
        ).fetchone()[0]
        conn.execute(
            "DELETE FROM events WHERE COALESCE(end_date, start_date) < ?",
            [cutoff],
        )
    return n


# --- ingest run log (data health) ----------------------------------------

def record_ingest_run(source: str, ok: bool, event_count: int,
                      error: Optional[str] = None) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO ingest_runs (source, run_at, ok, event_count, error) "
            "VALUES (?,?,?,?,?)",
            [source, datetime.now(timezone.utc), ok, event_count, error],
        )


def latest_ingest_status() -> list[dict]:
    """Return the most recent ingest run per source, newest first."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT source, run_at, ok, event_count, error
            FROM ingest_runs r
            WHERE run_at = (
                SELECT MAX(run_at) FROM ingest_runs WHERE source = r.source
            )
            ORDER BY source
            """
        ).fetchall()
    out = []
    for source, run_at, ok, count, error in rows:
        out.append({
            "source": source,
            "run_at": run_at.isoformat() if hasattr(run_at, "isoformat") else str(run_at),
            "ok": bool(ok),
            "event_count": count,
            "error": error,
        })
    return out


# --- geocode cache -------------------------------------------------------

def geocache_get(postcode: str) -> Optional[tuple[float, float]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT latitude, longitude FROM geocache WHERE postcode = ?",
            [postcode],
        ).fetchone()
    if row and row[0] is not None:
        return (row[0], row[1])
    return None


def geocache_put(postcode: str, lat: Optional[float], lon: Optional[float]) -> None:
    with connect() as conn:
        conn.execute("DELETE FROM geocache WHERE postcode = ?", [postcode])
        conn.execute(
            "INSERT INTO geocache (postcode, latitude, longitude, updated_at) "
            "VALUES (?,?,?,?)",
            [postcode, lat, lon, datetime.now(timezone.utc)],
        )
