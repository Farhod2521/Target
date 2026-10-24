"""The one change the agent makes without asking: stopping money gone for nothing.

Everything else it finds is a proposal with a button. This is not,
because the loss is the whole of the case: a group that has spent more
than half of its day's budget and brought not one result is paying for
nothing while the proposal waits for somebody to read it.

**One rule, and it is the owner's.** No result at all, and more than
:data:`STOP_SHARE_PCT` percent of the day's budget gone. A small budget
has its own bar instead, in the account's currency - half of a small day
is a few cents, and a few cents is not yet a verdict on anything.

**Counted from the last stop.** A group switched back on after one is
judged on what it spends and brings from then on, so switching it on is
never undone at the next update by the money spent before.

Stopping is never refused for learning - see :mod:`core.agent.guardrails` -
and that is why this is allowed at all: it is the stop, not a budget or an
audience, so the learning it ends is learning that was buying nothing.
"""

from dataclasses import dataclass
from typing import Final

# How much of a day's budget may go with nothing back before it is stopped.
STOP_SHARE_PCT: Final = 50


@dataclass(frozen=True, slots=True)
class SmallBudget:
    """Below ``budget_minor`` a day, the bar is ``spend_minor`` instead."""

    budget_minor: int
    spend_minor: int


@dataclass(frozen=True, slots=True)
class Fruitless:
    """One delivering group's money and results since it was last started.

    ``budget_minor`` is its day's budget, its own or its campaign's.
    """

    adset_id: str
    spend_minor: int
    results: int
    budget_minor: int


def must_stop(group: Fruitless, *, small: SmallBudget | None) -> bool:
    """Whether this group has spent past its bar with nothing back."""
    if group.results > 0 or group.budget_minor <= 0:
        return False
    if small is not None and group.budget_minor < small.budget_minor:
        return group.spend_minor > small.spend_minor
    return group.spend_minor * 100 > group.budget_minor * STOP_SHARE_PCT


__all__ = ["STOP_SHARE_PCT", "Fruitless", "SmallBudget", "must_stop"]
