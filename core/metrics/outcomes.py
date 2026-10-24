"""What one result is, for each thing an ad set can be told to optimise for.

The one table, and the reason it is here rather than in any of the four
places that read it. "Did this ad set produce results" and "what *is* a
result for this ad set" are different questions, and only the second one
has an answer that does not depend on how the week went.

**A campaign is bought for one kind of outcome and every figure about it
has to be denominated in that outcome.** A form campaign's is a lead - a
person in this product's own table, with a name and a telephone number. A
chat campaign's is a conversation, on the provider's own surface, in an
inbox nothing here reads. A call campaign's happens on a telephone, a
traffic campaign's is somebody arriving on the advertiser's own site, and
an awareness campaign's is having been seen at all.

They are **never interchangeable and never added together**, which is what
this table exists to make impossible to get wrong. Counting a conversation
as a lead would put a number into the cost per lead with no lead behind
it; counting it as nothing tells a chat advertiser they got nought results
out of money that was working, and nothing on the screen says why.

**The vocabulary is the provider's on the left and ours on the right.** An
optimisation goal *is* a provider word: it arrives on the port's own DTO
and is stored raw, so a table keyed on one is the smallest honest place
for this. What crosses back is our own word for the kind of thing, never
Meta's - so nothing above this module has to know which goal produced
which kind.

**An allowlist, and the direction is the whole safety of it.** A goal not
named below answers ``"none"``: a campaign somebody built by hand in the
provider's console, a goal Meta adds next year, an ad set the mirror has
not caught up with and whose goal is still an empty string. Pointed the
other way it would be a rule that judges an unknown ad set as though it
collected leads, finds none, and proposes stopping a campaign whose
telephone is ringing. The two mistakes are not the same size: this way
round the cost is a figure nobody was shown, and the other way round it is
a proposal that destroys a working campaign.
"""

from collections.abc import Iterable, Mapping
from typing import Final, Literal

# The kinds of result this product can put a number against, in our own
# words rather than the provider's.
#
# Seven rather than a boolean, and the two that share a column are still
# two: a conversation and a confirmed call arrive in the same ``actions``
# array and are the same integer to the fact table, and they are different
# things to the person reading the screen. "Suhbat narxi" over a count of
# telephone calls is exactly the silent mistake this type exists to
# prevent.
#
#   lead     a form the provider hosts, whose submissions arrive here by
#            webhook and get a row in this product's own table
#   chat     a thread opened on the provider's own surface
#   call     a telephone that rang, and the provider confirmed it
#   view     the advert was on a screen. Bought to be seen
#   click    somebody left for the advertiser's own site
#   recall   the provider's estimate of who would remember the advert
#   profile  a visit to the business's own Instagram profile, counted by
#            the provider in its ``results`` field rather than in actions
#   site_lead  a form on the advertiser's own website, counted by their
#            pixel. No row here and no webhook: the count is the
#            provider's, and the screens say so. Never a ``lead`` - see
#            :func:`outcome_for`
#   none     nothing this product can count. A purchase on somebody
#            else's website, or a goal nobody here has met
Outcome = Literal[
    "lead",
    "chat",
    "call",
    "view",
    "click",
    "recall",
    "profile",
    "site_lead",
    "none",
]

# Which kind of result each optimisation goal produces.
#
# **Every goal the preset catalogue offers has to be named here**, and a
# test pins that: a goal this product sells and then cannot describe is a
# campaign whose owner is shown a nought with no sentence beside it.
#
# Goals nobody offers are named too where the answer is obvious. They
# arrive from campaigns built by hand in Ads Manager, which a cabinet
# inherits the moment it connects to a working ad account.
OUTCOMES: Final[dict[str, Outcome]] = {
    # A form on the ad itself. The two goals mean the same thing, and both
    # of them put a row in this product's lead table.
    "LEAD_GENERATION": "lead",
    "QUALITY_LEAD": "lead",
    # A conversation the provider hosts. Real, counted, and not a lead: it
    # has no name, no telephone number and no verdict, and the product's
    # own cost divides by exactly those.
    "CONVERSATIONS": "chat",
    "QUALITY_CALL": "call",
    # Bought to be seen. ``REACH`` is here rather than as a kind of its
    # own because reach counts *people* and cannot be added across days or
    # across ad sets - the same person reached twice is one of them - so
    # the only additive answer to "how much was this seen" is impressions,
    # and it is the answer the other awareness goal already gives.
    "IMPRESSIONS": "view",
    "REACH": "view",
    "AD_RECALL_LIFT": "recall",
    # Somebody left for the advertiser's own site. What happens after that
    # is the advertiser's own business and this product has no tag for it,
    # but the departure itself is counted and is the result the campaign
    # was bought for.
    #
    # Both goals answer the same way and one of them is a compromise worth
    # stating: Meta's landing page view needs a pixel on the advertiser's
    # site to fire, and most accounts here have none. The count that is
    # always there is the click that went where the money was spent to
    # send it, so that is what the screens read - and they call it
    # "havolaga o'tish" rather than "landing page view", which is what it
    # actually is.
    "LANDING_PAGE_VIEWS": "click",
    "LINK_CLICKS": "click",
    # A purchase on somebody else's website, counted by a pixel this
    # product has no table for. An offered goal whose answer is nothing,
    # and it gets a sentence instead of a figure - see
    # ``apps.metrics.selectors.dashboard.UNCOUNTED_NOTES``.
    "OFFSITE_CONVERSIONS": "none",
    # A visit to the business's Instagram profile. Meta files it under no
    # action type - only its ``results`` field carries the count.
    "PROFILE_VISIT": "profile",
}


def outcome_of(optimization_goal: str) -> Outcome:
    """What one result is for an ad set optimising for this.

    ``"none"`` for anything not named, which is a real case rather than a
    guard: an ad set the mirror has not synced yet has no goal recorded,
    and an unknown ad set is not one to invent a figure for.
    """
    return OUTCOMES.get(optimization_goal.strip().upper(), "none")


# The one goal whose answer depends on more than the goal: a pixel event on
# the advertiser's own site. Which event is on the ad set's promoted object,
# and only a lead is counted - it is the one event the provider's count of
# leads carries (see ``metaads.insights.LEAD_ACTIONS``). A purchase, a
# contact or a registration on the same goal stays uncounted.
SITE_GOAL: Final = "OFFSITE_CONVERSIONS"
SITE_LEAD_EVENT: Final = "LEAD"


def outcome_for(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> Outcome:
    """What one result is for an ad set: its goal, and what it promotes.

    **The one place a kind is decided for a screen.** It is
    :func:`outcome_of` for every goal but the website one, where the goal
    alone says only "an event on your site" and the promoted object says
    which. A lead event there is ``site_lead`` and not ``lead``: nothing
    arrives here by webhook, so every rule about leads that never reached
    this product - the cost withheld over a gap, the stalled-form alarm -
    would fire against a table that is always empty for it.

    The agent's rules do not ask this - they read ``outcome_of`` and keep
    judging a website ad set as uncounted.
    """
    goal = optimization_goal.strip().upper()
    if goal == SITE_GOAL and _event_of(promoted_object) == SITE_LEAD_EVENT:
        return "site_lead"
    return outcome_of(goal)


def _event_of(promoted_object: Mapping[str, object] | None) -> str:
    if not isinstance(promoted_object, Mapping):
        return ""
    return str(promoted_object.get("custom_event_type") or "").strip().upper()


# How strongly one ad set's goal speaks for its campaign, strongest first.
# A form on the ad has rows of its own and wins; a lead on the owner's site
# is the next strongest evidence; anything else is taken in id order.
_RANK: Final[dict[Outcome, int]] = {"lead": 0, "site_lead": 1}


def campaign_goal(
    adsets: Iterable[tuple[str, str, Mapping[str, object] | None]],
) -> tuple[str, Mapping[str, object] | None]:
    """The one ad set that speaks for a campaign: its goal and promoted object.

    ``adsets`` are ``(external id, goal, promoted object)``. One ad set is
    what this product creates, so normally there is one answer. A campaign
    built by hand may hold several and they may disagree: a form wins, a
    website lead next, and otherwise the first by id - so every screen that
    names the campaign names it the same way.

    ``("", None)`` for a campaign whose ad sets the mirror has not read.
    """
    ranked = sorted(
        adsets,
        key=lambda row: (_RANK.get(outcome_for(row[1] or "", row[2]), 2), row[0]),
    )
    if not ranked:
        return "", None
    _, goal, promoted = ranked[0]
    return goal or "", promoted


def is_counted(optimization_goal: str) -> bool:
    """Whether there is any figure at all to put against this goal.

    The question a screen asks before it decides between a number and a
    sentence. False for the sales goal, whose result happens where this
    product has no tag, and false for every goal nobody wrote down.
    """
    return outcome_of(optimization_goal) != "none"


# Optimisation goals whose ad sets can put a row in this product's lead
# table. Derived rather than declared, which is the point of the table
# above: a second list is one that goes stale the day a goal is added to
# the other.
LEAD_GOALS: Final[frozenset[str]] = frozenset(
    goal for goal, kind in OUTCOMES.items() if kind == "lead"
)


def counts_leads(optimization_goal: str) -> bool:
    """Whether an ad set optimising for this can produce a lead row here.

    Not "did it". An ad set that collected nothing this week still counts
    leads; what this answers is whether nought is a **result** or a
    definition - and every rule that divides by a lead needs to know which,
    because the two look identical in the figures.

    Empty answers ``False``, and that is a real case rather than a guard:
    an ad set the mirror has not synced yet has no goal recorded, and an
    unknown ad set is not one to form opinions about.
    """
    return outcome_of(optimization_goal) == "lead"


__all__ = [
    "LEAD_GOALS",
    "OUTCOMES",
    "SITE_GOAL",
    "SITE_LEAD_EVENT",
    "Outcome",
    "campaign_goal",
    "counts_leads",
    "is_counted",
    "outcome_for",
    "outcome_of",
]
