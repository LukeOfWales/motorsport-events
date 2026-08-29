"""Date-dependent and network-layer tests.

These cover behaviour that the offline parse tests don't:
  - logic keyed off `date.today()` (frozen with freezegun)
  - the fetch() network path incl. retries and pagination (mocked with
    pytest-httpx so no real requests are made)
"""
import json

import httpx
import pytest
from freezegun import freeze_time

from app.adapters.hillclimb_uk import HillclimbUKAdapter
from app.adapters.msuk import MotorsportUKAdapter
from app.adapters.swlrc import SWLRCAdapter

from .conftest import FIXTURES, load


# --- SWLRC fetch path: retry then parse -----------------------------------

def test_swlrc_fetch_retries_then_succeeds(httpx_mock):
    # First attempt times out, second returns the fixture. fetch() should
    # transparently retry and still parse the events.
    httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    httpx_mock.add_response(text=load("swlrc.html"))
    events = SWLRCAdapter().fetch()
    assert len(events) == 13


def test_swlrc_fetch_gives_up_after_retries(httpx_mock):
    for _ in range(3):
        httpx_mock.add_exception(httpx.ReadTimeout("slow"))
    with pytest.raises(Exception):
        SWLRCAdapter().fetch()


# --- hillclimb.uk year fallback -------------------------------------------

@freeze_time("2026-08-29")
def test_hillclimb_prefers_current_year(httpx_mock):
    # 2026 page exists -> it should be used and events dated 2026.
    httpx_mock.add_response(url="https://hillclimb.uk/2026-hillclimb-dates/",
                            text=load("hillclimb_uk.html"))
    events = HillclimbUKAdapter().fetch()
    assert events
    assert all(e.start_date.year == 2026 for e in events)


@freeze_time("2026-08-29")
def test_hillclimb_falls_back_to_next_then_prev_year(httpx_mock):
    # Current + next year 404, previous year (2025) serves -> used as 2025.
    httpx_mock.add_response(url="https://hillclimb.uk/2026-hillclimb-dates/",
                            status_code=404)
    httpx_mock.add_response(url="https://hillclimb.uk/2027-hillclimb-dates/",
                            status_code=404)
    httpx_mock.add_response(url="https://hillclimb.uk/2025-hillclimb-dates/",
                            text=load("hillclimb_uk.html"))
    events = HillclimbUKAdapter().fetch()
    assert events
    assert all(e.start_date.year == 2025 for e in events)


# --- MSUK pagination + from_date ------------------------------------------

@freeze_time("2026-08-29")
def test_msuk_fetch_paginates(httpx_mock):
    pages = json.loads((FIXTURES / "msuk_pages.json").read_text())
    # Force the loop to stop after our two fixture pages by capping total_pages.
    p1 = dict(pages[0]); p1["props"] = dict(p1["props"]); p1["props"]["total_pages"] = 2
    p2 = dict(pages[1]); p2["props"] = dict(p2["props"]); p2["props"]["total_pages"] = 2
    httpx_mock.add_response(json=p1)
    httpx_mock.add_response(json=p2)
    events = MotorsportUKAdapter().fetch()
    assert len(events) > 0
    # The request must carry today's date as from_date.
    first_req = httpx_mock.get_requests()[0]
    assert "from_date=2026-08-29" in str(first_req.url)
