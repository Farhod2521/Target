"""The rule that looks inside a group, and the invariant that guards it.

No database and no clock. What ``weak_ad`` needs to see is a group's own
adverts as slices of its money, so every fixture here is that cut written
out - which is what lets "not quite enough evidence" be a test rather than
something noticed on somebody's account a fortnight later.

The numbers below are chosen so the arithmetic is readable. Two adverts,
one earning at 5 000 a lead and one that has spent more than ten leads
would have cost at that rate and returned nothing: that is exactly
``core.metrics.compare_segments``' definition of barren, and it is the only
list this rule reads.
"""

from dataclasses import replace
from typing import Any

from adskit import ProviderName

from core.agent import AccountFacts, AdFacts, AdSetFacts, Policy, scan
from core.agent.rules import WASTING, WEAK_AD, weak_ad
from core.agent.rules.creative import MIN_LIVE_ADS
from core.metrics import SegmentFigures, Totals

META = ProviderName("meta")
POLICY = Policy()

# What a lead costs in the advert that produces them, times the ten a slice
# must have been able to afford before its silence means anything.
EARNING = SegmentFigures(
    segment="ad-good", spend_minor=100_000, impressions=40_000, leads_reported=20
)
BARREN = SegmentFigures(
    segment="ad-bad", spend_minor=60_000, impressions=30_000, leads_reported=0
)


def _ad(figures: SegmentFigures, **overrides: Any) -> AdFacts:
    return AdFacts(
        name=overrides.pop("name", figures.segment),
        delivery=overrides.pop("delivery", "active"),
        figures=figures,
        days_with_spend=overrides.pop("days_with_spend", 7),
    )


def _adset(*ads: AdFacts, **overrides: Any) -> AdSetFacts:
    return AdSetFacts(
        external_id="adset-1",
        campaign_external_id="camp-1",
        name="Yosh onalar",
        delivery=overrides.pop("delivery", "active"),
        # Qualified leads on purpose: a group with twenty leads and none
        # of them wanted is ``junk``'s subject, and this file is about the
        # advert inside a group that is doing nothing wrong.
        totals=Totals(
            spend_minor=160_000,
            impressions=70_000,
            leads=20,
            qualified=8,
            leads_reported=20,
        ),
        days_with_spend=overrides.pop("days_with_spend", 7),
        daily_budget_minor=25_000,
        counts_leads=True,
        ads=ads,
        # Built here: nothing is proposed about a campaign made in Ads
        # Manager - see ``core.agent.rules.scan``.
        is_ours=overrides.pop("is_ours", True),
        **overrides,
    )


def _account(*adsets: AdSetFacts) -> AccountFacts:
    totals = Totals(spend_minor=1_000_000, leads=100, leads_reported=100, qualified=40)
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=totals,
        lead_totals=totals,
        adsets=adsets,
    )


# --- when it fires --------------------------------------------------------
def test_an_advert_that_took_the_money_and_returned_nothing_is_stopped() -> None:
    found = weak_ad(account=_account(_adset(_ad(EARNING), _ad(BARREN))), policy=POLICY)

    assert [item.rule for item in found] == [WEAK_AD]
    assert found[0].kind == "pause"
    assert found[0].ref.level == "ad"
    assert found[0].ref.id == "ad-bad"


def test_the_proposal_names_the_group_it_sits_in() -> None:
    """Without it nothing could withdraw this when the whole group is being
    stopped, and the screen would have no way to say which campaign it is
    about."""
    found = weak_ad(account=_account(_adset(_ad(EARNING), _ad(BARREN))), policy=POLICY)

    assert found[0].parent_id == "adset-1"


def test_it_is_weighed_by_what_the_advert_spent_not_the_group() -> None:
    """The ranking is about how much money one change is about. Claiming the
    group's whole spend would put this above proposals that stop all of it."""
    found = weak_ad(account=_account(_adset(_ad(EARNING), _ad(BARREN))), policy=POLICY)

    assert found[0].weight == BARREN.spend_minor


def test_the_card_shows_the_group_beside_the_advert() -> None:
    """ "This one took a third of the money" is only readable next to what
    the money was."""
    found = weak_ad(account=_account(_adset(_ad(EARNING), _ad(BARREN))), policy=POLICY)
    evidence = found[0].evidence

    assert evidence["ad_leads_reported"] == 0
    assert evidence["adset_spend_minor"] == 160_000
    assert evidence["adset_leads_reported"] == 20
    assert evidence["live_ads"] == 2
    assert evidence["ad_spend_share_pct"] >= POLICY.dead_segment_share_pct


# --- when it does not -----------------------------------------------------
def test_one_advert_alone_is_never_the_weak_one() -> None:
    """A cut of one slice has nothing to be worse than - its own cost *is*
    the average - and switching it off would stop the group rather than
    move its money."""
    assert weak_ad(account=_account(_adset(_ad(BARREN))), policy=POLICY) == []
    assert MIN_LIVE_ADS == 2


def test_an_advert_somebody_already_stopped_is_not_in_the_mix() -> None:
    """It spends nothing now. Leaving it in the cut would drag the earning
    rate every live slice is measured against - and here it also leaves one
    live advert, which is not a comparison at all."""
    paused = _ad(EARNING, delivery="paused")

    assert weak_ad(account=_account(_adset(paused, _ad(BARREN))), policy=POLICY) == []


def test_a_small_slice_is_not_worth_restarting_anything_for() -> None:
    """Below the share threshold the money at stake is a rounding error, and
    the same figure ``narrow_audience`` uses decides it."""
    tiny = SegmentFigures(
        segment="ad-bad", spend_minor=51_000, impressions=9_000, leads_reported=0
    )
    rich = SegmentFigures(
        segment="ad-good", spend_minor=900_000, impressions=90_000, leads_reported=180
    )

    assert weak_ad(account=_account(_adset(_ad(rich), _ad(tiny))), policy=POLICY) == []


def test_a_goal_the_provider_counts_no_leads_for_says_nothing() -> None:
    """No lead anywhere means no earning rate, every slice falls to ``thin``,
    and the rule switches itself off - the same guard ``narrow_audience``
    has, and the reason neither needed a ``needs_leads`` flag."""
    quiet = _adset(
        _ad(SegmentFigures(segment="ad-a", spend_minor=100_000, leads_reported=0)),
        _ad(SegmentFigures(segment="ad-b", spend_minor=60_000, leads_reported=0)),
    )

    assert weak_ad(account=_account(quiet), policy=POLICY) == []


def test_a_group_too_young_to_judge_is_not_opened_up() -> None:
    """The same evidence bar every other rule has. An advert's figures are
    no older than the group's."""
    young = _adset(_ad(EARNING), _ad(BARREN), days_with_spend=1)

    assert weak_ad(account=_account(young), policy=POLICY) == []


# --- the invariant: a part is withdrawn when the whole is changing --------
def test_stopping_the_group_withdraws_the_proposal_about_its_advert() -> None:
    """Both are sound on their own and incoherent on one screen. The reader
    is being asked whether to stop the whole thing; answering that first is
    the only order in which both answers make sense."""
    burning = replace(
        _adset(_ad(EARNING), _ad(BARREN)),
        totals=Totals(spend_minor=900_000, leads=0, leads_reported=0, qualified=0),
    )

    codes = [item.rule for item in scan(account=_account(burning), policy=POLICY)]

    assert WASTING in codes
    assert WEAK_AD not in codes


def test_with_the_group_left_alone_the_advert_is_still_proposed() -> None:
    """The other half of the assertion above: the withdrawal is about the
    parent being proposed, not about ad-level findings being second class."""
    codes = [
        item.rule
        for item in scan(
            account=_account(_adset(_ad(EARNING), _ad(BARREN))), policy=POLICY
        )
    ]

    assert codes == [WEAK_AD]
