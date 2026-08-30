"""Tests for the scheduler's error isolation."""
from unittest import mock

from app import scheduler


def test_safe_ingest_swallows_errors():
    # A failing ingest must not propagate (the loop should keep running).
    with mock.patch.object(scheduler.ingest, "run", side_effect=RuntimeError("boom")):
        scheduler._safe_ingest()  # should not raise


def test_safe_ingest_calls_run():
    with mock.patch.object(scheduler.ingest, "run", return_value=42) as m:
        scheduler._safe_ingest()
        m.assert_called_once()
