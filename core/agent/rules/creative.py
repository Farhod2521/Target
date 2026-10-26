"""The first rule that looks *inside* a group.

Every other rule here judges an ad set against the account: is it expensive,
is it starved, is its audience worn out. This one judges a group's adverts
against **each other**, which is a different question and the only one that
has an answer when the group as a whole is doing fine. A group at exactly
the account's cost per lead can be two adverts working and one taking a
third of the money for nothing, and that is invisible from every figure the
level above it holds.

**No new arithmetic.** The comparison is :func:`core.metrics.
compare_segments`, exactly as it is written for age cells and for
placements, because the question has the same shape: one pot of spend cut
into slices, each slice with its own results, and a floor under what may be
called a failure. ``barren`` is the list an exclusion is decided from -
slices that had the budget to produce leads at the rate the rest of the cut
manages and produced none - and here an exclusion is a switch.

**Two of the three candidates for this level were refused, and the second
refusal is the stronger one.** Meta's quality and engagement rankings are a
real signal, and the honest response to a low one is a new advert, which
this product cannot write. The only available response is a stop - and
stopping on a *relative* ranking would override the cost comparison above,
sometimes against the cheapest advert in the group. A rule whose action
contradicts a better rule is worse than no rule. A video's hook rate fails
the same test from the other side: it is a stand-in for a result now
measured directly on the same slice, and the only figure a stop moves is
the one this rule already grades.
"""

from typing import Final

from adskit import ExternalRef, Level

from core.agent.contracts import Finding, Policy
from core.agent.facts import AccountFacts, AdSetFacts, judgeable
from core.metrics import SegmentCost, compare_segments

WEAK_AD = "weak_ad"

# How many adverts must be delivering before one of them may be called the
# weak one.
#
# Two is arithmetic rather than taste, and it is two separate arguments
# landing on the same number. A cut of one slice has nothing to compare
# against - its own cost *is* the average, so no slice can be worse than
# it. And switching off one of one stops the group, which is the change
# nobody agreed to. Below this the rule finds nothing, which is also what
# keeps the guardrail's last-advert refusal from ever being reached by the
# agent's own path.
MIN_LIVE_ADS = 2

# How much of the group's money the weak advert must be taking is not
# written here. It is ``Policy.dead_segment_share_pct``, reused rather than
# copied: a slice at two percent of the spend is a rounding error and one at
# forty is the whole problem, and that question does not change because the
# slice happens to be an advert rather than an age cell.

# The only level in this package a finding has ever pointed below an ad
# set. Typed rather than left a bare string so that a misspelling is a
# type error here instead of a reference the provider cannot resolve.
_LEVEL: Final[Level] = "ad"


def weak_ad(*, account: AccountFacts, policy: Policy) -> list[Finding]:
    """One advert in the group spends and returns nothing - switch it off.

    Not ``wasting`` or ``junk``, which stop the whole group when *it* is
    the thing failing. Here the group is not on trial: its money is simply
    reaching people through an advert that never brings anybody back, and
    the rest of its budget goes to the adverts that do. That is why this is
    the one proposal in the product that leaves the spending exactly where
    it was.

    The provider's own lead count on both sides, because it is the only one
    a slice can have: a lead of ours carries the advert it came from but the
    comparison is made where ``compare_segments`` makes every other one -
    see the note in ``core.metrics.segment_compare``. A goal the provider
    counts no leads for produces no earning rate, every slice falls to
    ``thin``, and the rule finds nothing without being told to.
    """
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
    """The advert worth stopping in this group, or nothing.

    Only the delivering ones are compared. An advert somebody already
    switched off spends nothing and is not part of the mix - leaving it in
    would put a slice with no money in the cut and drag the earning rate
    every other slice is measured against.
    """
    live = [ad for ad in item.ads if ad.is_active and ad.in_window]
    if len(live) < MIN_LIVE_ADS:
        return None

    cut = compare_segments([ad.figures for ad in live])
    if not cut.barren:
        return None

    # Biggest spender first - that is how ``barren`` is sorted, and the
    # advert taking the most money for nothing is the one to ask about.
    #
    # Nothing here re-checks that a sibling is left running. ``MIN_LIVE_ADS``
    # already guarantees it, and a second copy of the same condition is a
    # line that reads as defence while defending nothing - the real second
    # opinion is ``core.agent.check_ad_pause``, which is asked again against
    # a fresh read at the moment of the write.
    worst = cut.barren[0]
    if worst.spend_share < policy.dead_segment_share_pct:
        return None
    return worst


def _finding(*, account: AccountFacts, item: AdSetFacts, cost: SegmentCost) -> Finding:
    """The proposal, with the arithmetic that produced it.

    ``weight`` is what the weak advert spent rather than what the group
    did. The ranking is about how much money one change is about, and this
    change is about that advert's share - claiming the group's whole spend
    would put it above proposals that stop far more of it.
    """
    return Finding(
        kind="pause",
        rule=WEAK_AD,
        ref=ExternalRef(provider=account.provider, level=_LEVEL, id=cost.segment),
        # The group this advert sits in. What makes "stop the group" and
        # "stop one advert in the group" impossible to propose on the same
        # night - see :class:`core.agent.Finding`.
        parent_id=item.external_id,
        weight=int(cost.spend_minor),
        evidence={
            "days": item.days_with_spend,
            "spend_minor": int(cost.spend_minor),
            "impressions": cost.impressions,
            # Nought, always, or this rule would not have fired - shown
            # anyway, because it is the line the whole proposal rests on.
            #
            # Its own key rather than the ``leads_reported`` every other
            # rule writes, and the reason is the screen: that key is hidden
            # everywhere else, because everywhere else the provider's count
            # is working arithmetic rather than the point. Here it *is* the
            # point, and one key cannot be both.
            "ad_leads_reported": cost.leads_reported,
            "ad_spend_share_pct": cost.spend_share,
            # What the group did, so the card can say what the money it is
            # taking was taken *from*.
            "adset_spend_minor": item.totals.spend_minor,
            "adset_leads_reported": item.totals.leads_reported,
            "live_ads": sum(1 for ad in item.ads if ad.is_active and ad.in_window),
            "currency": account.currency,
        },
    )


__all__ = ["MIN_LIVE_ADS", "WEAK_AD", "weak_ad"]
