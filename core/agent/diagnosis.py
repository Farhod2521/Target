"""Why a group spends without results, named from its own figures.

One cause per group, chosen by arithmetic somebody can read - the same
discipline as the rules. A language model explains the cause later; it
does not choose it, so the card, the chat and the notification cannot
disagree about what is wrong.

**The earliest step that failed is the cause.** Money is shown, then
clicked, then lands somewhere, then becomes a lead - and a problem at one
step makes every later step unreadable. See the declaration order of
:data:`core.agent.signals.Signal`.

**Opinions need poor results; facts do not.** A provider that stopped the
group, a page that does not open and a group too new to judge are stated
whatever the results say. Everything else is only a cause on a group whose
results cost too much - a lead, a conversation, a call, a visit, whatever
it was bought for - and a group doing well is ``no_problem`` with its
signals still recorded. A group whose results are poor and whose figures
point nowhere is ``unclear``, which is a finding of its own - the honest
answer, rather than the likeliest-sounding one.

**A group is judged by its own result and nothing else.** A low
click-through rate on a conversation group bringing conversations at the
usual price is not a problem; it is how that group looks. A group whose
result nothing here counts is never given an opinion - see
:func:`core.agent.benchmark.results_are_poor`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal, get_args

from core.agent.benchmark import (
    Benchmark,
    family_of,
    lead_count,
    peers,
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

Cause = Literal[
    "provider_stopped",
    "landing_blocks",
    "too_early",
    "worn_out",
    "weak_creative",
    "costly_audience",
    "promise_mismatch",
    # The provider gave up on learning: too few results a week to find the
    # people who bring them. Named only when nothing in the funnel is.
    "learning_limited",
    # Not causes of anything, and both written down: a group checked and
    # found well, and a group whose results are poor for a reason its
    # figures do not show.
    "no_problem",
    "unclear",
]
CAUSES: Final[tuple[Cause, ...]] = get_args(Cause)

# Which cause each signal points at. Iterated in the order signals are
# declared, which is the funnel's.
CAUSE_OF: Final[Mapping[Signal, Cause]] = {
    "provider_issue": "provider_stopped",
    "site_down": "landing_blocks",
    "learning": "too_early",
    "few_days": "too_early",
    "few_impressions": "too_early",
    "worn_out": "worn_out",
    "low_ranking": "weak_creative",
    "low_ctr": "weak_creative",
    "weak_hook": "weak_creative",
    "high_cpm": "costly_audience",
    "quality_below_engagement": "promise_mismatch",
    "low_click_to_lead": "landing_blocks",
    "low_arrival": "landing_blocks",
    "conversion_ranking_low": "landing_blocks",
    "long_form": "landing_blocks",
    "learning_limited": "learning_limited",
}

# A slice of a group whose thousand impressions cost this share of the
# group's own or more, while taking a real share of its money, is named in
# the evidence. Approximate, like every threshold in ``signals``.
COSTLY_SLICE_CPM_PCT: Final = 130

_ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """One group's cause, the signals behind it, and the numbers they read.

    ``evidence`` is numbers and provider ids only - no sentence is built in
    this package - and it is what makes a cause re-checkable months later.
    """

    adset_id: str
    name: str
    cause: Cause
    signals: tuple[Signal, ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)


def diagnose(*, account: AccountFacts, policy: Policy) -> tuple[Diagnosis, ...]:
    """A diagnosis for every group delivering, or stopped by the provider.

    A group the owner paused is not here. It spends nothing, and a cause for
    it would be an opinion about a decision somebody already made.
    """
    return tuple(
        _diagnosis(
            account=account,
            item=item,
            bench=peers(account.adsets, item),
            policy=policy,
        )
        for item in account.adsets
        if item.delivery == _ACTIVE or troubled(item)
    )


def _diagnosis(
    *, account: AccountFacts, item: AdSetFacts, bench: Benchmark, policy: Policy
) -> Diagnosis:
    found = signals(item=item, bench=bench, policy=policy)
    return Diagnosis(
        adset_id=item.external_id,
        name=item.name,
        cause=_cause(item=item, found=found, bench=bench, policy=policy),
        signals=found,
        evidence={
            **_figures(item=item, bench=bench),
            **_context(item=item, policy=policy),
            "currency": account.currency,
        },
    )


def _cause(
    *, item: AdSetFacts, found: tuple[Signal, ...], bench: Benchmark, policy: Policy
) -> Cause:
    pointed = CAUSE_OF[found[0]] if found else None
    if found and found[0] in FACTS:
        return CAUSE_OF[found[0]]
    if not results_are_poor(item=item, bench=bench, policy=policy):
        return "no_problem"
    return pointed or "unclear"


def _figures(*, item: AdSetFacts, bench: Benchmark) -> dict[str, Any]:
    """Each step's figure beside the account's, for the card to quote.

    ``outcome``, ``results`` and the two costs are the verdict's own
    figures - what one result cost here and what it usually costs on this
    account's groups bought for the same thing. Everything else explains
    them.
    """
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
        "click_to_lead_bp": per_ten_thousand(part=leads, whole=own.link_clicks),
        "account_click_to_lead_bp": bench.click_to_lead_bp,
        "cpl_minor": round(own.spend_minor / leads) if leads else None,
        "account_cpl_minor": bench.cpl_minor,
        "early_ctr_bp": item.early.link_ctr_bp,
        "late_ctr_bp": item.late.link_ctr_bp,
        "early_frequency": item.early.frequency,
        "late_frequency": item.late.frequency,
    }


def _context(*, item: AdSetFacts, policy: Policy) -> dict[str, Any]:
    """What the steps land on and what the provider said, by id."""
    return {
        "rankings": [
            {
                "ad": ad.external_id,
                # The advert's own name, so the cause can say which one.
                # A group runs several and "this advert" leaves the owner
                # guessing which of four to replace.
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
    """The biggest spender among the slices dear to show this group to.

    Across every cut the sync keeps - placement, region, age and gender. A
    slice counts when its thousand impressions cost well over the group's
    own and it takes a real share of the money. Said, never removed: a
    placement is the provider's to choose, and a region or an age the
    owner's.
    """
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
