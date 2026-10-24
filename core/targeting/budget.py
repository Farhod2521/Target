"""What a provider will actually accept per day, given what it optimises for.

Meta reports one floor per ad account - ``min_daily_budget``, in the
account currency's minor units - and it is not the number that gets
enforced. That figure is the floor for an ad set billed on impressions.
An ad set optimising toward an event the platform expects to be *rare* -
a lead, a call, a conversation, a purchase - is refused at twice it.

The evidence is a production refusal rather than a document: an account
reporting ``min_daily_budget = 100`` (USD 1.00) was refused a
``QUALITY_CALL`` ad set at that budget with ``100/1885272``, "Budget Is
Too Low", naming USD 2.00 as the minimum. The floor was read correctly and
was the wrong number to read.

Kept here rather than beside the account it multiplies, because the
multiplier is a property of the *goal*, and the goal is chosen by a preset
in this package. A copy of this table in the Django layer would be a copy
that drifts the first time a preset adopts a goal nobody added to it.

No clock, no ORM, no settings: this is arithmetic over two values the
caller already has.
"""

from typing import Final

# Optimisation goals Meta treats as rare-event, doubling the account's
# reported floor. Everything absent from this set is billed and floored
# like an impression goal.
#
# Listed explicitly rather than derived. There is no field on the preset
# that says "this is a conversion goal", and inventing one to hold a
# provider's billing rule would put a Meta idea inside the domain - the
# goals themselves are already Meta's vocabulary, so a set of them is the
# smallest honest place for this.
RARE_EVENT_GOALS: Final[frozenset[str]] = frozenset(
    {
        "LEAD_GENERATION",
        "QUALITY_LEAD",
        "QUALITY_CALL",
        "CONVERSATIONS",
        "OFFSITE_CONVERSIONS",
        "VALUE",
        "APP_INSTALLS",
    }
)

# How much more those goals cost per day. An integer because money here is
# an integer count of minor units and a fractional multiplier would need a
# rounding rule nobody has a reason to choose.
RARE_EVENT_MULTIPLIER: Final = 2


# The goals bought to be seen rather than acted on, and the only ones a
# frequency cap means anything for. The provider refuses it elsewhere,
# naming the field, at the moment the ad set is created.
#
# Here beside the other two sets of provider words for the reason they are
# here: an optimisation goal is the provider's vocabulary, and a set of
# them is the smallest honest place for a rule about them.
SEEN_GOALS: Final[frozenset[str]] = frozenset(
    {"IMPRESSIONS", "REACH", "AD_RECALL_LIFT"}
)


# Goals Meta takes a frequency cap on. Narrower than ``SEEN_GOALS``: the
# provider writes ``frequency_control_specs`` only for reach (and ThruPlay,
# which nothing here buys) and refuses it on impressions and recall.
FREQUENCY_GOALS: Final[frozenset[str]] = frozenset({"REACH"})


# Goals a "most per result" figure can be attached to.
#
# Not every goal has a result somebody could put a price on. An ad bought
# to be seen produces impressions, and "do not pay more than 20 000 for one
# impression" is not a sentence anybody means; a visit to a website is
# counted on the advertiser's side and priced there too.
#
# What is left is a goal whose result the provider sells a cost per result
# goal for **and has been seen to accept it**. Its help page names "a
# purchase, lead, or other optimization event"
# (https://www.facebook.com/business/help/272336376749096) and lists no
# goal it refuses, so the set is what is known to work and nothing else.
# A call and a conversation are out: Meta refused both on creation -
# 100/1885204 "Optimization goal only supports autobid" for QUALITY_CALL,
# 100/2446166 "Optimization Goal Incompatible with Cost Cap" for
# CONVERSATIONS. Qualified leads are out until one is seen through.
#
# A subset of ``RARE_EVENT_GOALS`` above and deliberately not the same set.
# That one answers "does the provider charge more per day for this", which
# is a billing rule; this one answers "will the provider take a cost cap
# here", which is the provider's rule about bidding.
CAPPABLE_GOALS: Final[frozenset[str]] = frozenset(
    {"LEAD_GENERATION", "OFFSITE_CONVERSIONS"}
)


def accepts_cap(optimization_goal: str) -> bool:
    """Whether a price per result means anything for this goal.

    Empty answers ``False``, which is a real case rather than a guard: a
    launch whose goal has not been chosen yet renders the budget screen,
    and offering a cap there would be asking for a price on a result
    nobody has picked.
    """
    return optimization_goal.strip().upper() in CAPPABLE_GOALS


# How much daily budget a cost cap needs behind it to deliver at all.
#
# A cost cap tells the provider "do not pay more than this for one result".
# Given a daily budget only a little larger than the cap, there is nothing
# for the pacing to work with: the provider has room for one result and
# spends the day looking for one at or under the price, which is how a cap
# that reads as prudent produces an ad set that shows the ad to nobody.
#
# Three is the multiple, and it is deliberately modest. Meta's own guidance
# for the capped strategies is stated in terms of "several times" the cap
# and the platform enforces nothing; a larger number here would refuse
# budgets that work, and this rule exists to catch the answer that cannot
# work rather than to have an opinion about the ones that might.
#
# **The direction of the check is the safety of it.** Too low a cap is
# invisible in every figure this product shows - an ad set delivering to
# nobody reports no spend, no leads, and a cost per lead of nothing at all,
# which reads exactly like a campaign that has not started yet.
CAP_BUDGET_MULTIPLE: Final = 3


def min_daily_for_cap(*, cap_minor: int) -> int:
    """The smallest daily budget this cap can deliver on.

    Zero in, zero out, like the floor below: a campaign that named no cap
    has no requirement to meet.
    """
    return max(0, cap_minor) * CAP_BUDGET_MULTIPLE


def cap_fits(*, cap_minor: int, daily_budget_minor: int) -> bool:
    """Whether this pair can deliver, before anything is created.

    A cap of nothing always fits - it means the ad set is uncapped.
    Everything else has to leave the provider room to pace.
    """
    if cap_minor <= 0:
        return True
    return daily_budget_minor >= min_daily_for_cap(cap_minor=cap_minor)


def daily_floor(*, account_minor: int, optimization_goal: str) -> int:
    """The smallest daily budget this goal can be launched with.

    Zero in, zero out. An account that has not told us its floor switches
    the check off rather than inheriting an invented one - the same rule
    every other unknown provider value follows here, and the provider
    still refuses a genuinely low budget on its own.
    """
    if account_minor <= 0:
        return 0
    if optimization_goal.strip().upper() in RARE_EVENT_GOALS:
        return account_minor * RARE_EVENT_MULTIPLIER
    return account_minor


# How many times the goal's daily floor each advert should have behind it
# before one budget is spread across several.
#
# Not a rule the provider enforces, and not how it spends. A budget sits on
# the ad set and is never divided evenly: delivery moves to whichever advert
# starts well, and the rest barely show. What the multiple marks is where a
# group stops being a comparison - below it the second and later adverts get
# too little to say anything, and ``weak_ad`` finds nothing on a cut that
# thin. Twice the floor is the smallest share still clearly above the line
# the provider refuses at.
PER_AD_FLOOR_MULTIPLE: Final = 2


def per_ad_floor(*, floor_minor: int) -> int:
    """The least one advert should have behind it once a budget is shared.

    The sum the warning names, so it cannot drift from the count below.
    Zero in, zero out, like ``daily_floor``.
    """
    return max(0, floor_minor) * PER_AD_FLOOR_MULTIPLE


def ads_budget_carries(*, daily_budget_minor: int, floor_minor: int, ads: int) -> int:
    """How many adverts this daily budget gives a fair share to.

    Never below one: a single advert takes the whole budget and has nothing
    to be compared against. An unknown floor answers ``ads`` - nothing is
    flagged on a number nobody supplied, the rule ``daily_floor`` follows.
    """
    if floor_minor <= 0:
        return ads
    return max(1, daily_budget_minor // per_ad_floor(floor_minor=floor_minor))


# What a total ceiling has to satisfy to be worth sending. Meta enforces its
# own minimums per currency and refuses the rest as ordinary errors; a total
# below one day's budget is accepted and delivers badly, which is the
# failure worth catching here.
#
# There are no daily floor and ceiling beside it. Meta takes those only on
# an ad set whose budget sits on the campaign, and every ad set here holds
# its own budget - the pair is refused at creation (code 1885624).
#
# A reason code rather than a sentence, like every other rule in this
# package: the wording is Uzbek and belongs in the Django catalogue.
CAP_BELOW_DAILY: Final = "cap_below_daily"


def spend_limits_fit(*, daily_minor: int, total_cap_minor: int = 0) -> str:
    """Why this total cannot hold, or ``""`` when it can.

    A total below one day's budget stops the campaign the day it starts,
    which reads on every screen as a campaign that never began. Zero means
    "not set", which is what nearly every campaign carries.
    """
    if total_cap_minor and total_cap_minor < daily_minor:
        return CAP_BELOW_DAILY
    return ""


__all__ = [
    "CAPPABLE_GOALS",
    "CAP_BELOW_DAILY",
    "CAP_BUDGET_MULTIPLE",
    "FREQUENCY_GOALS",
    "PER_AD_FLOOR_MULTIPLE",
    "RARE_EVENT_GOALS",
    "RARE_EVENT_MULTIPLIER",
    "SEEN_GOALS",
    "accepts_cap",
    "ads_budget_carries",
    "cap_fits",
    "daily_floor",
    "min_daily_for_cap",
    "per_ad_floor",
    "spend_limits_fit",
]
