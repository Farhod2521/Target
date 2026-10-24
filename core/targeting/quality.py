"""Whether a lead campaign may be bought on quality instead of on volume.

The other half of the reporting work, and the half that changes what the
provider does. Sending verdicts back tells a platform which leads were
worth having; this decides whether an ad set is allowed to *optimise*
towards them - which on Meta is the difference between ``LEAD_GENERATION``,
where anybody who submits the form is a success, and ``QUALITY_LEAD``,
where a success is somebody the owner later said yes about.

**It is not free and it is not always better**, which is the entire reason
this module is a set of conditions rather than a switch. A platform
optimising towards a rare event needs enough of them to learn from, and an
ad set asked to find fifty a week in an account that produces twelve does
not merely fail to improve - it under-delivers, because the optimiser
cannot find people it has confidence in and would rather show the ad to
nobody than to somebody it doubts.

So three things have to be true at once, and the third is the honest one:

1. Verdicts are actually being reported. Without them the goal names an
   event the provider has never seen.
2. Enough of them have arrived recently to be worth learning from.
3. **The owner asked for it.** Nothing here flips a campaign onto this goal
   by itself - see :func:`goal_for`, which takes the answer rather than
   deducing it.

No clock and no database, like the rest of this package: the window has
already been counted by the caller and arrives as a number.
"""

from typing import Final, Literal

# The provider vocabulary this module reads and writes.
#
# Meta's words, and named here rather than imported from the catalogue for
# the reason ``core.metrics.outcomes`` states about the same two strings: an
# optimisation goal *is* a provider word, it arrives on a DTO and is stored
# raw, and a set of them is the smallest honest place for a rule about them.
VOLUME_GOAL: Final = "LEAD_GENERATION"
QUALITY_GOAL: Final = "QUALITY_LEAD"

# How far back the qualified leads are counted.
#
# Four weeks rather than one. A week is what the provider's own learning
# phase is measured in, and it is the wrong window to *decide* on: a
# business with a quiet week would be switched off the goal and back on
# again, and each switch restarts the learning it was switched on for.
QUALITY_WINDOW_DAYS: Final = 28

# How many qualified leads in that window before the goal is offered.
#
# **This number is below the provider's own learning-phase rate and that is
# a deliberate, stated compromise.** Meta describes roughly fifty
# optimisation events a week as what an ad set needs to leave the learning
# phase; fifty in four weeks is about a quarter of that. Requiring the full
# rate would mean no customer of this product ever qualified - the
# businesses here run one ad set on a small daily budget - and the feature
# would exist as an unreachable branch.
#
# What makes the compromise defensible is that nothing is forced. This is
# the threshold at which the option is *offered*, with the count shown
# beside it, to somebody who then chooses; an account below it is never
# asked. If the goal turns out to under-deliver in the band between this
# number and the provider's, the evidence arrives as a cost per qualified
# lead that got worse, which is the figure this whole product is built to
# read - and the number to change is this one.
MIN_QUALIFIED_FOR_QUALITY: Final = 50


# What the owner is actually choosing between, in the domain's own words.
#
# Two, and neither of them is the provider's. "volume" is what every
# campaign this product has ever made does - the platform looks for people
# who will submit the form - and "quality" is the same campaign bought
# against the owner's own verdicts instead.
#
# A vocabulary rather than a boolean, and for the reason the two pickers
# beside it on the same screen have one: this is drawn as a choice between
# two named things with a sentence under each, and a control whose states
# are "on" and "off" cannot say what "off" means.
LeadBuying = Literal["volume", "quality"]
BUYING_MODES: Final[tuple[LeadBuying, ...]] = ("volume", "quality")

# What a launch that was never asked is. A campaign with no answer on it
# is bought on volume, so the fallback describes it rather than guessing
# about it.
DEFAULT_BUYING: Final[LeadBuying] = "volume"


def wants_quality(mode: str) -> bool:
    """Whether this answer asks for the quality goal.

    Anything unrecognised reads as volume, which is the safe direction and
    the same one every other mode in this package falls back in: a
    hand-edited form cannot move a campaign onto a goal that changes what
    the money buys.
    """
    return mode.strip().casefold() == "quality"


def is_lead_goal(goal: str) -> bool:
    """Whether this goal is one a quality signal could improve.

    Only the volume goal can be upgraded. A call campaign and a website
    campaign produce no lead row here to have a verdict on, and an
    ad set already on the quality goal has nothing to change.
    """
    return goal.strip().upper() == VOLUME_GOAL


def is_available(*, reporting: bool, qualified_recently: int) -> bool:
    """Whether this account has earned the right to be offered the goal.

    Both conditions, and neither is sufficient. An account reporting
    verdicts with nothing to show for them yet would be optimising towards
    an event that has happened twice; an account with a hundred qualified
    leads and no reporting has told the provider about none of them.

    **No account has earned it at the moment, and the reason is not about
    the account.** The second condition counts verdicts an owner set by
    hand, and there is no screen left to set one on - the marking is
    withdrawn, see ``templates/leads/partials/_live.html``. What that
    leaves is a threshold nobody's count can ever move towards and, worse,
    a campaign bought against an event that stopped arriving: the provider
    accepts the goal and then under-delivers on it, silently, which is the
    exact failure the conditions above exist to prevent.

    One line, and it is the whole switch: :func:`goal_for` below reads
    this, so no spec can name the quality goal while it answers no, and
    ``apps.ads.selectors.quality`` reads it too, so the picker is offered
    to nobody. Restoring the marking is deleting the return under this
    note.

        return reporting and qualified_recently >= MIN_QUALIFIED_FOR_QUALITY
    """
    return False


def goal_for(
    *, preset_goal: str, chosen: bool, reporting: bool, qualified_recently: int
) -> str:
    """Which goal this ad set is actually created with.

    The preset's own goal unless every condition holds, including the
    owner's. ``chosen`` is passed in rather than inferred from the account's
    figures, and that is the load-bearing argument of this function: a
    product that silently moved somebody onto a different optimisation goal
    because they crossed a threshold would be changing what their money buys
    without saying so - and the change is invisible in every screen except
    the one number it moves.

    Safe in the direction that matters. Every way of being wrong here
    returns the goal the campaign would have had anyway.
    """
    if not chosen or not is_lead_goal(preset_goal):
        return preset_goal
    if not is_available(reporting=reporting, qualified_recently=qualified_recently):
        return preset_goal
    return QUALITY_GOAL


__all__ = [
    "BUYING_MODES",
    "DEFAULT_BUYING",
    "MIN_QUALIFIED_FOR_QUALITY",
    "QUALITY_GOAL",
    "QUALITY_WINDOW_DAYS",
    "VOLUME_GOAL",
    "LeadBuying",
    "goal_for",
    "is_available",
    "is_lead_goal",
    "wants_quality",
]
