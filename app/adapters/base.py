"""Base adapter interface."""
from __future__ import annotations

import abc

import httpx

from .. import config
from ..models import Event


class Adapter(abc.ABC):
    """A source of motorsport events.

    Subclasses implement `fetch()` and return a list of Events. They should
    not raise on network/parse errors for individual items — log and skip.
    """

    #: Short stable key used as the `source` field on events.
    key: str = ""
    #: Human-readable name for logs/UI.
    name: str = ""

    def make_client(self) -> httpx.Client:
        return httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=True,
        )

    @abc.abstractmethod
    def fetch(self) -> list[Event]:
        """Return normalized events from this source."""
        raise NotImplementedError
