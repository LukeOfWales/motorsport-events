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

## Adding a source

Each source is an **adapter** in `app/adapters/`. Subclass `Adapter` and
implement `fetch()` (and, by convention, a `parse()` the tests can call with a
saved fixture), returning a list of `Event`. Put a postcode in the `postcode`
field (or let `extract_postcode()` pull one from the venue text) so distance
ranking works, then register the adapter in `app/adapters/__init__.py`.

Adapters should be resilient — skip a malformed item rather than failing the
whole feed. The build isolates each adapter, so one failing source won't break
the others (its failure is recorded in the source-status panel).

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
