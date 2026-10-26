"""The first days of a new ad group, watched for the two ways they go quiet.

A group this product switched on either starts spending or it does not,
and if it spends it either brings results or it does not. Both silences
are normal for a while and both stop being normal at a known hour - and a
person left to guess which hour that is does one of two things: switches a
healthy group off on its first afternoon, or leaves a stuck one running
for a week. This answers "is it time to say something, and what".

**Two questions, five answers.**

*Nothing spent.* At six hours the provider is usually still reviewing the
advert, and saying so - with how long that can take - is what stops the
switching off and on. At a day, an advert already approved that still
spends nothing is waited for too: nothing spent is nothing to judge by,
and the brief moves no budget before there is - see
:mod:`core.agent.sufficiency`. At two days, with nothing spent either way,
deleting it and making it again is the answer that usually works.

*Money spent, nothing back.* At a day, half a day's budget gone with no
result is worth a word and not a change: the provider is still learning,
and the word says so - but only while there is not enough to judge by, see
:mod:`core.agent.sufficiency`. Past that the group is the agent's own stop
to make (:mod:`core.agent.auto_stop`), and "wait" an hour before "stopped"
would be the product arguing with itself.

**Never a cause it cannot see.** A refused advert, an account the provider
switched off or an unpaid bill each has its own line elsewhere naming the
cause. Saying "raise the budget" over one of those would be wrong advice
dressed as help, so a blocked group gets nothing from here at all.

**The bars are the owner's decision, not a measurement.**
"""

from dataclasses import dataclass
from typing import Final, Literal

from core.agent.sufficiency import enough_to_decide

# When each step is due, in hours since the group was switched on.
FIRST_LOOK_HOURS: Final = 6
DAY_HOURS: Final = 24
LATE_UNSTARTED_HOURS: Final = 48

# After this the group is not new any more, and the running watch has it
# - see :mod:`core.agent.running_watch`.
WATCH_HOURS: Final = 7 * 24

# How much of a day's budget has to be gone, per day watched, before a
# nought means anything.
SPENT_SHARE_PCT: Final = 50

# How far the budget moves on an advert that is approved and spends nothing.
# Larger than the agent's own step on purpose: there is no learning to lose
# yet, and a fifth more rarely changes whether an advert wins any auction.
BUDGET_STEP_PCT: Final = 50

Stage = Literal[
    # Nothing spent at six hours.
    "unstarted",
    # Nothing spent at a day, the advert still under review.
    "in_review",
    # Nothing spent at a day, the advert approved.
    "idle",
    # Nothing spent at two days.
    "stuck",
    # Half a day's budget gone at a day, nothing back, too little to judge.
    "quiet",
    # No longer said - the agent's stop answers it. Kept for the lines
    # already written.
    "fruitless",
    # Past the first week: spent before, nothing on the last finished day.
    "stalled",
    # Past the first week: days without a result, at three, seven, fourteen.
    "dry",
    # Past the first week: the last week's price well above the weeks before.
    "dearer",
    # Past the first week: cheaper than before, and the budget spent up.
    "cheaper",
    # Stopped by the agent itself - see :mod:`core.agent.auto_stop`.
    "stopped",
]

Move = Literal["wait", "budget_up", "budget_down", "pause", "delete", "resume"]


@dataclass(frozen=True, slots=True)
class WatchedGroup:
    """One new group, in the facts these questions need.

    ``hours`` are since it was switched on. ``spend_minor`` and
    ``results`` are since that day began in the account's own calendar -
    the figures are kept per day, and the first day's morning is before
    the switch-on and so holds nothing. ``results`` is ``None`` for a
    group whose results are its showings: it has no "nothing back".

    ``in_review`` means no advert of it is delivering and one is still
    being reviewed. ``blocked`` means something with its own line
    elsewhere stops it. ``owns_budget`` means the daily figure is the
    group's own and not a campaign's shared with other groups.
    """

    adset_id: str
    hours: float
    spend_minor: int
    results: int | None
    daily_budget_minor: int | None
    in_review: bool = False
    blocked: bool = False
    owns_budget: bool = True
    learning: bool = False
    # The provider stopped learning without finishing: its price is no
    # price to move a budget on.
    limited: bool = False
    # What the brief's "enough to judge by" is read on - see
    # :mod:`core.agent.sufficiency`. Since it was switched on, like the spend.
    impressions: int = 0
    link_clicks: int = 0
    usual_cost_minor: int | None = None


@dataclass(frozen=True, slots=True)
class Watch:
    """What is due: the step, the buttons, and which one is advised.

    ``tag`` tells two sayings of one stage apart - a second dry spell, a
    later week - so each is new news once. ``step_pct`` is how far the
    budget buttons move it.
    """

    stage: Stage
    moves: tuple[Move, ...]
    advised: Move
    tag: str = ""
    step_pct: int = BUDGET_STEP_PCT


def watch(group: WatchedGroup) -> Watch | None:
    """What to say about this group now, or nothing."""
    if group.blocked or not FIRST_LOOK_HOURS <= group.hours < WATCH_HOURS:
        return None
    if group.spend_minor <= 0:
        return _unstarted(group)
    return _quiet(group)


def moved_budget(
    *, budget_minor: int, move: Move, step_pct: int = BUDGET_STEP_PCT
) -> int:
    """The daily figure a budget button sets. Never zero."""
    sign = {"budget_up": 1, "budget_down": -1}.get(move, 0)
    return max(1, round(budget_minor * (100 + sign * step_pct) / 100))


def _unstarted(group: WatchedGroup) -> Watch:
    if group.hours >= LATE_UNSTARTED_HOURS:
        return Watch(stage="stuck", moves=("delete", "wait"), advised="delete")
    if group.hours < DAY_HOURS:
        return Watch(stage="unstarted", moves=("wait",), advised="wait")
    if group.in_review:
        return Watch(stage="in_review", moves=("wait",), advised="wait")
    return Watch(stage="idle", moves=("wait",), advised="wait")


def _quiet(group: WatchedGroup) -> Watch | None:
    budget = group.daily_budget_minor
    if group.results is None or group.results > 0 or not budget:
        return None
    if group.hours < DAY_HOURS or not _spent(group):
        return None
    if enough_to_decide(
        spend_minor=group.spend_minor,
        usual_cost_minor=group.usual_cost_minor,
        impressions=group.impressions,
        link_clicks=group.link_clicks,
    ):
        return None
    return Watch(stage="quiet", moves=("wait",), advised="wait")


def _spent(group: WatchedGroup) -> bool:
    budget = group.daily_budget_minor or 0
    return group.spend_minor * 100 >= budget * SPENT_SHARE_PCT


__all__ = [
    "BUDGET_STEP_PCT",
    "DAY_HOURS",
    "FIRST_LOOK_HOURS",
    "LATE_UNSTARTED_HOURS",
    "SPENT_SHARE_PCT",
    "WATCH_HOURS",
    "Move",
    "Stage",
    "Watch",
    "WatchedGroup",
    "moved_budget",
    "watch",
]
