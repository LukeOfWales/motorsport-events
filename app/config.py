"""Configuration and constants."""
from __future__ import annotations

import os
from pathlib import Path

# Project paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = Path(os.environ.get("MSE_DB_PATH", DATA_DIR / "events.duckdb"))

# Home location: CF10 1EP (Cardiff, South Wales).
# Coordinates are approximate centre of the postcode district.
HOME_POSTCODE = os.environ.get("MSE_HOME_POSTCODE", "CF10 1EP")
HOME_LAT = float(os.environ.get("MSE_HOME_LAT", "51.4816"))
HOME_LON = float(os.environ.get("MSE_HOME_LON", "-3.1791"))

# Default "near me" radius in km.
DEFAULT_RADIUS_KM = float(os.environ.get("MSE_RADIUS_KM", "150"))

# Optional per-discipline radius overrides (km). You'll travel further for a
# championship rally than a local trial. When a discipline isn't listed, the
# request's radius (or DEFAULT_RADIUS_KM) applies. Applied server-side only
# when the client asks for it (per_discipline_radius=true).
DISCIPLINE_RADIUS_KM = {
    "rally": 300,
    "hillclimb": 200,
    "off_road": 200,
    "trials": 100,
    "other": 150,
}

# Polite HTTP defaults for scrapers.
USER_AGENT = os.environ.get(
    "MSE_USER_AGENT",
    "motorsport-events/0.1 (personal event aggregator)",
)
HTTP_TIMEOUT = float(os.environ.get("MSE_HTTP_TIMEOUT", "45"))
