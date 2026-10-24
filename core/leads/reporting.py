"""Which verdicts go back to the provider, and when.

The rules behind the one thing this product knows that no ad platform can
find out: whether the person who filled in the form was worth having. A
platform optimises towards the event it is told about, and left alone the
only event it can see is a submission - so an account measuring a cost per
*qualified* lead while the platform buys submissions is paying for one
thing and counting another.

Everything here is arithmetic over values the caller already holds. No
clock, no database, no provider: ``now`` arrives as an argument, the
verdicts arrive as a sequence, and what comes back is which of them to
send. That is what lets the awkward half - "is this one too old", "has
somebody changed their mind since" - be tested without a fixture.

**Two windows, and confusing them is the whole difficulty of this module.**

* The **settle** window is ours and protects the *provider* from us. A
  verdict is not sent the instant a button is pressed, because a platform
  cannot un-learn: a misclick corrected forty seconds later would already
  have taught an optimiser that the wrong sort of person is the right sort,
  and nothing can retract it. Waiting costs nothing - optimisation happens
  over days - and it turns a class of permanent mistakes into no mistake at
  all.

* The **report** window is the provider's and protects *us* from it. Every
  platform refuses an event stamped further back than some limit, and
  refuses it quietly, with a success and a count that is simply lower than
  the batch. A verdict that has failed to send for longer than that will
  never land, and going on retrying it is a sweep that never empties.

They point in opposite directions - one delays sending, the other gives up
on it - and between them they are why this is a module rather than a
``filter`` in a selector.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from adskit import LeadStage

# How long a verdict has to stand before it is sent.
#
# Thirty minutes, and the number is chosen against the mistake rather than
# against the clock. What this exists to catch is somebody pressing the
# wrong button and noticing - which happens while they are still looking at
# the screen, or not at all - so the useful length is "the rest of this
# sitting" and not "long enough to be sure".
#
# Longer would cost nothing on the provider's side and something real on
# ours: a customer who marks twenty leads and expects the account to start
# learning would be told about a delay measured in hours. Shorter stops
# catching the correction.
SETTLE_MINUTES: Final = 30

# What a verdict is, stripped of everything a database knows about it.
#
# ``lead_external_id`` is the provider's own id for the person, which is
# the only handle that crosses back - see :class:`adskit.dto.LeadEventDTO`
# for why nothing else may.


@dataclass(frozen=True, slots=True)
class Verdict:
    """One judgement, as the rules below need it.

    ``decided_at`` is when somebody said it, not when the lead arrived. It
    is both halves of this module's arithmetic: the settle window measures
    forward from it, the provider's window measures back to it, and it is
    what gets stamped on the event as the moment the thing happened.

    ``value_minor`` is present only on a sale and carries its currency with
    it, like every other amount in this codebase. The two travel together
    or not at all - an amount without a currency is not an amount - and the
    DTO one layer down refuses the pair on any stage but a sale.
    """

    lead_external_id: str
    status: str
    decided_at: datetime
    value_minor: int | None = None
    currency: str = ""


# What each verdict the product can hold is called on the way out.
#
# A mapping rather than a pass-through, and it earns its place by being
# incomplete. The status column is deliberately wider than the two values a
# person can choose - a CRM writing its own funnel words is the next source
# of these rows - so a word nobody has mapped must produce *nothing to
# send*, not an event named after a string that arrived from outside.
STAGE_OF: Final[dict[str, LeadStage]] = {
    "qualified": "qualified",
    "unqualified": "unqualified",
    "converted": "converted",
}


def stage_of(status: str) -> LeadStage | None:
    """The stage this verdict reports as, or nothing at all.

    ``None`` is a real answer and the safe one. An unmapped status means a
    party this product has not taught the provider about, and the honest
    response is silence: an event sent under a guessed name is counted by
    nothing and cannot be withdrawn.
    """
    return STAGE_OF.get(status.strip().casefold())


def event_key(*, provider: str, lead_external_id: str, stage: str) -> str:
    """The idempotency key one verdict is sent under.

    Built out of the verdict rather than generated, and that is the whole
    design. Every platform de-duplicates on this string, and the retry this
    product performs - a sweep, running again over anything unacknowledged -
    is exactly the traffic that needs de-duplicating: the same judgement
    resent after a worker restart has to count once.

    **The stage is part of the key on purpose.** An owner who changes their
    mind produces a genuinely different event, and it must not be
    de-duplicated away against the one it replaces. What that cannot do is
    *retract* the first - no platform allows it - which is the reason the
    settle window above exists.
    """
    return f"{provider}:{lead_external_id}:{stage}"


def is_settled(*, decided_at: datetime, now: datetime, minutes: int) -> bool:
    """Whether this verdict has stood long enough to be worth sending."""
    return now - decided_at >= timedelta(minutes=minutes)


def is_reportable(*, decided_at: datetime, now: datetime, window_days: int) -> bool:
    """Whether the provider would still count an event stamped this far back.

    A verdict past the window is not a failure and is not retried. Its lead
    was judged, the figure this product shows is built on that judgement,
    and the only thing lost is one training example on somebody else's
    optimiser - which is a smaller loss than a sweep that grows a permanent
    tail of rows it can never clear.
    """
    return now - decided_at <= timedelta(days=window_days)


def due(
    *,
    verdicts: Iterable[Verdict],
    now: datetime,
    window_days: int,
    settle_minutes: int = SETTLE_MINUTES,
) -> tuple[tuple[Verdict, LeadStage], ...]:
    """The verdicts to send now, each with the stage it goes out as.

    Both windows and the vocabulary check, in the one place. The caller has
    already narrowed to rows that have not been reported; what is left is
    the three reasons a row that looks ready is not - it is too new, it is
    too old, or nobody taught the provider a name for it.

    Paired with the stage rather than returning bare verdicts, because the
    caller needs it twice - once for the event and once for the key - and
    looking it up again is how the two come to disagree.
    """
    ready: list[tuple[Verdict, LeadStage]] = []
    for verdict in verdicts:
        stage = stage_of(verdict.status)
        if stage is None:
            continue
        if not is_settled(
            decided_at=verdict.decided_at, now=now, minutes=settle_minutes
        ):
            continue
        if not is_reportable(
            decided_at=verdict.decided_at, now=now, window_days=window_days
        ):
            continue
        ready.append((verdict, stage))
    return tuple(ready)


def expired(
    *, verdicts: Iterable[Verdict], now: datetime, window_days: int
) -> tuple[Verdict, ...]:
    """The ones the provider will never count, however often they are sent.

    Answered separately from :func:`due` rather than inferred from what it
    left out, because the caller does two different things with the two
    lists: one is posted, and one is marked so the sweep stops carrying it.
    A row that is merely settling must not be marked, and the difference
    between "not yet" and "never" is invisible from the outside.
    """
    return tuple(
        verdict
        for verdict in verdicts
        if not is_reportable(
            decided_at=verdict.decided_at, now=now, window_days=window_days
        )
    )


__all__ = [
    "SETTLE_MINUTES",
    "STAGE_OF",
    "Verdict",
    "due",
    "event_key",
    "expired",
    "is_reportable",
    "is_settled",
    "stage_of",
]
