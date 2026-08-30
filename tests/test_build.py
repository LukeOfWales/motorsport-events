"""Tests for the shared dedupe module and the static-site build shaping."""
import importlib
import json
from datetime import date

import pytest

from app.dedupe import dedupe, source_rank, spans_weekend
from app.models import Discipline, Event


def _ev(source, sid, start, postcode=None, end=None, dist=None):
    return Event(source=source, source_id=sid, title=f"{source} {sid}",
                 discipline=Discipline.OTHER, start_date=start, end_date=end,
                 postcode=postcode, distance_km=dist)


def test_source_rank_prefers_clubs_over_msuk():
    assert source_rank("awdc") < source_rank("msuk")
    assert source_rank("unknown") >= source_rank("msuk")


def test_dedupe_merges_same_date_postcode():
    events = [
        _ev("msuk", "1", date(2026, 9, 6), "GL12 7QA"),
        _ev("awdc", "2", date(2026, 9, 6), "GL12 7QA"),
    ]
    out = dedupe(events)
    assert len(out) == 1
    assert out[0].source == "awdc"           # club preferred
    assert out[0].alt_sources == ["msuk"]


def test_dedupe_keeps_no_postcode_events():
    events = [_ev("a", "1", date(2026, 9, 6)), _ev("b", "2", date(2026, 9, 6))]
    assert len(dedupe(events)) == 2


def test_spans_weekend():
    assert spans_weekend(_ev("s", "sat", date(2026, 9, 5)))       # Saturday
    assert not spans_weekend(_ev("s", "tue", date(2026, 9, 8)))   # Tuesday
    # Fri->Mon spans a weekend.
    assert spans_weekend(_ev("s", "span", date(2026, 9, 4), end=date(2026, 9, 7)))


# --- build shaping (no network: patch adapters + geocode) ----------------

@pytest.fixture()
def build_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MSE_SITE_DIR", str(tmp_path / "site"))
    from app import config as config_mod
    importlib.reload(config_mod)
    from app import build_site as bs
    importlib.reload(bs)
    return bs, tmp_path


def test_build_writes_json(build_env, monkeypatch):
    bs, tmp_path = build_env

    # Fake adapter that returns a couple of future events, no network.
    class FakeAdapter:
        key = "fake"
        name = "Fake"
        def fetch(self):
            return [
                Event(source="fake", source_id="1", title="Future Rally",
                      discipline=Discipline.RALLY,
                      start_date=date(2099, 9, 5), postcode="CF10 1EP",
                      latitude=51.68, longitude=-3.13),
                Event(source="fake", source_id="past", title="Old",
                      discipline=Discipline.OTHER, start_date=date(2000, 1, 1)),
            ]

    monkeypatch.setattr(bs, "all_adapters", lambda: [FakeAdapter()])
    # Point the geocache/first_seen files at the tmp data dir to stay isolated.
    monkeypatch.setattr(bs, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(bs, "GEOCACHE_PATH", tmp_path / "data" / "geocache.json")

    out = bs.build()
    payload = json.loads(out.read_text())

    # Past event dropped; future one kept.
    titles = [e["title"] for e in payload["events"]]
    assert "Future Rally" in titles
    assert "Old" not in titles
    # Shape checks.
    assert payload["home"]["postcode"]
    assert payload["count"] == len(payload["events"])
    assert all("is_new" in e for e in payload["events"])
    assert all("fetched_at" not in e for e in payload["events"])
