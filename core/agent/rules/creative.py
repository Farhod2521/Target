"""The first rule that looks *inside* a group."""

from typing import Final

from adskit import ExternalRef, Level

from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable
from core.metrics import SegmentCost, compare_segments

WEAK_AD = "weak_ad"

MIN_LIVE_ADS = 2


_LEVEL: Final[Level] = "ad"


def weak_ad(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """One advert in the group spends and returns nothing - switch it off."""
    found: list[Finding] = []
    for item in account.adsets:
        if not judgeable(item, policy):
            continue
        weakest = _weakest(item=item, policy=policy)
        if weakest is None:
            continue
        found.append(_finding(account=account, item=item, cost=weakest))

    return found


def _weakest(*, item: AdSetFacts, policy: Policy) -> SegmentCost | None:
    """The advert worth stopping in this group, or nothing."""
    live = [ad for ad in item.ads if ad.is_active and ad.in_window]
    if len(live) < MIN_LIVE_ADS:
        return None

    cut = compare_segments([ad.figures for ad in live])
    if not cut.barren:
        return None

    worst = cut.barren[0]
    if worst.spend_share < policy.dead_segment_share_pct:
        return None
    return worst


def _finding(*, account: AccountFacts, item: AdSetFacts, cost: SegmentCost) -> Finding:
    """The proposal, with the arithmetic that produced it."""
    return Finding(
        kind="pause",
        rule=WEAK_AD,
        ref=ExternalRef(provider=account.provider, level=_LEVEL, id=cost.segment),
        parent_id=item.external_id,
        weight=int(cost.spend_minor),
        evidence={
            "days": item.days_with_spend,
            "spend_minor": int(cost.spend_minor),
            "impressions": cost.impressions,
            "ad_leads_reported": cost.leads_reported,
            "ad_spend_share_pct": cost.spend_share,
            "adset_spend_minor": item.totals.spend_minor,
            "adset_leads_reported": item.totals.leads_reported,
            "live_ads": sum(1 for ad in item.ads if ad.is_active and ad.in_window),
            "currency": account.currency,
        },
    )


__all__ = ["MIN_LIVE_ADS", "WEAK_AD", "weak_ad"]
