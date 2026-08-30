# Motorsport Events

Find upcoming UK motorsport events — **rally, trials/RTV, hill climbs, off-road
and circuit racing** — aggregated from many sources into one calendar and
ranked by distance from your postcode.

> **Live site:** https://lukeofwales.github.io/motorsport-events/

![Motorsport Events](docs/screenshot.png)

## Features

- Aggregates 7 sources (AWDC, ALRC, SWLRC, hillclimb.uk, Motorsport UK, MSV,
  Pembrey) with cross-source de-duplication.
- Distance ranking from any UK postcode (geocoded via postcodes.io).
- List, month-calendar and map views.
- Filter by discipline, source, distance, weekend-only, or free-text search.
- "Smart radius" (travel further for a rally than a local trial), saved events,
  new-event badges, and per-event / subscribable calendar (.ics) export.

## How it works

It's a static single-page app with a build-time data step — no server at
runtime:

```
build (Python)                          runtime (browser SPA)
adapters -> normalize -> geocode ->     fetch events.json -> filter / rank by
dedupe -> write site/events.json        distance / search / map / calendar
        |                                        |
   scheduled GitHub Action              geocode your postcode via postcodes.io
   deploys site/ to Pages               and compute distances client-side
```

- **Build** (`app/build_site.py`): runs each source adapter, geocodes venues
  (postcodes.io, file-cached in `data/geocache.json`), de-duplicates across
  sources, drops past events, and writes `site/events.json`.
- **Runtime** (`site/`): `index.html` + `app.js` + `style.css` fetch that JSON
  and do all filtering, distance ranking, search, and map/calendar rendering in
  the browser. Your postcode is geocoded client-side; nothing is sent anywhere.
- **Deploy** (`.github/workflows/deploy.yml`): rebuilds the data daily (and on
  push) and publishes `site/` to GitHub Pages.

## Run it locally

```bash
pip install -r requirements.txt
python -m app.build_site                  # writes site/events.json
cd site && python3 -m http.server 8200    # open http://localhost:8200
```

Or with the Makefile: `make build-site` then `make serve-site`. Run
`make help` for all targets.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Adapters are tested against saved fixtures in `tests/fixtures/` so the fragile
parsing runs offline and deterministically. Date-dependent logic is tested with
`freezegun`, and the network/retry/pagination paths with `pytest-httpx`.
Coverage is reported automatically (`pytest --cov` is on by default).

When a source changes its markup and a parse test fails, re-capture its fixture
(fetch the live page, save it over the old fixture) and update the expected
counts/fields in `tests/test_adapters.py`.

### CI / pre-push

A git pre-push hook runs the tests before any push (the "pre-GitHub" gate).
Install it once after cloning:

```bash
./scripts/install-hooks.sh
```

CI runs on both GitHub Actions (`.github/workflows/`, authoritative) and a local
Forgejo instance (`.forgejo/workflows/`, pre-GitHub). See `docs/forgejo.md`.

## Contributing a source

The app is built to make adding your local club, series or venue calendar
straightforward. Each source is a small self-contained **adapter** in
`app/adapters/`; the build runs them all and merges the results. A failing or
malformed source is skipped (and shown in the source-status panel), so a new
adapter can't break the others.

### 1. Create the adapter

Add `app/adapters/yourclub.py`. Subclass `Adapter`, give it a stable `key` and
a human `name`, and return a list of `Event` from `fetch()`. Split the network
fetch from parsing (a `parse()` method) so it can be unit-tested offline.

```python
from __future__ import annotations

from ..classify import classify          # infer discipline from the title
from ..geo import extract_postcode       # pull a UK postcode out of venue text
from ..models import Discipline, Event
from .base import Adapter

URL = "https://yourclub.example/events"


class YourClubAdapter(Adapter):
    key = "yourclub"                      # short, stable; used as the source id
    name = "Your Club Name"               # shown in the UI

    def fetch(self) -> list[Event]:
        with self.make_client() as client:   # shared httpx client (UA, timeout)
            resp = client.get(URL)
            resp.raise_for_status()
        return self.parse(resp.text)

    def parse(self, html: str) -> list[Event]:
        from bs4 import BeautifulSoup       # bs4 + lxml are available
        soup = BeautifulSoup(html, "lxml")
        events: list[Event] = []
        for row in soup.select(".event"):   # adjust to the page's markup
            title = row.select_one(".title").get_text(strip=True)
            # ... extract a start date, venue text, optional URL ...
            events.append(Event(
                source=self.key,
                source_id=slug,             # stable per-event id within source
                title=title,
                discipline=classify(title), # or set Discipline.RALLY etc. directly
                start_date=start,           # datetime.date
                end_date=end,               # optional (multi-day events)
                venue=venue,
                postcode=extract_postcode(venue),
                url=detail_url,             # optional link to the event page
                organiser=self.name,        # optional
                description=None,           # optional
            ))
        return events
```

Field notes:

- `start_date` / `end_date` are `datetime.date`. Omit `end_date` for single-day
  events.
- Set a `postcode` (or `latitude`/`longitude`) so the event can be
  distance-ranked. If you only have free-text venue, `extract_postcode()` finds
  a UK postcode in it. The build geocodes postcodes via postcodes.io and caches
  the result in `data/geocache.json`.
- `discipline` must be one of `Discipline.{TRIALS, RALLY, HILLCLIMB, OFF_ROAD,
  OTHER}`. Use `classify(title)` to infer it from the event name, or set it
  directly.
- `source_id` must be stable for a given event (a slug, or the source's own id)
  — it's how the same event is recognised across rebuilds.
- Be resilient: skip a malformed row rather than raising, so one bad entry
  doesn't drop the whole feed.

### 2. Register it

Import and add your adapter in `app/adapters/__init__.py`:

```python
from .yourclub import YourClubAdapter

def all_adapters() -> list[Adapter]:
    return [
        # ... existing adapters ...
        YourClubAdapter(),
    ]
```

Order matters for de-duplication: when the same event (same date + postcode)
appears from multiple sources, the one earlier in the list wins and the others
show as "also on ...". Put discipline-specific club sources before broad
aggregators.

### 3. Add a test with a saved fixture

Tests run offline against saved pages, so they're fast and don't depend on the
live site. Save a real response, then assert what your parser produces.

```bash
# capture the page your adapter parses
curl -s https://yourclub.example/events > tests/fixtures/yourclub.html
```

```python
# in tests/test_adapters.py
from app.adapters.yourclub import YourClubAdapter

def test_yourclub_parses_events():
    events = YourClubAdapter().parse(load("yourclub.html"))
    assert len(events) >= 1
    assert all(e.source == "yourclub" and e.title for e in events)
```

Run `pytest`. The pre-push hook runs it too, so a broken parser won't be pushed.

### 4. Verify and open a PR

```bash
python -m app.build_site     # runs your adapter against the live source
make serve-site              # preview at http://localhost:8200
```

Check your events appear with correct dates, venues and distances, then open a
pull request. Please include the fixture and test so the parser stays covered
if the source's markup changes later.

Tip: if a source publishes structured data (an iCal `.ics` feed or schema.org
JSON-LD), prefer parsing that over scraping HTML — it's far more stable. See
`app/adapters/pembrey.py` for a JSON-LD example and `app/adapters/msuk.py` for a
JSON API example.

## Configuration

Home/default location and HTTP behaviour are set in `app/config.py` or via env
vars: `MSE_HOME_POSTCODE`, `MSE_HOME_LAT`, `MSE_HOME_LON`, `MSE_RADIUS_KM`,
`MSE_USER_AGENT`, `MSE_HTTP_TIMEOUT`. The home location is only a default; users
set their own postcode at runtime in the browser.

## Project layout

```
app/
  build_site.py      run adapters -> geocode -> dedupe -> write site/events.json
  models.py          Event + Discipline schema
  config.py          home location, radius, HTTP defaults
  classify.py        infer discipline from event text
  dedupe.py          cross-source de-duplication + weekend detection
  geo.py             postcode geocoding + haversine distance
  adapters/
    base.py          Adapter interface
    <source>.py      one adapter per source (awdc, alrc, swlrc, ...)
site/
  index.html         the SPA
  app.js             client-side filtering/distance/views
  style.css
  events.json        built data (git-ignored; produced by app.build_site)
data/
  geocache.json      cached postcode lookups (git-ignored)
  first_seen.json    first-seen dates for "new" badges (git-ignored)
```

## License

Code is released under the [MIT License](LICENSE) — use, modify and
redistribute freely, with attribution and no warranty.

Note: the license covers this project's **code**, not the event data it
aggregates. Event listings are fetched from third-party sources (clubs, series
and venues) and remain the property of those sites, subject to their own terms.
The built `events.json` is provided for personal use.
