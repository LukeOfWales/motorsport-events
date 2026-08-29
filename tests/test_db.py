"""Tests for the DuckDB storage layer: upsert, dedup, purge, queries.

Each test runs against a fresh temporary database file so they're isolated
and don't touch the real data/events.duckdb.
"""
import importlib
from datetime import date, timedelta

import pytest


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """A fresh db module bound to a temporary DuckDB file."""
    monkeypatch.setenv("MSE_DB_PATH", str(tmp_path / "test.duckdb"))
    # Reload config + db so they pick up the env override.
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()
    return db_mod


def _event(db, source, source_id, title, disc, start, postcode=None,
           end=None, distance=None):
    from app.models import Discipline, Event
    return Event(
        source=source, source_id=source_id, title=title,
        discipline=Discipline(disc), start_date=start, end_date=end,
        postcode=postcode, distance_km=distance,
    )


def test_upsert_and_count(db):
    evs = [
        _event(db, "awdc", "1", "Trial A", "trials", date(2026, 9, 1), "CF10 1EP"),
        _event(db, "awdc", "2", "Trial B", "trials", date(2026, 9, 2), "SA11 5TU"),
    ]
    db.upsert_events(evs)
    assert db.count_events() == 2


def test_upsert_is_idempotent(db):
    ev = _event(db, "awdc", "1", "Trial A", "trials", date(2026, 9, 1))
    db.upsert_events([ev])
    db.upsert_events([ev])  # same uid
    assert db.count_events() == 1


def test_upsert_preserves_geocode(db):
    # First write with coords, then re-write same uid without coords.
    ev1 = _event(db, "awdc", "1", "Trial", "trials", date(2026, 9, 1),
                 "CF10 1EP", distance=10.0)
    ev1.latitude, ev1.longitude = 51.6, -3.1
    db.upsert_events([ev1])
    ev2 = _event(db, "awdc", "1", "Trial renamed", "trials", date(2026, 9, 1),
                 "CF10 1EP")
    db.upsert_events([ev2])
    rows = db.query_events(start=date(2026, 1, 1), dedupe=False)
    assert rows[0].title == "Trial renamed"
    assert rows[0].latitude == 51.6  # coords preserved
    assert rows[0].distance_km == 10.0


def test_dedupe_merges_same_date_postcode(db):
    # Same event from two sources -> one, with the other as alt_source.
    db.upsert_events([
        _event(db, "awdc", "1", "Ozleworth Trial", "trials",
               date(2026, 9, 6), "GL12 7QA"),
        _event(db, "msuk", "99", "Ozleworth", "trials",
               date(2026, 9, 6), "GL12 7QA"),
    ])
    rows = db.query_events(start=date(2026, 1, 1))
    assert len(rows) == 1
    # AWDC is preferred over MSUK.
    assert rows[0].source == "awdc"
    assert rows[0].alt_sources == ["msuk"]


def test_dedupe_keeps_distinct_dates(db):
    db.upsert_events([
        _event(db, "awdc", "1", "Trial", "trials", date(2026, 9, 6), "GL12 7QA"),
        _event(db, "msuk", "2", "Trial", "trials", date(2026, 9, 7), "GL12 7QA"),
    ])
    rows = db.query_events(start=date(2026, 1, 1))
    assert len(rows) == 2


def test_dedupe_never_merges_missing_postcode(db):
    db.upsert_events([
        _event(db, "awdc", "1", "Event", "other", date(2026, 9, 6)),
        _event(db, "msuk", "2", "Event", "other", date(2026, 9, 6)),
    ])
    rows = db.query_events(start=date(2026, 1, 1))
    assert len(rows) == 2  # both kept


def test_query_filters(db):
    db.upsert_events([
        _event(db, "awdc", "1", "Trial", "trials", date(2026, 9, 1),
               "CF10 1EP", distance=10.0),
        _event(db, "msv", "2", "Race", "other", date(2026, 9, 2),
               "DA3 8NG", distance=200.0),
    ])
    assert len(db.query_events(start=date(2026, 1, 1), disciplines=["trials"])) == 1
    assert len(db.query_events(start=date(2026, 1, 1), sources=["msv"])) == 1
    assert len(db.query_events(start=date(2026, 1, 1), max_distance_km=50)) == 1


def test_distance_filter_excludes_ungeocoded(db):
    # An event with no distance must not pass a distance filter.
    db.upsert_events([
        _event(db, "s", "near", "Near", "other", date(2026, 9, 1),
               "CF10 1EP", distance=10.0),
        _event(db, "s", "noloc", "No location", "other", date(2026, 9, 2)),
    ])
    rows = db.query_events(start=date(2026, 1, 1), max_distance_km=50)
    assert [e.source_id for e in rows] == ["near"]


def test_origin_recomputes_distance(db):
    # Two events with real coords; querying from an origin near one of them
    # should rank/filter by distance to that origin, not the stored home value.
    from app.models import Discipline, Event
    swansea = Event(source="s", source_id="swan", title="Swansea Event",
                    discipline=Discipline.OTHER, start_date=date(2026, 9, 1),
                    latitude=51.62, longitude=-3.94, distance_km=999.0)
    leeds = Event(source="s", source_id="leeds", title="Leeds Event",
                  discipline=Discipline.OTHER, start_date=date(2026, 9, 2),
                  latitude=53.80, longitude=-1.55, distance_km=1.0)
    db.upsert_events([swansea, leeds])
    # Origin = Swansea; only the Swansea event is within 30km.
    rows = db.query_events(start=date(2026, 1, 1),
                           origin=(51.62, -3.94), max_distance_km=30)
    assert [e.source_id for e in rows] == ["swan"]
    assert rows[0].distance_km < 5  # recomputed, not the stored 999


def test_delete_past_events(db):
    today = date(2026, 8, 29)
    db.upsert_events([
        _event(db, "s", "past", "Old", "other", today - timedelta(days=10)),
        _event(db, "s", "today", "Now", "other", today),
        _event(db, "s", "future", "Soon", "other", today + timedelta(days=10)),
    ])
    removed = db.delete_past_events(before=today)
    assert removed == 1
    assert db.count_events() == 2


def test_delete_past_keeps_multiday_still_running(db):
    today = date(2026, 8, 29)
    db.upsert_events([
        _event(db, "s", "run", "Weekend", "other",
               today - timedelta(days=1), end=today + timedelta(days=1)),
    ])
    removed = db.delete_past_events(before=today)
    assert removed == 0  # still running today


def test_sources_with_upcoming(db):
    today = date(2026, 8, 29)
    db.upsert_events([
        _event(db, "awdc", "1", "Upcoming", "trials", today + timedelta(days=5)),
        _event(db, "old", "2", "Past", "other", today - timedelta(days=5)),
    ])
    active = db.sources_with_upcoming(start=today)
    assert active == {"awdc"}


def test_delete_past_events_uses_today_by_default(db):
    from freezegun import freeze_time
    with freeze_time("2026-08-29"):
        db.upsert_events([
            _event(db, "s", "past", "Old", "other", date(2026, 8, 1)),
            _event(db, "s", "future", "Soon", "other", date(2026, 9, 30)),
        ])
        removed = db.delete_past_events()  # no explicit date -> uses today
    assert removed == 1
    assert db.count_events() == 1


def test_replace_source_events_removes_orphans(db):
    # First ingest: two events from source 's'.
    db.replace_source_events("s", [
        _event(db, "s", "1", "Keep", "other", date(2026, 9, 1), "CF10 1EP"),
        _event(db, "s", "2", "Drop", "other", date(2026, 9, 2), "SA11 5TU"),
    ])
    assert db.count_events() == 2
    # Second ingest: source no longer produces event "2".
    db.replace_source_events("s", [
        _event(db, "s", "1", "Keep", "other", date(2026, 9, 1), "CF10 1EP"),
    ])
    rows = db.query_events(start=date(2026, 1, 1), dedupe=False)
    assert {e.source_id for e in rows} == {"1"}  # orphan removed


def test_replace_source_events_ignores_other_sources(db):
    db.upsert_events([
        _event(db, "other", "x", "Untouched", "other", date(2026, 9, 5), "CF10 1EP"),
    ])
    db.replace_source_events("s", [
        _event(db, "s", "1", "New", "other", date(2026, 9, 1), "SA11 5TU"),
    ])
    sources = {e.source for e in db.query_events(start=date(2026, 1, 1), dedupe=False)}
    assert sources == {"other", "s"}


def test_replace_source_events_empty_is_noop(db):
    db.upsert_events([
        _event(db, "s", "1", "Existing", "other", date(2026, 9, 1), "CF10 1EP"),
    ])
    # An empty fetch must not wipe existing data.
    written = db.replace_source_events("s", [])
    assert written == 0
    assert db.count_events() == 1
