"""Scheduled auto-refresh: periodically run the ingest pipeline.

Run as a long-lived process:

    python -m app.scheduler                 # default: every 6 hours
    MSE_REFRESH_HOURS=3 python -m app.scheduler

It runs one ingest immediately on startup, then repeats on the interval. Each
run's per-source outcome is recorded in the ingest_runs table (see /api/health).

Alternatively, skip this and drive `python -m app.ingest` from cron/launchd —
see the README. This module is for when you'd rather keep one process running.
"""
from __future__ import annotations

import logging
import os
import signal
import time

import schedule

from . import ingest

log = logging.getLogger("mse.scheduler")

REFRESH_HOURS = float(os.environ.get("MSE_REFRESH_HOURS", "6"))

_running = True


def _stop(signum, frame):  # noqa: ARG001
    global _running
    log.info("Shutting down scheduler (signal %s).", signum)
    _running = False


def _safe_ingest() -> None:
    """Run ingest, never letting an exception kill the scheduler loop."""
    try:
        ingest.run()
    except Exception:  # noqa: BLE001
        log.exception("Ingest run failed; will retry on the next tick.")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    log.info("Scheduler starting; refreshing every %.1f hours.", REFRESH_HOURS)
    _safe_ingest()  # initial run on startup

    schedule.every(REFRESH_HOURS).hours.do(_safe_ingest)
    while _running:
        schedule.run_pending()
        time.sleep(1)
    log.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
