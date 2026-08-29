"""Shared discipline classification.

Adapters that don't get a discipline from their source (most of them) infer it
from the event name/type text. This is the single authoritative keyword map so
the rules stay consistent across sources — refine them here, not per-adapter.

Keywords are checked in order; the first match wins, so list more specific
terms before broader ones (e.g. "stage rally" before "rally", "comp safari"
before "safari").
"""
from __future__ import annotations

from .models import Discipline

# (keyword, discipline). Matched case-insensitively as a substring of the text.
DISCIPLINE_KEYWORDS: list[tuple[str, Discipline]] = [
    # --- Rally (most specific first) ---
    ("rallycross", Discipline.RALLY),
    ("stage rally", Discipline.RALLY),
    ("road rally", Discipline.RALLY),
    ("targa", Discipline.RALLY),
    ("navigation", Discipline.RALLY),
    ("scatter", Discipline.RALLY),

    # --- Off-road ---
    ("cross country", Discipline.OFF_ROAD),
    ("comp safari", Discipline.OFF_ROAD),
    ("ccvt", Discipline.OFF_ROAD),          # Cross-Country Vehicle Trial
    ("ccv", Discipline.OFF_ROAD),           # Cross-Country Vehicle
    ("safari", Discipline.OFF_ROAD),
    ("winch", Discipline.OFF_ROAD),
    ("off road", Discipline.OFF_ROAD),
    ("off-road", Discipline.OFF_ROAD),

    # --- Trials / RTV ---
    ("rtvt", Discipline.TRIALS),            # RTV Trial
    ("rtv", Discipline.TRIALS),             # Road-Taxed Vehicle trial
    ("tyro", Discipline.TRIALS),            # Tyro trial (junior/novice off-road)
    ("pca", Discipline.TRIALS),             # Production Car Autotest / trial
    ("trial", Discipline.TRIALS),           # sporting / car trial

    # --- Hill climb & speed events ---
    ("hill climb", Discipline.HILLCLIMB),
    ("hillclimb", Discipline.HILLCLIMB),
    ("sprint", Discipline.HILLCLIMB),       # speed events grouped with hillclimb
    ("speed", Discipline.HILLCLIMB),

    # --- Broad rally catch-alls (after the specific off-road/trial terms) ---
    ("rally", Discipline.RALLY),
    ("stage", Discipline.RALLY),

    # --- Explicitly Other (not a target discipline) ---
    ("autotest", Discipline.OTHER),
    ("autosolo", Discipline.OTHER),
]


def classify(text: str) -> Discipline:
    """Infer a Discipline from an event name/type string.

    Returns Discipline.OTHER when nothing matches.
    """
    if not text:
        return Discipline.OTHER
    low = text.lower()
    for keyword, discipline in DISCIPLINE_KEYWORDS:
        if keyword in low:
            return discipline
    return Discipline.OTHER
