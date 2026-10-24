"""What may be done to something that is already running.

Every change in this product passes through here, whoever asked for it. A
person pressing a button and the agent deciding at three in the morning get
the same answers, because a rule that only one of them obeys is a rule that
will be discovered by whichever one skipped it.

Pure arithmetic over values the caller already holds: no clock, no ORM, no
provider. A verdict is a decision about a described object, not a lookup.

**Refusals carry a code, never a sentence.** ``GuardrailVerdict.reason`` is
one of the ``REFUSED_*`` constants below and the Django layer turns it into
Uzbek. Writing the sentence here would put a language into the domain,
where it can be neither translated nor logged - the same rule
``core/targeting/exceptions`` follows and for the same reason.

One rule is deliberately absent. **Stopping is never refused.** Pausing
throws learning away exactly as a budget edit does, and it is still allowed,
because the object being stopped is spending somebody's money and the
person asking owns it. A product that answers "your ad is still learning"
to "stop my ad" has confused a rule about spending money well with a rule
about spending it at all.
"""

from dataclasses import dataclass
from typing import Final

from core.agent.contracts import GuardrailVerdict

# Why a change was turned away. Codes rather than sentences - see the module
# docstring - and stable, because the Django layer maps them to text and a
# renamed one becomes an untranslated screen.
REFUSED_ALREADY: Final = "already"
REFUSED_FINISHED: Final = "finished"
REFUSED_LEARNING: Final = "learning"
REFUSED_BELOW_FLOOR: Final = "below_floor"
REFUSED_LAST_AD: Final = "last_ad"

# The two delivery states a change can be asked for, as the domain spells
# them. Everything else in ``adskit.Delivery`` describes what the provider
# decided rather than what an advertiser wants.
ACTIVE: Final = "active"
PAUSED: Final = "paused"

# Ran and stopped on its own: end date reached, budget spent, archived.
# Setting it back to active succeeds at the provider and delivers nothing,
# which is the worst of both - a button that works and changes nothing.
FINISHED: Final = "finished"

# Stopped by the provider: refused, or running with a fault it reported.
REJECTED: Final = "rejected"

ALLOWED: Final = GuardrailVerdict(allowed=True, reason="")


@dataclass(frozen=True, slots=True)
class ObjectState:
    """The object a change is aimed at, as it was last read.

    Read fresh before a write rather than taken from the mirror. "Was this
    still learning a quarter of an hour ago" is not the question the
    guardrail is asking, and the mirror is as old as the last sync.

    ``daily_budget_minor`` is ``None`` when the object holds no budget of
    its own - a campaign whose ad sets each carry theirs. That is not zero,
    and a screen showing zero would tell somebody their campaign cannot
    spend when in fact it has four budgets underneath it.
    """

    delivery: str
    is_learning: bool = False
    daily_budget_minor: int | None = None
    # Whether the object has ever spent anything. True unless a caller has
    # looked and found nothing: an unknown is read as "it has", which keeps
    # the learning guard where it was.
    has_spent: bool = True


def check_status_change(*, state: ObjectState, wanted: str) -> GuardrailVerdict:
    """Whether this object can be switched to ``wanted``.

    Two refusals and no third. Asking for the state it is already in is a
    write that would leave an audit row claiming a change nobody made, and
    a finished object cannot be restarted however the switch is set.

    Learning is not consulted. Stopping is how somebody protects
    themselves from a decision this product made, and it has to work while
    the decision is still being made.
    """
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    if state.delivery == wanted:
        return GuardrailVerdict(allowed=False, reason=REFUSED_ALREADY)
    return ALLOWED


def check_budget_change(
    *, state: ObjectState, wanted_minor: int, floor_minor: int
) -> GuardrailVerdict:
    """Whether this object's daily budget may become ``wanted_minor``.

    ``floor_minor`` comes from :func:`core.targeting.daily_floor`, which
    already accounts for the optimisation goal: the provider's reported
    minimum is the floor for an impression goal and roughly double it for
    the rare events this product mostly buys. Zero switches the check off,
    the same as everywhere else an unknown provider value appears - the
    provider still refuses a genuinely low budget on its own.

    This is where learning bites. Editing the budget of an ad set the
    provider is still learning for throws that learning away and starts the
    spend over, and unlike a pause it buys nothing in return: the ad set
    keeps delivering either way, just from a worse starting point.

    Except where nothing has been spent. An ad set the provider calls
    learning that has never been shown has learned nothing, and a budget
    too small to win a single auction is the usual reason it has not -
    refusing the one change that could start it would protect nothing.
    """
    if state.is_learning and state.has_spent:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    if state.daily_budget_minor == wanted_minor:
        return GuardrailVerdict(allowed=False, reason=REFUSED_ALREADY)
    if floor_minor > 0 and wanted_minor < floor_minor:
        return GuardrailVerdict(allowed=False, reason=REFUSED_BELOW_FLOOR)
    return ALLOWED


@dataclass(frozen=True, slots=True)
class AdContext:
    """What an advert's ad set looks like, for a decision about the advert.

    Two facts and neither of them lives on the advert. An ad carries no
    budget and no learning stage - both belong to the group above it - so a
    decision about one is made partly from figures read one level up, and
    saying so in a value is what keeps a caller from silently passing
    ``False`` for something it never looked up.

    ``other_active_ads`` counts the **siblings**, not the ad set's whole
    list: nought means this is the only one still delivering.
    """

    parent_is_learning: bool = False
    other_active_ads: int = 0


def check_ad_pause(*, state: ObjectState, parent: AdContext) -> GuardrailVerdict:
    """Whether one advert inside a group may be switched off.

    **A separate check because stopping an advert is not stopping
    anything.** The rule above - that a stop is never refused - is about an
    owner's ability to stop their own spending, and it holds absolutely at
    the two levels where a stop does that. An advert is not one of them: the
    group keeps its budget and keeps spending it, on whatever adverts are
    left. So this is not a person protecting themselves from a decision;
    it is an optimisation, and it obeys the rules optimisations obey.

    Two refusals of its own, on top of the ordinary ones:

    **The last advert.** Switching off the only one still delivering stops
    the group, silently. Somebody agreed to "turn off the advert that is not
    working", not to "stop my campaign", and a change that quietly does the
    second is worse than one that refuses.

    **A learning parent.** Learning belongs to the ad set and there is no
    such thing at this level, so the question is whether removing an advert
    from the mix counts as the kind of edit that restarts it. The provider's
    own reference does not say, and it cannot be proved either way from
    what we hold - so the asymmetry decides: being wrong here throws away
    days of somebody's budget, and being wrong the other way costs two days
    of waiting. **Openly approximate.**

    **Switching an advert back on is not checked here, deliberately.** It
    may well disturb the same learning, and it is still allowed - because
    it is how somebody undoes a change this product talked them into, and
    "we turned your advert off and will not turn it back on yet" is the one
    answer a product that proposes changes must never give. The same
    reasoning as the rule above about stopping, applied to the reversal.
    """
    if parent.parent_is_learning:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    if parent.other_active_ads <= 0:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LAST_AD)
    return check_status_change(state=state, wanted=PAUSED)


def check_creative_swap(*, state: ObjectState, parent: AdContext) -> GuardrailVerdict:
    """Whether an advert's words and picture may be replaced.

    Replaced is the wrong word for what happens and the right word for what
    somebody asked. No provider allows a creative to be edited, so this is
    a second advert made from the first and the first switched off - which
    is why there is no last-advert rule here, unlike
    :func:`check_ad_pause`. The group cannot go dark: one goes on as the
    other goes off.

    **Learning refuses, and this is the least arguable of the four places
    it does.** A budget edit disturbs learning by degrees and an audience
    edit makes the delivery learned so far irrelevant; a new creative is
    the case the providers themselves name - what is being bought changed,
    so the phase starts over. An advert restaged on day two of learning
    costs two days of somebody's budget and buys nothing.

    **Except for an advert the provider has stopped.** It is delivering
    nothing, so there is no learning of its own to protect, and waiting for
    the group to finish learning keeps the fault running for as long as it
    takes - the replacement is the fix.

    Finished refuses because there is nothing to replace. A new advert
    under a campaign that has stopped is created, delivers to nobody, and
    leaves an audit row claiming a change nobody can see.
    """
    if parent.parent_is_learning and state.delivery != REJECTED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    return ALLOWED


def check_targeting_change(*, state: ObjectState) -> GuardrailVerdict:
    """Whether this object's audience may be replaced.

    Learning refuses, for the same reason it refuses a budget edit and more
    strongly: a new audience is a new problem for the provider to solve, so
    the delivery bought so far is not merely disturbed, it is irrelevant.
    An ad set three days into learning that gets a wider radius starts from
    nothing with three days of somebody's budget already spent.

    Finished refuses because there is nothing to change. Rewriting the
    audience of an ad set that has stopped succeeds at the provider,
    delivers nothing, and leaves an audit row claiming a change that
    affected no one.

    Nothing else is checked here. Whether a wider audience is a *good* idea
    is a question about numbers, and it was answered before this was called
    - see ``core.agent.rules.delivery``.
    """
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    if state.is_learning:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    return ALLOWED


def check_limit_change(*, state: ObjectState) -> GuardrailVerdict:
    """Whether this object's end date or total ceiling may be set.

    **Learning does not refuse here, and that is the whole reason this is
    not :func:`check_budget_change`.** Providers restart the learning phase
    for the edits that change *who or what* is being bought - the audience,
    the creative, the optimisation goal, a budget moved far enough to be a
    different plan. Saying when a campaign should stop, or how much it may
    spend before it does, changes none of those: delivery continues exactly
    as it was until the moment the limit is reached.

    Refusing anyway would be inventing a restriction, which costs somebody
    the one control that answers "make sure this stops" - and they would be
    told to wait several days for it.

    Finished refuses, and for the same reason it refuses everywhere else:
    an end date on a campaign that has already ended, or a ceiling on one
    that will never spend again, succeeds at the provider and changes
    nothing anybody can see.
    """
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    return ALLOWED


def resets_learning(*, state: ObjectState) -> bool:
    """Whether going ahead costs the delivery bought so far.

    For the screen, not for the decision. A stop is allowed while an ad set
    is learning and it still throws that learning away, so the person
    pressing it deserves to be told before rather than after.
    """
    return state.is_learning


__all__ = [
    "ACTIVE",
    "ALLOWED",
    "FINISHED",
    "PAUSED",
    "REFUSED_ALREADY",
    "REFUSED_BELOW_FLOOR",
    "REFUSED_FINISHED",
    "REFUSED_LAST_AD",
    "REFUSED_LEARNING",
    "REJECTED",
    "AdContext",
    "ObjectState",
    "check_ad_pause",
    "check_budget_change",
    "check_creative_swap",
    "check_limit_change",
    "check_status_change",
    "check_targeting_change",
    "resets_learning",
]
