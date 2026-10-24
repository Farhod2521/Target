"""Rules about who is being shown the ad, and how often."""

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

MIN_HALF_DAYS = 2

MIN_HALF_IMPRESSIONS = 1_000

FREQUENCY_RISE_PCT = 10

MIN_WORN_FREQUENCY = 130


def saturated(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """The same people keep seeing it, and have stopped clicking - widen it."""
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
            continue

        found.append(
            Finding(
                kind="swap_targeting",
                rule=SATURATED,
                ref=_ref(account, item),
                weight=item.totals.spend_minor,
                evidence={
                    **_result_figures(item=item, bench_cost=bench.cost_minor),
                    "days": item.days_with_spend,
                    "spend_minor": item.totals.spend_minor,
                    "impressions": item.totals.impressions,
                    "early_ctr_bp": before,
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
    """A slice of the audience only ever spent money - stop paying for it."""
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
