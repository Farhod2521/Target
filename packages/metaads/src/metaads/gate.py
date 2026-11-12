"""The app-wide call budget, held where every process can see it.

``X-App-Usage`` is one figure for the whole deployment, and the brake in
:mod:`metaads.client` lives one conversation: a worker that saw the budget
at ninety percent stopped its own read, and the worker beside it started
the next account's a moment later. With more workers reading at once that
is how the limit itself is met, and past it Meta refuses every customer
for minutes - the person launching an advert among them.

So the stop is written to a store the caller supplies, and only reads made
in the background meet it. A write, a launch and what a person pressed for
go on as before: they are few, they cannot wait for the next sweep, and
stopping them to protect the sweeps would be the wrong way round.

The package still reads no configuration. Without :func:`install` nothing
here does anything.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final, Protocol

logger = logging.getLogger(__name__)

# How long one sighting holds the background reads back. Meta counts the
# app's budget over a rolling hour; five minutes lets it fall and is short
# enough that a figure read once and wrongly cannot stop a night's work.
# Every answer still over the line starts the wait again.
STOP_SECONDS: Final = 300


class UsageGate(Protocol):
    """Where the stop is kept: Redis in the product, a dict in a test."""

    def stopped(self) -> float | None:
        """The percentage that set the stop, or ``None`` when there is none."""

    def stop(self, percent: float, seconds: int) -> None:
        """Hold background reads back for this long."""


_gate: UsageGate | None = None
_background: ContextVar[bool] = ContextVar("metaads_background_read", default=False)


def install(gate: UsageGate | None) -> None:
    global _gate
    _gate = gate


@contextmanager
def background() -> Iterator[None]:
    """Everything read inside is a sweep's: it can wait for the next one."""
    token = _background.set(True)
    try:
        yield
    finally:
        _background.reset(token)


def enter_background() -> None:
    """:func:`background` for a caller with a start and an end of its own."""
    _background.set(True)


def leave_background() -> None:
    _background.set(False)


def blocked() -> float | None:
    """The stop a background read must respect now. A store that cannot be
    asked blocks nothing: the budget is Meta's to enforce in the end."""
    if _gate is None or not _background.get():
        return None
    try:
        return _gate.stopped()
    except Exception:
        logger.warning("the usage gate could not be read", exc_info=True)
        return None


def note(percent: float) -> None:
    """The app's budget was seen at this figure, by whoever was calling."""
    if _gate is None:
        return
    try:
        _gate.stop(percent, STOP_SECONDS)
    except Exception:
        logger.warning("the usage gate could not be set", exc_info=True)


__all__ = [
    "STOP_SECONDS",
    "UsageGate",
    "background",
    "blocked",
    "enter_background",
    "install",
    "leave_background",
    "note",
]
