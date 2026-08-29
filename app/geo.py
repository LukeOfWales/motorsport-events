"""Geocoding (UK postcodes) and distance calculation.

Uses postcodes.io — a free, no-key UK postcode API — to turn postcodes into
coordinates. Results are cached in the DB so we don't re-query on every run.
"""
from __future__ import annotations

import math
import re
from typing import Optional

import httpx

from . import config

POSTCODE_RE = re.compile(r"[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}", re.IGNORECASE)
OUTCODE_RE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?$", re.IGNORECASE)

POSTCODES_IO = "https://api.postcodes.io"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points in kilometres."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * r * math.asin(math.sqrt(a))


def distance_from_home(lat: float, lon: float) -> float:
    return round(haversine_km(config.HOME_LAT, config.HOME_LON, lat, lon), 1)


def distance_between(origin: tuple[float, float], lat: float, lon: float) -> float:
    """Distance in km from an arbitrary origin (lat, lon) to a point."""
    return round(haversine_km(origin[0], origin[1], lat, lon), 1)


def extract_postcode(text: str) -> Optional[str]:
    """Pull the first UK postcode out of a blob of text."""
    if not text:
        return None
    m = POSTCODE_RE.search(text)
    if not m:
        return None
    return normalise_postcode(m.group(0))


def normalise_postcode(pc: str) -> str:
    pc = re.sub(r"\s+", "", pc).upper()
    # Insert the canonical space before the final 3 chars.
    if len(pc) > 3:
        pc = pc[:-3] + " " + pc[-3:]
    return pc


def geocode_postcode(client: httpx.Client, postcode: str) -> Optional[tuple[float, float]]:
    """Return (lat, lon) for a full or partial (outcode) postcode, or None."""
    pc = normalise_postcode(postcode)
    compact = pc.replace(" ", "")

    # Full postcode lookup
    try:
        resp = client.get(f"{POSTCODES_IO}/postcodes/{compact}")
        if resp.status_code == 200:
            result = resp.json().get("result")
            if result and result.get("latitude") is not None:
                return (result["latitude"], result["longitude"])
    except httpx.HTTPError:
        pass

    # Fall back to outcode (e.g. "CF10") centroid
    outcode = compact
    m = re.match(r"^([A-Z]{1,2}\d[A-Z\d]?)", compact)
    if m:
        outcode = m.group(1)
    try:
        resp = client.get(f"{POSTCODES_IO}/outcodes/{outcode}")
        if resp.status_code == 200:
            result = resp.json().get("result")
            if result and result.get("latitude") is not None:
                return (result["latitude"], result["longitude"])
    except httpx.HTTPError:
        pass

    return None
