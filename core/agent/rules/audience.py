"""Rules about who is being shown the ad, and how often.

Both propose the same write - the ad set's audience is replaced - and they
pull in opposite directions, which is why they sit together. One says the
pool is too small for the money going through it; the other says part of
the pool has never once responded. An ad set can genuinely be both, and
``scan`` keeps whichever is worth more.

**Neither declares ``needs_leads``, and neither needs to.** The first
divides impressions by nothing at all; the second divides by the
*provider's* lead count, which exists for every goal and is nought
everywhere on a goal the provider counts no leads for - and a comparison
where nothing converted has no rate to judge against, so it produces no
dead slice and no proposal. The absence is unambiguous, which is exactly
what ``needs_leads`` was invented to handle when it is not.
"""

from adskit import ExternalRef

from core.agent.benchmark import (
    benchmarks,
    family_of,
    result_cost,
    result_count,
    results_are_poor,
)
from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable
from core.agent.narrow import narrow
from core.agent.widen import widen

SATURATED = "saturated"
NARROW_AUDIENCE = "narrow_audience"

# How many days each half of the window must have figures for. Two: with
# one, "the direction it is going" is one day against one day, and a quiet
# Sunday would read as a collapse.
MIN_HALF_DAYS = 2

# How many impressions each half needs before its click-through rate is
# worth comparing. A rate over a few hundred impressions moves by a third
# on the strength of one or two clicks, which is the whole trap this
# guards - the drop is measured as a percentage of a small number.
MIN_HALF_IMPRESSIONS = 1_000

# How much the daily frequency must climb, as a percentage of the earlier
# half's, before a falling click-through rate is read as *fatigue* rather
# than as an ordinary bad week. Approximate, like every threshold in this
# area: the provider publishes no figure for it.
FREQUENCY_RISE_PCT = 10

# How often one person must already see it a day, in hundredths, before a
# rise is fatigue at all. From 1,1 to 1,22 is a tenth more and still
# nobody's tired of anything; practitioners put fatigue near three a week
# for a cold audience, which is this a day.
MIN_WORN_FREQUENCY = 130


def saturated(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """The same people keep seeing it, and have stopped clicking - widen it.

    The classic wear-out signature, and it needs both halves of itself.
    A falling click-through rate on its own is a bad week, a seasonal dip,
    a competitor outbidding us; a rising frequency on its own is a small
    audience delivering normally. Together they say something specific:
    the pool is being shown the ad more and more often, and it has stopped
    responding.

    The remedy here is a wider audience - fresh people who have not seen
    it. The other is a new picture in front of the same people, which is
    a change to an **ad** and belongs to :mod:`core.agent.rules.refresh`.
    Widening genuinely addresses the cause rather than merely being what
    is available: frequency climbs because the pool is too small for the
    money going through it.

    One step outward per proposal, the same ladder ``starved`` climbs -
    see :mod:`core.agent.widen`.

    **Only where what the group was bought for has become dear.** Tired
    people clicking less is a reading of attention, not a result: a
    conversation group whose conversations still cost what they usually do
    is working, and throwing away its audience would be judging it by a
    figure it was never bought for. The price is read against the whole
    account's groups of the same kind, which is why the rule is shown the
    whole account and keeps to campaigns this product built by itself.
    """
    found: list[Finding] = []
    families = benchmarks(account.adsets)

    for item in account.adsets:
        if not item.is_ours or not judgeable(item, policy):
            continue
        bench = families[family_of(item)]
        if not results_are_poor(item=item, bench=bench, policy=policy):
            continue
        early, late = item.early, item.late
        if min(early.days, late.days) < MIN_HALF_DAYS:
            continue
        if min(early.impressions, late.impressions) < MIN_HALF_IMPRESSIONS:
            continue

        before, after = early.link_ctr_bp, late.link_ctr_bp
        if before is None or after is None or before <= 0:
            continue
        drop = round((before - after) * 100 / before)
        if drop < policy.ctr_drop_pct:
            continue
        if late.frequency <= early.frequency * (100 + FREQUENCY_RISE_PCT) / 100:
            continue
        if late.frequency < MIN_WORN_FREQUENCY:
            continue

        wider = widen(item.targeting)
        if wider is None:
            # Already showing to everyone this spec can reach. The
            # diagnosis stands and there is nothing to propose, which is
            # the honest end of it - see ``starved``.
            continue

        found.append(
            Finding(
                kind="swap_targeting",
                rule=SATURATED,
                ref=_ref(account, item),
                weight=item.totals.spend_minor,
                evidence={
                    # What the group was bought for and what it cost - the
                    # figure the promise is graded on.
                    **_result_figures(item=item, bench_cost=bench.cost_minor),
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    "impressions": item.totals.impressions,
                    "early_ctr_bp": before,
                    # What the assessment is graded against, and the
                    # reason it is stored rather than recomputed: this is
                    # the worn state the change was meant to undo.
                    "late_ctr_bp": after,
                    "ctr_drop_pct": drop,
                    "early_frequency": early.frequency,
                    "late_frequency": late.frequency,
                    "step": wider.step,
                    "currency": account.currency,
                    **wider.detail,
                },
                payload={"targeting": wider.targeting, "step": wider.step},
            )
        )

    return found


def _result_figures(*, item: AdSetFacts, bench_cost: int | None) -> dict[str, object]:
    """The group's result, its price, and the price usual for its kind here."""
    family = family_of(item)
    count = result_count(item)
    return {
        "outcome": family,
        "results": count,
        "cost_minor": result_cost(
            spend_minor=item.totals.spend_minor, count=count, family=family
        ),
        "account_cost_minor": bench_cost,
    }


def narrow_audience(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """A slice of the audience only ever spent money - stop paying for it.

    Reads the age-and-gender figures collected nightly. What makes it safe
    to act on is not the arithmetic - it is :mod:`core.agent.narrow`,
    which refuses every dead slice the provider cannot actually be told to
    skip.

    **The verdict rests on the provider's own lead count.** A lead of ours
    carries the ad it came from and never the age of the person who filled
    it in, so a cost per *qualified* lead per segment does not exist and
    never will. The evidence says so, the card must say so, and the
    assessment grades the same figure the decision was made on.

    The share threshold is what keeps this from being pedantry: replacing
    an audience throws away the delivery learned so far, and doing that to
    reclaim two percent of a budget is a worse trade than leaving the two
    percent where it is.
    """
    found: list[Finding] = []

    for item in account.adsets:
        if not judgeable(item, policy) or item.totals.spend_minor <= 0:
            continue
        cuts = item.segments
        if not cuts.barren:
            continue

        tighter = narrow(
            item.targeting,
            dead={row.segment: row.spend_minor for row in cuts.barren},
            alive=[row.segment for row in (*cuts.ranked, *cuts.weak)],
        )
        if tighter is None:
            continue

        # The share of *this ad set's* money going to the slice actually
        # being cut - not to every dead slice, which would justify a cut
        # by the weight of cells it does not remove.
        dropped = int(tighter.detail.get("dropped_spend_minor", 0))
        share = round(dropped * 100 / item.totals.spend_minor)
        if share < policy.dead_segment_share_pct:
            continue

        found.append(
            Finding(
                kind="narrow_targeting",
                rule=NARROW_AUDIENCE,
                ref=_ref(account, item),
                weight=dropped,
                evidence={
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    # The provider's count on both sides of the division,
                    # because that is the only count a segment has.
                    "leads_reported": item.totals.leads_reported,
                    "dead_share_pct": share,
                    "step": tighter.step,
                    "currency": account.currency,
                    **tighter.detail,
                },
                payload={"targeting": tighter.targeting, "step": tighter.step},
            )
        )

    return found


def _ref(account: AccountFacts, item: AdSetFacts) -> ExternalRef:
    return ExternalRef(provider=account.provider, level="adset", id=item.external_id)


__all__ = [
    "FREQUENCY_RISE_PCT",
    "MIN_HALF_DAYS",
    "MIN_HALF_IMPRESSIONS",
    "MIN_WORN_FREQUENCY",
    "NARROW_AUDIENCE",
    "SATURATED",
    "narrow_audience",
    "saturated",
]
