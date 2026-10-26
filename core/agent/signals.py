"""The separate things a diagnosis notices about one group.

Each signal is one step of the funnel read against something: the group's
own figures against a fixed floor, or against the same step on the
account's comparable groups - see :mod:`core.agent.benchmark`. None of
them is a verdict. The verdict is :mod:`core.agent.diagnosis`, which picks
the earliest step that failed.

**Every threshold here is approximate, and says so.** The provider
publishes no "good" click-through rate, cost per thousand or hook rate -
its own reference compares an advert with the adverts it competed with and
stops there. So every comparison is with this account's own groups, and
every number below is a margin wide enough that an ordinary week does not
cross it, not a figure with a source.

The one exception has a source: :data:`MIN_IMPRESSIONS`, the provider's own
floor before it will rank an advert at all.
"""

from typing import Final, Literal, get_args

from core.agent.benchmark import (
    Benchmark,
    family_of,
    lead_count,
    per_of,
    result_count,
)
from core.agent.contracts import Policy
from core.agent.facts import AdFacts, AdSetFacts, troubled
from core.agent.frequency import seen_too_often
from core.agent.funnel import per_ten_thousand
from core.agent.rules.audience import MIN_HALF_DAYS, MIN_HALF_IMPRESSIONS
from core.agent.sufficiency import enough_to_decide

# **Declared in the brief's order, and the order is the verdict.** The
# first signal present decides the cause - see
# ``core.agent.diagnosis.CAUSE_OF`` - whatever the group's price: the brief
# reads a group top down and takes the first step that failed. Five steps:
# its state, whether there is enough to judge by, whether it is shown, the
# advert, and what happens after the click.
Signal = Literal[
    # 1. The state. The account owes the provider money - added by the
    # diagnosis, which holds the account - the provider stopped the group,
    # or the page does not open. Nothing after these can be read.
    "unpaid",
    "provider_issue",
    "site_down",
    # 2. Enough to judge by: the provider still learning, too few days or
    # showings, or under three results' usual price spent - see
    # ``core.agent.sufficiency``. The brief decides nothing on it.
    "learning",
    "few_days",
    "few_impressions",
    "thin_data",
    # 3. Shown at all: a group that cannot spend its budget, one dear to
    # show, and one a week into learning nowhere near the results it needs
    # to finish.
    "underspending",
    "high_cpm",
    "learning_stuck",
    # 4. The advert. Wear-out first, because it is the cause of the falling
    # rate the next ones would otherwise report.
    "worn_out",
    # Clicked far less now than while it was new: the advert is spent.
    "fatigued",
    "low_ranking",
    "low_ctr",
    "weak_hook",
    # The opening stopped people and the middle lost them.
    "weak_hold",
    # 5. After the click.
    "quality_below_engagement",
    "low_click_to_lead",
    "low_arrival",
    "conversion_ranking_low",
    # A tenth or more of the enquiries left a number nobody can call back.
    "junk_numbers",
    "long_form",
    # Last: the provider's own word that the group cannot learn, said only
    # when no step explains it better.
    "learning_limited",
]
SIGNALS: Final[tuple[Signal, ...]] = get_args(Signal)

# The provider's own floor: below it an advert is not ranked, and a rate
# over fewer impressions moves by a third on one click.
MIN_IMPRESSIONS: Final = 500
# How many impressions a rate needs before it is compared with anything.
MIN_RATE_IMPRESSIONS: Final = 1_000
# A rate under this share of the usual one - the pair's fortnight, else
# its other groups of the kind - is low. See ``Benchmark.link_ctr_bp``.
LOW_RATE_SHARE_PCT: Final = 70
# Where the pair has no other video to compare with, the starting values
# the product's own brief gives: under a fifth of the people shown it
# watching three seconds is a weak opening, under fifteen in a hundred of
# those staying to the end a weak middle. To be tuned per trade once there
# is data.
HOOK_FLOOR_BP: Final = 2_000
HOLD_FLOOR_BP: Final = 1_500
# The provider's own figure: about fifty results a week end learning. A
# group a week in with under this share of them will not get there by
# waiting - the brief's starting value, like the floors above.
LEARNING_RESULTS: Final = 50
STUCK_SHARE_PCT: Final = 30
# The last three days' click-through rate under this share of the first
# three's is a tired advert - the brief's starting value.
FATIGUE_SHARE_PCT: Final = 70
# Past this share of a group's enquiries with a number nobody can call
# back, the form lets too much through - over at least this many of them.
# The brief's starting values.
JUNK_SHARE_PCT: Final = 10
JUNK_MIN_LEADS: Final = 10
# A group that spent under this share of its budget is not being shown
# enough to judge its advert by - the brief's starting value.
UNDERSPEND_SHARE_PCT: Final = 70
# A thousand impressions at this share of the account's or more is dear.
HIGH_CPM_SHARE_PCT: Final = 150
# Link clicks before what happened after them is judged. On a form advert
# a click opens the form - the provider's own reading of it, not checked
# against a live account - so this is people who saw the questions.
MIN_CLICKS: Final = 100
# Leads per click under this share of the account's is a step that stalls.
LOW_CONVERSION_SHARE_PCT: Final = 50
# Under half of link clicks reaching a loaded page is a page in the way.
LOW_ARRIVAL_BP: Final = 5_000
# More questions than a name, a telephone and two more. Each extra
# question costs a share of the people who opened the form.
MAX_EASY_QUESTIONS: Final = 4

# The provider's words for an advert's standing, as ``AdFacts`` carries them.
BOTTOM: Final[frozenset[str]] = frozenset({"below_average_20", "below_average_10"})
BELOW: Final[frozenset[str]] = BOTTOM | {"below_average_35"}
FINE: Final[frozenset[str]] = frozenset({"average", "above_average"})


def signals(
    *, item: AdSetFacts, bench: Benchmark, policy: Policy
) -> tuple[Signal, ...]:
    """Everything noticed about one group, in funnel order."""
    found = {
        *_facts(item, bench, policy),
        *_delivery(item),
        *_attention(item, bench, policy),
        *_standing(item, policy),
        *_after_click(item, bench),
    }
    return tuple(signal for signal in SIGNALS if signal in found)


def leading_ads(item: AdSetFacts, policy: Policy) -> tuple[AdFacts, ...]:
    """The delivering adverts carrying a real share of the group's money.

    The share is ``Policy.dead_segment_share_pct``, the bar every other cut
    of a group's money uses: an advert at two percent of the spend says
    nothing about why the group is failing.
    """
    spend = item.totals.spend_minor
    if spend <= 0:
        return ()
    return tuple(
        ad
        for ad in item.ads
        if ad.is_active
        and ad.in_window
        and ad.figures.spend_minor * 100 >= spend * policy.dead_segment_share_pct
    )


def _facts(item: AdSetFacts, bench: Benchmark, policy: Policy) -> list[Signal]:
    found: list[Signal] = []
    if troubled(item):
        found.append("provider_issue")
    if item.landing.down_urls:
        found.append("site_down")
    if item.is_learning:
        found.append("learning_stuck" if _stuck(item, policy) else "learning")
    if item.days_with_spend < policy.min_days:
        found.append("few_days")
    if item.funnel.impressions < MIN_IMPRESSIONS:
        found.append("few_impressions")
    if _thin(item, bench):
        found.append("thin_data")
    if item.learning_limited:
        found.append("learning_limited")
    return found


def _thin(item: AdSetFacts, bench: Benchmark) -> bool:
    """Short of the brief's rule: three results' usual price spent, or -
    where nothing says what a result costs - the showings and clicks it
    asks for instead. See :func:`core.agent.sufficiency.enough_to_decide`.
    """
    return not enough_to_decide(
        spend_minor=item.totals.spend_minor,
        usual_cost_minor=bench.cost_minor,
        impressions=item.funnel.impressions,
        link_clicks=item.funnel.link_clicks,
        per=per_of(family_of(item)),
    )


def _stuck(item: AdSetFacts, policy: Policy) -> bool:
    """A full window of learning with too few results to ever finish it."""
    if item.days_with_spend < policy.window_days:
        return False
    count = result_count(item)
    return count is not None and count * 100 < LEARNING_RESULTS * STUCK_SHARE_PCT


def _delivery(item: AdSetFacts) -> list[Signal]:
    """Whether the group spends what it is allowed to.

    Not where the budget was moved inside the window - the share is read
    against today's budget - nor where the campaign above holds it.
    """
    if not item.daily_budget_minor or item.budget_moved:
        return []
    share = item.spend_share
    return ["underspending"] if 0 < share < UNDERSPEND_SHARE_PCT else []


def _attention(item: AdSetFacts, bench: Benchmark, policy: Policy) -> list[Signal]:
    own = item.funnel
    found: list[Signal] = []
    if _worn_out(item, policy):
        found.append("worn_out")
    if _fatigued(item, policy):
        found.append("fatigued")
    if own.impressions < MIN_RATE_IMPRESSIONS:
        return found
    if _below(own.link_ctr_bp, bench.link_ctr_bp, LOW_RATE_SHARE_PCT):
        found.append("low_ctr")
    if _weak(own.hook_bp, bench.hook_bp, HOOK_FLOOR_BP):
        found.append("weak_hook")
    if _weak(own.hold_bp, bench.hold_bp, HOLD_FLOOR_BP):
        found.append("weak_hold")
    if _at_least(own.cpm_minor, bench.cpm_minor, HIGH_CPM_SHARE_PCT):
        found.append("high_cpm")
    return found


def _fatigued(item: AdSetFacts, policy: Policy) -> bool:
    """The last three days clicked far less than the first three ever did.

    Only for a group with a full window behind it, so the two ends of the
    comparison are not the same days.
    """
    if item.days_with_spend < policy.window_days:
        return False
    if item.recent.totals.impressions < MIN_RATE_IMPRESSIONS:
        return False
    return _below(item.recent.link_ctr_bp, item.launch_ctr_bp, FATIGUE_SHARE_PCT)


def _weak(own: int | None, peers: int | None, floor: int) -> bool:
    """Under the comparable groups' rate, or under the floor without them."""
    if peers is not None:
        return _below(own, peers, LOW_RATE_SHARE_PCT)
    return own is not None and own < floor


def _worn_out(item: AdSetFacts, policy: Policy) -> bool:
    """The same people keep seeing it and have stopped clicking.

    Clicks falling from the window's first half to its second, while one
    person has seen it at least as often as the first frequency bar - the
    figure the morning's levels read, see :mod:`core.agent.frequency`. The
    signature ``core.agent.rules.audience.saturated`` reads, with the same
    floors - without its second condition, that the audience can still be
    widened. That decides whether there is a change to offer, not whether
    the audience is worn out.
    """
    early, late = item.early, item.late
    if min(early.days, late.days) < MIN_HALF_DAYS:
        return False
    if min(early.impressions, late.impressions) < MIN_HALF_IMPRESSIONS:
        return False
    before, after = early.link_ctr_bp, late.link_ctr_bp
    if before is None or after is None or before <= 0:
        return False
    if (before - after) * 100 < before * policy.ctr_drop_pct:
        return False
    return seen_too_often(item.week_frequency)


def _standing(item: AdSetFacts, policy: Policy) -> list[Signal]:
    """What the provider says about the adverts carrying the money.

    Three verdicts that fail apart, and the pairs are the provider's own
    reading of them. People ignore it: the advert. People engage and the
    quality is low: the advert promises something it is not. People engage
    and do not convert: whatever comes after the click.
    """
    found: list[Signal] = []
    for ad in leading_ads(item, policy):
        quality, engagement = ad.quality_ranking, ad.engagement_ranking
        if engagement in BOTTOM or (quality in BOTTOM and engagement not in FINE):
            found.append("low_ranking")
        if quality in BELOW and engagement in FINE:
            found.append("quality_below_engagement")
        if ad.conversion_ranking in BOTTOM and engagement in FINE:
            found.append("conversion_ranking_low")
    return found


def _after_click(item: AdSetFacts, bench: Benchmark) -> list[Signal]:
    own = item.funnel
    found: list[Signal] = []
    if item.counts_leads and _form_stalls(item, bench):
        found.append("low_click_to_lead")
    # Only where a page carries the pixel. Without one nobody's arrival is
    # counted, and nought arrivals is the site's silence, not its visitors'.
    if (
        item.landing.pixel_seen
        and own.link_clicks >= MIN_CLICKS
        and _below(own.arrival_bp, LOW_ARRIVAL_BP, 100)
    ):
        found.append("low_arrival")
    if item.counts_leads and _junk(item):
        found.append("junk_numbers")
    if item.landing.form_questions > MAX_EASY_QUESTIONS:
        found.append("long_form")
    return found


def _junk(item: AdSetFacts) -> bool:
    leads = lead_count(item)
    return leads >= JUNK_MIN_LEADS and item.junk_leads * 100 > leads * JUNK_SHARE_PCT


def _form_stalls(item: AdSetFacts, bench: Benchmark) -> bool:
    """Enough people clicked, and too few of them became a lead.

    No lead at all from a hundred clicks stalls on its own. Otherwise the
    rate is compared with the account's, which has to have one.
    """
    clicks = item.funnel.link_clicks
    if clicks < MIN_CLICKS:
        return False
    leads = lead_count(item)
    if leads == 0:
        return True
    own = per_ten_thousand(part=leads, whole=clicks)
    return _below(own, bench.click_to_lead_bp, LOW_CONVERSION_SHARE_PCT)


def _below(value: int | None, base: int | None, share_pct: int) -> bool:
    """``value`` is under ``share_pct`` percent of ``base``."""
    if value is None or base is None or base <= 0:
        return False
    return value * 100 < base * share_pct


def _at_least(value: int | None, base: int | None, share_pct: int) -> bool:
    """``value`` is at ``share_pct`` percent of ``base`` or over."""
    if value is None or base is None or base <= 0:
        return False
    return value * 100 >= base * share_pct


__all__ = [
    "BELOW",
    "BOTTOM",
    "FINE",
    "HIGH_CPM_SHARE_PCT",
    "LOW_ARRIVAL_BP",
    "LOW_CONVERSION_SHARE_PCT",
    "LOW_RATE_SHARE_PCT",
    "MAX_EASY_QUESTIONS",
    "MIN_CLICKS",
    "MIN_IMPRESSIONS",
    "MIN_RATE_IMPRESSIONS",
    "SIGNALS",
    "Signal",
    "leading_ads",
    "signals",
]
