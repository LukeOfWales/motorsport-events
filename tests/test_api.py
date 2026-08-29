"""API integration tests via FastAPI's TestClient.

Uses an isolated temporary DuckDB seeded with a couple of events, so the
endpoints are exercised end to end without touching real data or the network.
"""
import importlib
from datetime import date

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MSE_DB_PATH", str(tmp_path / "api.duckdb"))
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import db as db_mod
    importlib.reload(db_mod)
    db_mod.init_db()

    from app.models import Discipline, Event
    db_mod.upsert_events([
        Event(source="awdc", source_id="1", title="AWDC Trial - Ozleworth",
              discipline=Discipline.TRIALS, start_date=date(2099, 9, 6),
              venue="Ozleworth", postcode="GL12 7QA",
              latitude=51.65, longitude=-2.33, distance_km=58.0),
        Event(source="msv", source_id="2", title="Brands Hatch Race",
              discipline=Discipline.OTHER, start_date=date(2099, 9, 12),
              venue="Brands Hatch", postcode="DA3 8NG",
              latitude=51.36, longitude=0.26, distance_km=250.0),
    ])
    db_mod.record_ingest_run("awdc", ok=True, event_count=1)

    from app import main as main_mod
    importlib.reload(main_mod)
    return TestClient(main_mod.app)


def test_events_endpoint(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    assert all("is_new" in e for e in data["events"])


def test_events_search(client):
    r = client.get("/api/events", params={"search": "ozleworth"})
    assert r.json()["count"] == 1


def test_events_discipline_filter(client):
    r = client.get("/api/events", params={"discipline": "trials"})
    events = r.json()["events"]
    assert len(events) == 1 and events[0]["source"] == "awdc"


def test_ics_feed(client):
    r = client.get("/api/events.ics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r.text
    assert "AWDC Trial" in r.text


def test_single_event_ics(client):
    r = client.get("/api/event/awdc/1.ics")
    assert r.status_code == 200
    assert "BEGIN:VEVENT" in r.text
    assert r.headers["content-disposition"].startswith("attachment")


def test_single_event_ics_404(client):
    r = client.get("/api/event/awdc/does-not-exist.ics")
    assert r.status_code == 404


def test_health_endpoint(client):
    r = client.get("/api/health")
    data = r.json()
    assert data["total_events"] == 2
    sources = {s["source"]: s for s in data["sources"]}
    assert sources["awdc"]["ok"] is True


def test_geocode_endpoint_uses_cache(client):
    # Seed the geocache so no network call is needed.
    from app import db as db_mod
    db_mod.geocache_put("CF10 1EP", 51.4816, -3.1791)
    r = client.get("/api/geocode", params={"postcode": "CF10 1EP"})
    data = r.json()
    assert data["found"] is True
    assert abs(data["latitude"] - 51.4816) < 0.001
