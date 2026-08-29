"""Source adapters: each turns a data source into normalized Event objects.

Add a new source by subclassing `Adapter`, implementing `fetch()`, and
registering it in `all_adapters()`. Adapters should be resilient: a failure in
one source must not break the others.
"""
from __future__ import annotations

from .base import Adapter
from .alrc import ALRCAdapter
from .awdc import AWDCAdapter
from .hillclimb_uk import HillclimbUKAdapter
from .msuk import MotorsportUKAdapter
from .msv import MSVAdapter
from .pembrey import PembreyAdapter
from .swlrc import SWLRCAdapter

# .ical.ICalAdapter is a reusable template for any source that publishes an
# iCal (.ics) feed; import and register it here if you find such a feed.


def all_adapters() -> list[Adapter]:
    """Return the enabled adapters, in preference order.

    To add a source: create an Adapter subclass in this package, import it
    above, and append an instance here.
    """
    return [
        SWLRCAdapter(),
        HillclimbUKAdapter(),
        MotorsportUKAdapter(),
        AWDCAdapter(),
        ALRCAdapter(),
        MSVAdapter(),
        PembreyAdapter(),
    ]


def all_sources() -> list[dict]:
    """Return {key, name} for each enabled source, for UI source filters."""
    return [{"value": a.key, "label": a.name} for a in all_adapters()]
