"""Tests for the geo helpers: postcode extraction, normalisation, distance."""
import math

from app import config
from app.geo import (
    distance_from_home,
    extract_postcode,
    haversine_km,
    normalise_postcode,
)


def test_normalise_postcode():
    assert normalise_postcode("cf10 1ep") == "CF10 1EP"
    assert normalise_postcode("CF101EP") == "CF10 1EP"
    assert normalise_postcode(" sa11  5tu ") == "SA11 5TU"


def test_extract_postcode_from_text():
    assert extract_postcode("Walters Arena SA11 5TU (AT Tyres)") == "SA11 5TU"
    assert extract_postcode("Hall Farm, Hundall, DRONFIELD, S18 4BS") == "S18 4BS"
    assert extract_postcode("no postcode here") is None
    assert extract_postcode("") is None


def test_haversine_known_distance():
    # London (51.5074, -0.1278) to Cardiff (51.4816, -3.1791) ~ 211 km.
    d = haversine_km(51.5074, -0.1278, 51.4816, -3.1791)
    assert 200 < d < 220


def test_distance_from_home_zero():
    # Distance from home to home is ~0.
    assert distance_from_home(config.HOME_LAT, config.HOME_LON) < 0.1


def test_distance_from_home_positive():
    # Somewhere clearly far (Edinburgh-ish) should be several hundred km.
    d = distance_from_home(55.95, -3.19)
    assert d > 400
