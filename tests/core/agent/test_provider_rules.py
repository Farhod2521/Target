"""The two rules whose subject is the provider rather than the figures.

What is asked here is mostly about the *boundary*, because the boundary is
the whole risk. One of these rules exists to see ad sets every other rule
in the package refuses to look at, and it proposes taking part of somebody's
audience out of a live campaign - so the questions are which faults it fires
on, which it deliberately leaves alone, and what the card is told when the
only list an advertiser chose is the one coming out.

No database and no clock, like every rule test here: what the rule needs to
see arrives as a value, which is what lets "the mirror had never synced"
be a test rather than something met on a customer's account.
"""

from typing import Any

import pytest
from adskit import ProviderName

from core.agent import AccountFacts, AdSetFacts, Policy, broaden, find, repair, scan
from core.agent.rules import PROVIDER_ADVICE, PROVIDER_STOPPED
from core.metrics import Totals

META = ProviderName("meta")
POLICY = Policy()

# The audience the ad set is aimed at, in the shape the provider hands back.
AIMED: dict[str, Any] = {
    "age_min": 18,
    "age_max": 65,
    "custom_audiences": [{"id": "aud-gone"}, {"id": "aud-live"}],
    "targeting_automation": {"advantage_audience": 0},
}


def _adset(**overrides: Any) -> AdSetFacts:
    figures = {"spend_minor": 300_000, "impressions": 60_000, "leads": 4}
    figures.update(overrides.pop("totals", {}))
    return AdSetFacts(
        external_id=overrides.pop("external_id", "adset-1"),
        campaign_external_id="camp-1",
        name="Toshkent 25-45",
        delivery=overrides.pop("delivery", "rejected"),
        totals=Totals(**{"leads_reported": figures.get("leads", 0), **figures}),
        days_with_spend=overrides.pop("days_with_spend", 7),
        daily_budget_minor=overrides.pop("daily_budget_minor", 15_000),
        targeting=overrides.pop("targeting", AIMED),
        counts_leads=overrides.pop("counts_leads", True),
        # A campaign this product built, unless a test says otherwise. The
        # dataclass defaults the other way - the safe way - so a caller who
        # forgets loses a proposal rather than rewriting the audience of a
        # campaign somebody built in Ads Manager. See ``AdSetFacts.is_ours``.
        is_ours=overrides.pop("is_ours", True),
        **overrides,
    )


def _account(*adsets: AdSetFacts) -> AccountFacts:
    totals = Totals(spend_minor=1_000_000, leads=100, leads_reported=100, qualified=40)
    # The other groups at 10 000 a lead, the groups handed in on top: a
    # group is measured against the rest of the account.
    lead_totals = Totals(
        spend_minor=totals.spend_minor + sum(a.totals.spend_minor for a in adsets),
        leads=totals.leads + sum(a.totals.leads for a in adsets),
        leads_reported=totals.leads_reported
        + sum(a.totals.leads_reported for a in adsets),
        qualified=totals.qualified,
    )
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=totals,
        lead_totals=lead_totals,
        adsets=adsets,
    )


def _broken(**overrides: Any) -> AdSetFacts:
    fields: dict[str, Any] = {
        "issue_codes": ("1815869",),
        "unusable_audience_ids": ("aud-gone",),
    }
    fields.update(overrides)
    return _adset(**fields)


# --- The exception that had to exist -------------------------------------
def test_a_group_the_provider_stopped_is_seen_at_all() -> None:
    """The gap this rule was written for. Every other rule requires an ad
    set to be *delivering* before it forms an opinion, which left the agent
    blind in the one case where a stopped advert is the whole story."""
    found = scan(account=_account(_broken()), policy=POLICY)

    assert [item.rule for item in found] == [PROVIDER_STOPPED]
    assert found[0].kind == "drop_audience"


@pytest.mark.parametrize("delivery", ["paused", "paused_above", "finished"])
def test_a_group_switched_off_by_its_owner_is_not_a_provider_fault(
    delivery: str,
) -> None:
    """A fault reported before the owner switched the group off is history.
    Read as the provider's doing, the card blamed Meta for the owner's own
    pause and offered to repair something nobody runs."""
    found = scan(account=_account(_broken(delivery=delivery)), policy=POLICY)

    assert found == []


def test_learning_does_not_hide_it() -> None:
    """There is no learning left to protect. A group that is not being
    delivered is not learning who to deliver it to."""
    found = scan(account=_account(_broken(is_learning=True)), policy=POLICY)

    assert [item.rule for item in found] == [PROVIDER_STOPPED]


def test_a_fault_needs_no_window_of_days() -> None:
    """A fault is not a measurement. It is either reported or it is not,
    and an ad set stopped on its second day is stopped."""
    found = scan(account=_account(_broken(days_with_spend=1)), policy=POLICY)

    assert [item.rule for item in found] == [PROVIDER_STOPPED]


# --- And what it refuses to touch ----------------------------------------
def test_nothing_is_proposed_for_a_group_with_no_fault() -> None:
    found = scan(account=_account(_adset(delivery="paused")), policy=POLICY)

    assert [item.rule for item in found if item.rule == PROVIDER_STOPPED] == []


def test_a_delivering_group_is_not_repaired() -> None:
    """The fault reported here is one the provider stopped delivery over.
    A group still running with a stale issue on it is not that."""
    found = scan(
        account=_account(_broken(delivery="active", days_with_spend=1)),
        policy=POLICY,
    )

    assert [item.rule for item in found if item.rule == PROVIDER_STOPPED] == []


def test_a_fault_with_nothing_removable_proposes_nothing() -> None:
    """The unrepairable case, and it is the ordinary one: a code about
    something other than an audience, or an audience the mirror has never
    been synced for. The line is already on the owner's waiting list in the
    provider's own words - a card offering a change that would not fix it
    is worse than no card."""
    found = scan(
        account=_account(_broken(unusable_audience_ids=())),
        policy=POLICY,
    )

    assert found == []


def test_a_fault_on_the_excluded_side_is_left_alone() -> None:
    """Removing an unusable *exclusion* would show the advert to the very
    people somebody took the trouble to keep away from it, which is worse
    than an advert that is switched off."""
    kept_out: dict[str, Any] = {
        "age_min": 18,
        "excluded_custom_audiences": [{"id": "aud-gone"}],
    }
    found = scan(
        account=_account(_broken(targeting=kept_out)),
        policy=POLICY,
    )

    assert found == []


# --- What the card is told ------------------------------------------------
def test_the_evidence_carries_the_codes_and_the_counts() -> None:
    """Numbers for the screen, codes for the replay: a proposal read a year
    later has to be re-checkable against what the provider said."""
    found = scan(account=_account(_broken()), policy=POLICY)
    evidence = found[0].evidence

    assert evidence["issue_codes"] == ["1815869"]
    assert evidence["dropped_audiences"] == 1
    assert evidence["kept_audiences"] == 1


def test_taking_the_only_list_out_is_said_out_loud() -> None:
    """The same edit, two very different decisions. One of three lists
    gone is a repair; the only list gone means the advert goes to anybody
    the rest of the settings allow."""
    alone: dict[str, Any] = {"custom_audiences": [{"id": "aud-gone"}]}
    found = scan(account=_account(_broken(targeting=alone)), policy=POLICY)

    assert found[0].evidence["kept_audiences"] == 0


def test_a_stopped_group_never_weighs_nothing() -> None:
    """Weight ranks the list, and a group whose figures went to nought the
    day it broke must not sort below one that is merely expensive."""
    found = scan(
        account=_account(_broken(totals={"spend_minor": 0, "leads": 0})),
        policy=POLICY,
    )

    assert found[0].weight == 15_000


# --- The provider's own advice -------------------------------------------
def _advised(**overrides: Any) -> AdSetFacts:
    """A delivering group Meta advises on, whose leads cost what the account's
    do - so the advice is the only thing there is to propose about it."""
    fields: dict[str, Any] = {
        "advice": ("broader_audience",),
        "delivery": "active",
        "totals": {"leads": 40, "qualified": 16},
    }
    fields.update(overrides)
    return _adset(**fields)


def test_the_platforms_own_advice_becomes_a_proposal() -> None:
    """It is on every mirrored ad set, and this rule is what turns it into
    something somebody can act on."""
    found = [
        item
        for item in scan(account=_account(_advised()), policy=POLICY)
        if item.rule == PROVIDER_ADVICE
    ]

    assert found and found[0].kind == "swap_targeting"


def test_advice_the_group_has_already_taken_proposes_nothing() -> None:
    """A button that changes nothing is the one failure a button cannot
    recover from - and the provider does leave the recommendation on an ad
    set that has taken it."""
    taken = dict(AIMED) | {"targeting_automation": {"advantage_audience": 1}}
    found = scan(account=_account(_advised(targeting=taken)), policy=POLICY)

    assert [item.rule for item in found if item.rule == PROVIDER_ADVICE] == []


def test_advice_is_not_acted_on_while_the_group_is_learning() -> None:
    """Unlike its neighbour: this is an improvement to something that is
    running, and editing the targeting of a group the provider is still
    learning for throws that learning away for nothing."""
    found = scan(account=_account(_advised(is_learning=True)), policy=POLICY)

    assert [item.rule for item in found if item.rule == PROVIDER_ADVICE] == []


def test_the_age_limits_the_mode_will_not_accept_are_named() -> None:
    """The provider refuses this mode above an ``age_min`` of 25 and takes
    no ``age_max`` at all, so an advertiser who typed an upper age is about
    to be sent a spec without one."""
    narrow = dict(AIMED) | {"age_min": 35, "age_max": 55}
    found = [
        item
        for item in scan(account=_account(_advised(targeting=narrow)), policy=POLICY)
        if item.rule == PROVIDER_ADVICE
    ]

    assert set(found[0].evidence["changed"]) == {"age_min", "age_max"}
    assert found[0].payload["targeting"]["age_min"] == 25
    assert "age_max" not in found[0].payload["targeting"]


# --- The cap, and the one thing it does not apply to ---------------------
def test_every_fault_is_offered_however_many_there_are() -> None:
    """ "They will still be there tomorrow" is the argument for the cap and
    it is true of every improvement. It is not true of an advert the
    provider has switched off, and a cap here would mean this product
    choosing which of somebody's broken campaigns to mention."""
    broken = [
        _broken(external_id=f"adset-{index}", totals={"spend_minor": 1_000 * index})
        for index in range(1, 6)
    ]

    offered = find(account=_account(*broken), policy=POLICY)

    assert len(offered) == 5
    assert POLICY.max_per_run == 3


def test_the_cap_still_holds_for_the_improvements_beside_them() -> None:
    """One list, two allowances: the faults are all offered and the
    improvements still stop at three."""
    broken = [_broken(external_id=f"broken-{index}") for index in range(2)]
    advised = [
        _advised(external_id=f"advised-{index}", totals={"spend_minor": 10_000 * index})
        for index in range(1, 6)
    ]

    offered = find(account=_account(*broken, *advised), policy=POLICY)
    kinds = [item.rule for item in offered]

    assert kinds.count(PROVIDER_STOPPED) == 2
    assert kinds.count(PROVIDER_ADVICE) == 3


# --- The two pure helpers under them --------------------------------------
def test_the_spec_that_arrives_is_never_edited_in_place() -> None:
    """The rest of the pass is still reading it."""
    spec = {"custom_audiences": [{"id": "aud-gone"}, {"id": "aud-live"}]}

    repair(spec, unusable=["aud-gone"])
    broaden(spec)

    assert spec["custom_audiences"] == [{"id": "aud-gone"}, {"id": "aud-live"}]


def test_an_empty_list_is_not_left_behind() -> None:
    """The provider reads an absent key as "no such constraint" and an
    empty list as an error."""
    fixed = repair({"custom_audiences": [{"id": "aud-gone"}]}, unusable=["aud-gone"])

    assert fixed is not None
    assert "custom_audiences" not in fixed.targeting


def test_a_spec_written_with_bare_ids_is_read_too() -> None:
    """An account inherited from a media buyer is exactly what this reads."""
    spec = {"custom_audiences": ["aud-gone", "aud-live"]}

    fixed = repair(spec, unusable=["aud-gone"])

    assert fixed is not None
    assert fixed.dropped == ("aud-gone",)
    assert fixed.kept == 1


# --- The campaigns somebody else built ------------------------------------
def test_a_campaign_built_elsewhere_is_never_given_a_new_audience() -> None:
    """The reason the restriction is declared on the rule rather than
    written inside five of them: an inherited campaign
    gets a stop and a budget, never a new audience. Somebody chose that
    targeting in a console this product cannot see the reasoning of."""
    found = scan(account=_account(_broken(is_ours=False)), policy=POLICY)

    assert found == []


def test_the_provider_s_advice_stops_at_our_own_campaigns_too() -> None:
    """It is the platform's advice and it is still an audience change."""
    found = scan(account=_account(_advised(is_ours=False)), policy=POLICY)

    assert [item.rule for item in found if item.rule == PROVIDER_ADVICE] == []


def test_a_campaign_built_elsewhere_gets_nothing_at_all() -> None:
    """Not even a stop over money leaving it: a campaign made in Ads
    Manager is its owner's to run there."""
    burning = _adset(
        delivery="active",
        is_ours=False,
        totals={"spend_minor": 900_000, "leads": 0, "qualified": 0},
        days_with_spend=7,
    )

    found = scan(account=_account(burning), policy=POLICY)

    assert found == []
