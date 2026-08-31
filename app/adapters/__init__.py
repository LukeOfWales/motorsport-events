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
from .rallies_info import RalliesInfoAdapter
from .swlrc import SWLRCAdapter


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
        RalliesInfoAdapter(),
    ]
