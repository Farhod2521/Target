"""A group past its first week, watched for as long as it runs.

The first week has its own steps - see :mod:`core.agent.launch_watch` -
and they end there because a new group's questions do: has it started,
has it brought anything. A group that is a month old has other ones, and
nobody else asks them of every group: the agent's rules wait for an
account's usual price and skip learning groups, and the morning report
speaks once a day about the day before. So this asks them, on finished
days only, and says something exactly when a line is crossed.

**Four lines.**

*Nothing spent.* A group that spent before and spent nothing on the last
finished day is not running, whatever its switch says.

*Nothing back.* Days since its last result, said at three, seven and
fourteen of them - each once per dry spell - and only when the money gone
in that time would have bought at least one result at what one usually
costs - the night's usual price, the one every card quotes; the budget is
the bar only where none exists.

*Dearer.* The brief's one "dearer": the last three finished days against
the usual price - the fortnight's median day - past twice it and on three
results' usual price spent - see :func:`core.agent.usual.price_level`. Said only for a
group whose budget is not its own: one that has its own is answered by the
night's budget card on the same reading, and a message beside the card
would say it twice.

*Cheaper, and short of money.* The same comparison the other way, said
only when the budget is already being spent to the end: a cheap group
that is not using what it has does not need more.

**The bars are the owner's decision, not a measurement.**
"""

from dataclasses import dataclass
from datetime import date
from typing import Final

from core.agent.launch_watch import Move, Watch, WatchedGroup
from core.agent.sufficiency import enough_spent, enough_to_decide
from core.agent.usual import price_level

# How many finished days count as "the last week", and how many before
# them are what it is compared against.
RECENT_DAYS: Final = 7
BEFORE_DAYS: Final = 21

# Days without a result at which it is said. Each once per dry spell.
DRY_STEPS: Final = (3, 7, 14)

# Results a price needs on each side before it is compared at all.
MIN_RESULTS: Final = 5

# How much cheaper than the weeks before, in percent of them, is worth more money.
CHEAPER_PCT: Final = 70

# How much of a week's budget counts as spent to the end.
SPENT_UP_PCT: Final = 90

# How many finished days with nothing spent still read as "it stopped". A
# longer run is a group somebody paused and switched back on, not one that
# stalled: the days it was off are not news about today.
MAX_STALLED_DAYS: Final = 3

# How far the budget moves on a running group. The agent's own step:
# past the first week there is learning to lose.
RUNNING_STEP_PCT: Final = 20


@dataclass(frozen=True, slots=True)
class Tally:
    """Money and results over some finished days."""

    spend_minor: int = 0
    results: int = 0


@dataclass(frozen=True, slots=True)
class Running:
    """A group past its first week, in finished days.

    ``dry_days`` count back from the last finished day to the last one
    with a result, or to the day it was switched on if it never had one;
    ``dry_spend_minor`` is what those days cost, and ``spell`` names the
    spell: the group's results ever, which stay put while nothing comes
    and change the day something does - so a spell is told once however
    far it slides back. ``expected_cost_minor``
    is what one result usually costs - the price the night's diagnosis
    quotes - or ``None`` when it quotes none; ``dry_impressions`` and
    ``dry_link_clicks`` are what the spell bought, the brief's bar then.
    ``idle_days`` count back the finished days with nothing spent, and are
    ``0`` when the figures for them are not in yet; ``spent_before`` says
    whether the day before them spent.
    ``before_days`` is how many days ``before`` covers - fewer than
    :data:`BEFORE_DAYS` on a young group. ``week`` names the last finished
    day's week, so a price is said once a week and not every quarter hour.
    ``last`` is the last three finished days and ``usual_cost_minor`` the
    usual price last night quoted, which they are held against - the
    brief's "dearer".
    """

    dry_days: int
    dry_spend_minor: int
    spell: int
    expected_cost_minor: int | None
    recent: Tally
    before: Tally
    idle_days: int
    idle_since: date | None
    spent_before: bool
    week: str
    dry_impressions: int = 0
    dry_link_clicks: int = 0
    before_days: int = BEFORE_DAYS
    last: Tally = Tally()
    usual_cost_minor: int | None = None


def running_watch(group: WatchedGroup, facts: Running) -> Watch | None:
    """What to say about a group past its first week, or nothing."""
    return (
        _stalled(group, facts)
        or _dry(group, facts)
        or _dearer(group, facts)
        or _cheaper(group, facts)
    )


def _stalled(group: WatchedGroup, facts: Running) -> Watch | None:
    if group.spend_minor > 0 or group.in_review:
        return None
    if not 1 <= facts.idle_days <= MAX_STALLED_DAYS or not facts.spent_before:
        return None
    # Days with nothing spent are nothing to judge by, and the brief moves
    # no budget before there is - see ``core.agent.sufficiency``.
    return Watch(
        stage="stalled",
        moves=("wait",),
        advised="wait",
        tag=str(facts.idle_since or ""),
        step_pct=RUNNING_STEP_PCT,
    )


def _dry(group: WatchedGroup, facts: Running) -> Watch | None:
    if group.results is None or group.results > 0:
        return None
    step = max((days for days in DRY_STEPS if days <= facts.dry_days), default=0)
    if not step or not _dry_enough(group, facts, step=step):
        return None
    # A stop is a decision, and the brief decides on three results' worth
    # gone - or, where no price says what that is, on the showings and
    # clicks the card and the agent's own stop read.
    enough = enough_to_decide(
        spend_minor=facts.dry_spend_minor,
        usual_cost_minor=facts.expected_cost_minor,
        impressions=facts.dry_impressions,
        link_clicks=facts.dry_link_clicks,
    )
    advised: Move = "pause" if enough else "wait"
    if group.learning and step == DRY_STEPS[0]:
        advised = "wait"
    return Watch(
        stage="dry",
        moves=("pause", "wait"),
        advised=advised,
        tag=f"{step}:{facts.spell}",
        step_pct=RUNNING_STEP_PCT,
    )


def _dry_enough(group: WatchedGroup, facts: Running, *, step: int) -> bool:
    """Whether the money gone would have bought a result by now."""
    if facts.expected_cost_minor:
        return facts.dry_spend_minor >= facts.expected_cost_minor
    budget = group.daily_budget_minor or 0
    # No price anywhere: half a day's budget per dry day, the first
    # week's own bar.
    return budget > 0 and facts.dry_spend_minor * 2 >= budget * step


def _dearer(group: WatchedGroup, facts: Running) -> Watch | None:
    if not _priced(group) or _may_move_budget(group):
        return None
    level = price_level(
        spend_minor=facts.last.spend_minor,
        count=facts.last.results,
        usual_cost_minor=facts.usual_cost_minor,
        window_spend_minor=facts.recent.spend_minor,
    )
    if level != "act" or not facts.last.results:
        return None
    return Watch(
        stage="dearer",
        moves=("pause", "wait"),
        advised="pause",
        tag=facts.week,
        step_pct=RUNNING_STEP_PCT,
    )


def _cheaper(group: WatchedGroup, facts: Running) -> Watch | None:
    ratio = _ratio(facts)
    if ratio is None or not _priced(group) or facts.recent.results < MIN_RESULTS:
        return None
    # More money is a budget change, and the brief makes none before three
    # results' usual price is spent.
    if not enough_spent(
        spend_minor=facts.recent.spend_minor, usual_cost_minor=facts.usual_cost_minor
    ):
        return None
    if ratio > CHEAPER_PCT or not _may_move_budget(group):
        return None
    budget = group.daily_budget_minor or 0
    if facts.recent.spend_minor * 100 < budget * RECENT_DAYS * SPENT_UP_PCT:
        return None
    return Watch(
        stage="cheaper",
        moves=("budget_up", "wait"),
        advised="budget_up",
        tag=facts.week,
        step_pct=RUNNING_STEP_PCT,
    )


def _ratio(facts: Running) -> int | None:
    """The last week's price as a percentage of the weeks before, or nothing.

    Nothing until the weeks before have enough results to be a price.
    """
    before, recent = facts.before, facts.recent
    if before.results < MIN_RESULTS or before.spend_minor <= 0 or not recent.results:
        return None
    return (recent.spend_minor * before.results * 100) // (
        before.spend_minor * recent.results
    )


def _priced(group: WatchedGroup) -> bool:
    """Whether the group's price is a price: not learning, and not stuck.

    A group the provider stopped learning on gets too few results a week
    for its price to say anything - the agent's own rules skip it too.
    """
    return not group.learning and not group.limited


def _may_move_budget(group: WatchedGroup) -> bool:
    """A button only on a budget that is the group's own, and a real price."""
    return group.owns_budget and bool(group.daily_budget_minor) and _priced(group)


__all__ = [
    "BEFORE_DAYS",
    "CHEAPER_PCT",
    "DRY_STEPS",
    "MAX_STALLED_DAYS",
    "MIN_RESULTS",
    "RECENT_DAYS",
    "RUNNING_STEP_PCT",
    "SPENT_UP_PCT",
    "Running",
    "Tally",
    "running_watch",
]
