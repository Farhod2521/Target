"""Why a group spends without results, named from its own figures."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

from core.agent.benchmark import (
    Benchmark,
    count_in,
    family_of,
    lead_count,
    peers,
    per_of,
    result_cost,
    result_count,
    results_are_poor,
)
from core.agent.contracts import Policy
from core.agent.facts import AccountFacts, AdSetFacts, troubled
from core.agent.funnel import per_ten_thousand
from core.agent.signals import (
    FACTS,
    MIN_RATE_IMPRESSIONS,
    Signal,
    leading_ads,
    signals,
)
from core.agent.usual import TREND_ACT_PCT, cost_trend

Cause = Literal[
    "provider_stopped",
    "landing_blocks",
    "too_early",
    "worn_out",
    "weak_creative",
    "costly_audience",
    "not_delivering",
    "promise_mismatch",
    "learning_limited",
    "no_problem",
    "unclear",
]
CAUSES: Final[tuple[Cause, ...]] = get_args(Cause)

CAUSE_OF: Final[Mapping[Signal, Cause]] = {
    "provider_issue": "provider_stopped",
    "site_down": "landing_blocks",
    "learning_stuck": "learning_limited",
    "learning": "too_early",
    "few_days": "too_early",
    "few_impressions": "too_early",
    "underspending": "not_delivering",
    "worn_out": "worn_out",
    "fatigued": "worn_out",
    "low_ranking": "weak_creative",
    "low_ctr": "weak_creative",
    "weak_hook": "weak_creative",
    "weak_hold": "weak_creative",
    "high_cpm": "costly_audience",
    "quality_below_engagement": "promise_mismatch",
    "low_click_to_lead": "landing_blocks",
    "low_arrival": "landing_blocks",
    "conversion_ranking_low": "landing_blocks",
    "junk_numbers": "landing_blocks",
    "long_form": "landing_blocks",
    "learning_limited": "learning_limited",
}

COSTLY_SLICE_CPM_PCT: Final = 130

_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """One group's cause, the signals behind it, and the numbers they read."""

    adset_id: str
    name: str
    cause: Cause
    signals: tuple[Signal, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)


def diagnose(*, account: AccountFacts, policy: Policy) -> tuple[Diagnosis, ...]:
    """A diagnosis for every group delivering, or stopped by the provider."""
    return tuple(
        _diagnosis(
            account=account,
            item=item,
            bench=peers(account.adsets, item, account.usual),
            policy=policy,
        )
        for item in account.adsets
        if item.delivery == _ACTIVE or troubled(item)
    )


def _diagnosis(
    *, account: AccountFacts, item: AdSetFacts, bench: Benchmark, policy: Policy
) -> Diagnosis:
    found = signals(item=item, bench=bench, policy=policy)
    trend = _trend(item=item, account=account)
    rising = trend.get("cost_trend_pct") or 0
    return Diagnosis(
        adset_id=item.external_id,
        name=item.name,
        cause=_cause(
            item=item,
            found=found,
            bench=bench,
            policy=policy,
            rising=rising >= TREND_ACT_PCT or "junk_numbers" in found,
        ),
        signals=found,
        evidence={
            **_figures(item=item, bench=bench),
            **trend,
            **_context(item=item, policy=policy),
            "currency": account.currency,
        },
    )


def _cause(
    *,
    item: AdSetFacts,
    found: tuple[Signal, ...],
    bench: Benchmark,
    policy: Policy,
    rising: bool,
) -> Cause:
    """The first signal's cause, once the results say there is a problem."""
    pointed = CAUSE_OF[found[0]] if found else None
    if found and found[0] in FACTS:
        return CAUSE_OF[found[0]]
    if not rising and not results_are_poor(item=item, bench=bench, policy=policy):
        return "no_problem"
    return pointed or "unclear"


def _trend(*, item: AdSetFacts, account: AccountFacts) -> dict[str, Any]:
    """The last three days' price against the pair's usual, and the click
    rate's against the advert's first days."""
    family = family_of(item)
    usual = account.usual.get(family)
    recent = item.recent
    count = count_in(
        totals=recent.totals, link_clicks=recent.link_clicks, family=family
    )
    per = per_of(family)
    usual_cost = usual.cost_minor if usual is not None else None
    return {
        "usual_cost_minor": usual_cost,
        "recent_cost_minor": result_cost(
            spend_minor=recent.totals.spend_minor, count=count, family=family
        ),
        "cost_trend_pct": cost_trend(
            spend_minor=recent.totals.spend_minor,
            count=count,
            usual_cost_minor=usual_cost,
            per=per,
        ),
        "launch_ctr_bp": item.launch_ctr_bp,
        "recent_ctr_bp": recent.link_ctr_bp,
    }


def _figures(*, item: AdSetFacts, bench: Benchmark) -> dict[str, Any]:
    """Each step's figure beside the account's, for the card to quote."""
    own = item.funnel
    leads = lead_count(item)
    family = family_of(item)
    results = result_count(item)
    return {
        "outcome": family,
        "results": results,
        "cost_minor": result_cost(
            spend_minor=own.spend_minor, count=results, family=family
        ),
        "account_cost_minor": bench.cost_minor,
        "days": item.days_with_spend,
        "spend_minor": own.spend_minor,
        "impressions": own.impressions,
        "link_clicks": own.link_clicks,
        "landing_page_views": own.landing_page_views,
        "leads": leads,
        "cpm_minor": own.cpm_minor,
        "account_cpm_minor": bench.funnel.cpm_minor,
        "link_ctr_bp": own.link_ctr_bp,
        "account_link_ctr_bp": bench.funnel.link_ctr_bp,
        "hook_bp": own.hook_bp,
        "account_hook_bp": bench.hook_bp,
        "hold_bp": own.hold_bp,
        "account_hold_bp": bench.hold_bp,
        "click_to_lead_bp": per_ten_thousand(part=leads, whole=own.link_clicks),
        "account_click_to_lead_bp": bench.click_to_lead_bp,
        "cpl_minor": round(own.spend_minor / leads) if leads else None,
        "account_cpl_minor": bench.cpl_minor,
        "early_ctr_bp": item.early.link_ctr_bp,
        "late_ctr_bp": item.late.link_ctr_bp,
        "spend_share": item.spend_share if item.daily_budget_minor else None,
        "junk_leads": item.junk_leads,
        "early_frequency": item.early.frequency,
        "late_frequency": item.late.frequency,
    }


def _context(*, item: AdSetFacts, policy: Policy) -> dict[str, Any]:
    """What the steps land on and what the provider said, by id."""
    return {
        "rankings": [
            {
                "ad": ad.external_id,
                "name": ad.name,
                "quality": ad.quality_ranking,
                "engagement": ad.engagement_ranking,
                "conversion": ad.conversion_ranking,
            }
            for ad in leading_ads(item, policy)
        ],
        "down_urls": list(item.landing.down_urls),
        "pixel_seen": item.landing.pixel_seen,
        "form_questions": item.landing.form_questions,
        "issue_codes": list(item.issue_codes),
        "costly_slice": _costly_slice(item=item, policy=policy),
    }


def _costly_slice(*, item: AdSetFacts, policy: Policy) -> dict[str, Any] | None:
    """The biggest spender among the slices dear to show this group to."""
    base = item.funnel.cpm_minor
    if base is None:
        return None
    best: dict[str, Any] | None = None
    for kind, cells in item.slices.items():
        spent = sum(cell.spend_minor for cell in cells)
        for cell in cells:
            if spent <= 0 or cell.impressions < MIN_RATE_IMPRESSIONS:
                continue
            share = round(cell.spend_minor * 100 / spent)
            cpm = round(cell.spend_minor * 1_000 / cell.impressions)
            if share < policy.dead_segment_share_pct:
                continue
            if cpm * 100 < base * COSTLY_SLICE_CPM_PCT:
                continue
            if best is None or cell.spend_minor > best["spend_minor"]:
                best = {
                    "kind": kind,
                    "segment": cell.segment,
                    "spend_minor": int(cell.spend_minor),
                    "spend_share_pct": share,
                    "cpm_minor": cpm,
                }
    return best


__all__ = [
    "CAUSES",
    "CAUSE_OF",
    "COSTLY_SLICE_CPM_PCT",
    "Cause",
    "Diagnosis",
    "diagnose",
    "results_are_poor",
]
