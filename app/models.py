"""Core data models for motorsport events."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Discipline(str, Enum):
    """Motorsport disciplines we track."""
    TRIALS = "trials"             # RTV / trials / off-road trials
    RALLY = "rally"               # Rallying (stage, targa, road rally, WRC, rallycross)
    HILLCLIMB = "hillclimb"       # Speed hill climbs & sprints
    OFF_ROAD = "off_road"         # General off-road racing
    OTHER = "other"               # Anything else from Motorsport UK etc.

    @property
    def label(self) -> str:
        return {
            Discipline.TRIALS: "Trials / RTV",
            Discipline.RALLY: "Rally",
            Discipline.HILLCLIMB: "Hill Climb",
            Discipline.OFF_ROAD: "Off-Road",
            Discipline.OTHER: "Other",
        }[self]


class Event(BaseModel):
    """A normalized motorsport event from any source."""

    # Stable identity: source-provided id namespaced by source key.
    # Used for de-duplication across scraper runs.
    source: str = Field(..., description="Adapter/source key, e.g. 'awdc'")
    source_id: str = Field(..., description="Stable id within the source")

    title: str
    discipline: Discipline
    start_date: date
    end_date: Optional[date] = None

    # Location
    venue: Optional[str] = None
    postcode: Optional[str] = None

    # Geocoded (filled in later); distance_km computed from home location.
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: Optional[float] = None

    # Extra
    organiser: Optional[str] = None
    url: Optional[str] = None
    description: Optional[str] = None

    # Populated during de-duplication when the same event is listed by other
    # sources (e.g. an AWDC trial also on Motorsport UK). Each entry is a
    # source key. Empty when there are no duplicates.
    alt_sources: list[str] = Field(default_factory=list)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"
