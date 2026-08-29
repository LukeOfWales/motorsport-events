"""Tests for iCalendar serialisation and new query features."""
from datetime import date

from app.ics import build_ics
from app.models import Discipline, Event


def _ev(**kw):
    base = dict(source="t", source_id="1", title="Test Event",
               discipline=Discipline.RALLY, start_date=date(2026, 9, 5))
    base.update(kw)
    return Event(**base)


def test_ics_has_calendar_envelope():
    ics = build_ics([_ev()])
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert ics.rstrip().endswith("END:VCALENDAR")
    assert "VERSION:2.0" in ics


def test_ics_single_day_dtend_is_next_day():
    ics = build_ics([_ev(start_date=date(2026, 9, 5))])
    assert "DTSTART;VALUE=DATE:20260905" in ics
    assert "DTEND;VALUE=DATE:20260906" in ics  # exclusive end


def test_ics_multiday_dtend_is_day_after_end():
    ics = build_ics([_ev(start_date=date(2026, 10, 10), end_date=date(2026, 10, 11))])
    assert "DTSTART;VALUE=DATE:20261010" in ics
    assert "DTEND;VALUE=DATE:20261012" in ics


def test_ics_escapes_special_chars():
    ics = build_ics([_ev(title="Rally, Sprint; test")])
    assert "SUMMARY:Rally\\, Sprint\\; test" in ics


def test_ics_deduplicates_postcode_in_location():
    ics = build_ics([_ev(venue="Walters Arena SA11 5TU", postcode="SA11 5TU")])
    # Postcode already in venue -> not appended twice.
    assert "SA11 5TU, SA11 5TU" not in ics
    assert "LOCATION:Walters Arena SA11 5TU" in ics
