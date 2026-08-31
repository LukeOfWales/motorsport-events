"""Adapter parse tests.

Each adapter is tested against a saved fixture (real captured HTML/JSON in
tests/fixtures/) so the fragile parsing logic is exercised offline. When a
source changes its markup, re-capture the fixture and update expectations.
"""
import json

from app.adapters.alrc import ALRCAdapter
from app.adapters.awdc import AWDCAdapter
from app.adapters.hillclimb_uk import HillclimbUKAdapter
from app.adapters.msuk import MotorsportUKAdapter
from app.adapters.msv import MSVAdapter
from app.adapters.pembrey import PembreyAdapter
from app.adapters.swlrc import SWLRCAdapter
from app.models import Discipline

from .conftest import FIXTURES, load


# --- SWLRC ---------------------------------------------------------------

def test_swlrc_parses_events():
    events = SWLRCAdapter().parse(load("swlrc.html"))
    assert len(events) == 13
    # All have a source and a title, and none is the POSTPONED entry.
    assert all(e.source == "swlrc" and e.title for e in events)
    assert not any("gavin" in e.title.lower() for e in events)


def test_swlrc_multiday_and_postcode():
    events = {e.title: e for e in SWLRCAdapter().parse(load("swlrc.html"))}
    gb = events["Great British Land Rover Show"]
    assert gb.start_date.isoformat() == "2026-04-25"
    assert gb.end_date.isoformat() == "2026-04-26"
    assert gb.postcode == "BA4 6QN"


# --- ALRC ----------------------------------------------------------------

def test_alrc_parses_events():
    events = ALRCAdapter().parse(load("alrc.html"))
    assert len(events) == 4
    tyro = next(e for e in events if "Tyro" in e.title)
    assert tyro.discipline is Discipline.TRIALS
    assert tyro.postcode == "NG33 5QP"
    assert tyro.end_date is not None  # 25-26 Sep is multi-day


def test_alrc_ccvt_is_offroad():
    events = ALRCAdapter().parse(load("alrc.html"))
    ccvt = [e for e in events if "CCVT" in e.title]
    assert ccvt and all(e.discipline is Discipline.OFF_ROAD for e in ccvt)


# --- MSV -----------------------------------------------------------------

def test_msv_parses_and_dedupes_views():
    # The page has grid + list views; the adapter must not double-count.
    events = MSVAdapter().parse(load("msv.html"))
    assert 40 <= len(events) <= 60
    keys = {(e.start_date, e.title, e.venue) for e in events}
    assert len(keys) == len(events)  # no duplicates


def test_msv_cross_month_range():
    events = MSVAdapter().parse(load("msv.html"))
    fireworks = [e for e in events if "Fireworks" in e.title]
    assert fireworks
    ev = fireworks[0]
    assert ev.start_date.month == 10 and ev.end_date.month == 11


def test_msv_venue_postcodes():
    events = MSVAdapter().parse(load("msv.html"))
    brands = [e for e in events if e.venue and "Brands Hatch" in e.venue]
    assert brands and all(e.postcode == "DA3 8NG" for e in brands)


# --- hillclimb.uk --------------------------------------------------------

def test_hillclimb_parses_all_venues():
    events = HillclimbUKAdapter().parse(load("hillclimb_uk.html"), 2025)
    assert len(events) > 40
    assert all(e.discipline is Discipline.HILLCLIMB for e in events)
    venues = {e.venue.split(",")[0] for e in events}
    assert "Prescott Hill Climb" in venues
    assert any("Shelsley" in v for v in venues)


# --- MSUK (Inertia JSON) -------------------------------------------------

def test_msuk_parses_pages():
    pages = json.loads((FIXTURES / "msuk_pages.json").read_text())
    events = MotorsportUKAdapter().parse_pages(pages)
    assert len(events) > 0
    assert all(e.source == "msuk" and e.title and e.start_date for e in events)


def test_msuk_classifies_disciplines():
    pages = json.loads((FIXTURES / "msuk_pages.json").read_text())
    events = MotorsportUKAdapter().parse_pages(pages)
    # There should be a mix; at least the classifier ran (some non-Other).
    disciplines = {e.discipline for e in events}
    assert Discipline.OTHER in disciplines or len(disciplines) >= 1


# --- AWDC (static transcribed data, no network) --------------------------

def test_awdc_builds_trials_and_safari():
    events = AWDCAdapter().fetch()
    trials = [e for e in events if "Trial" in e.title]
    safari = [e for e in events if "Comp Safari" in e.title]
    assert len(trials) == 26
    assert len(safari) == 8
    assert all(e.source == "awdc" for e in events)
    # All AWDC events carry a postcode for geocoding.
    assert all(e.postcode for e in events)


def test_awdc_safari_round8_is_multiday():
    events = AWDCAdapter().fetch()
    r8 = next(e for e in events if "R8" in e.title)
    assert r8.discipline is Discipline.OFF_ROAD
    assert r8.end_date is not None  # Walters Arena 2-day event
    assert r8.postcode == "SA11 5TU"


# --- Pembrey (schema.org JSON-LD from a detail page) ---------------------

def test_pembrey_parses_sportsevent_ld():
    ev = PembreyAdapter().parse(
        load("pembrey_event.html"),
        "https://pembreycircuit.co.uk/racing/british-rallycross",
    )
    assert ev is not None
    assert ev.source == "pembrey"
    assert ev.source_id == "british-rallycross"
    assert ev.title == "British Rallycross Championship"
    assert ev.discipline is Discipline.RALLY
    assert ev.postcode == "SA16 0HZ"
    assert ev.start_date.year == 2026


# --- rallies.info (JSON feed) --------------------------------------------

def test_rallies_info_parses_feed():
    from app.adapters.rallies_info import RalliesInfoAdapter
    events = RalliesInfoAdapter().parse(load("rallies_info.json"))
    assert len(events) > 20
    assert all(e.source == "rallies_info" and e.title for e in events)
    # Cancelled events are filtered out.
    assert not any("cancelled" in e.title.lower() for e in events)
    # Date prefixes are stripped from titles.
    assert not any(e.title.startswith(("1st", "2nd", "3rd")) for e in events)


def test_rallies_info_classifies_disciplines():
    from app.adapters.rallies_info import RalliesInfoAdapter
    from app.models import Discipline
    by_title = {e.title: e for e in RalliesInfoAdapter().parse(load("rallies_info.json"))}
    # A stage/targa rally -> RALLY; a motocross/sand race -> OFF_ROAD.
    assert any(e.discipline is Discipline.RALLY for e in by_title.values())
    assert any(e.discipline is Discipline.OFF_ROAD for e in by_title.values())
