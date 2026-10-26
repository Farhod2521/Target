"""core/agent/rules: the five things the agent knows how to notice.

No database and no clock. Every threshold is a comparison against figures
handed in, which is what lets a rule be argued with in a test rather than
observed in production a fortnight later.
"""

from dataclasses import replace
from typing import Any

from adskit import ProviderName

from core.agent import AccountFacts, AdSetFacts, Policy, Recent, find, holds, scan
from core.agent.rules import EXPENSIVE, IDLE, STARVED, WASTING, WINNING
from core.metrics import Totals
from tests.core.agent.pace import at_week_pace

META = ProviderName("meta")
POLICY = Policy()


def _adset(**overrides: Any) -> AdSetFacts:
    figures = {
        "spend_minor": 100_000,
        "impressions": 10_000,
        "clicks": 300,
        "leads": 10,
        "qualified": 4,
    }
    figures.update(overrides.pop("totals", {}))
    totals = Totals(**{"leads_reported": figures.get("leads", 0), **figures})
    overrides.setdefault("recent", at_week_pace(totals))
    return AdSetFacts(
        external_id=overrides.pop("external_id", "adset-1"),
        campaign_external_id=overrides.pop("campaign_external_id", "camp-1"),
        name=overrides.pop("name", "Yosh onalar"),
        delivery=overrides.pop("delivery", "active"),
        totals=totals,
        days_with_spend=overrides.pop("days_with_spend", 7),
        daily_budget_minor=overrides.pop("daily_budget_minor", 15_000),
        # A lead ad set unless a test says otherwise, which is what almost
        # every test in this file is about. The dataclass itself defaults
        # the other way - the safe way - so a caller who forgets loses a
        # proposal rather than judging a call campaign on leads it cannot
        # produce. See ``core.metrics.counts_leads``.
        counts_leads=overrides.pop("counts_leads", True),
        # A campaign this product built, unless a test says otherwise. The
        # dataclass defaults the other way - the safe way - so a caller who
        # forgets loses a proposal rather than rewriting the audience of a
        # campaign somebody built in Ads Manager. See ``AdSetFacts.is_ours``.
        is_ours=overrides.pop("is_ours", True),
        **overrides,
    )


def _with(totals: Totals, adsets: tuple[AdSetFacts, ...]) -> Totals:
    return replace(
        totals,
        spend_minor=totals.spend_minor + sum(a.totals.spend_minor for a in adsets),
        leads=totals.leads + sum(a.totals.leads for a in adsets),
        leads_reported=totals.leads_reported
        + sum(a.totals.leads_reported for a in adsets),
    )


def _account(*adsets: AdSetFacts, **overrides: Any) -> AccountFacts:
    totals = overrides.pop(
        "totals",
        Totals(spend_minor=1_000_000, leads=100, leads_reported=100, qualified=40),
    )
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=totals,
        # The benchmark, and the same figure unless a test separates them.
        # They are one field apart on purpose: what the account spent
        # includes campaigns that cannot produce a lead, and what a lead
        # costs cannot. The tests that care pass this explicitly.
        #
        # ``totals`` is the account's *other* groups: the groups handed in
        # are added on top, because a group is measured against the rest
        # of the account and never against a sum it is part of.
        lead_totals=overrides.pop("lead_totals", None) or _with(totals, adsets),
        adsets=adsets,
    )


# --- wasting -------------------------------------------------------------
def test_spending_far_past_a_normal_lead_with_none_to_show_is_a_stop() -> None:
    burning = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 90_000})

    found = scan(account=_account(burning), policy=POLICY)

    assert [item.rule for item in found] == [WASTING]
    assert found[0].kind == "pause"
    assert found[0].evidence["account_cpl_minor"] == 10_000


def test_zero_leads_alone_is_not_enough() -> None:
    """Below the threshold there is nothing to conclude. An account whose
    leads cost 10 000 has learned nothing from an ad set that spent 20 000."""
    quiet = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 20_000})

    assert scan(account=_account(quiet), policy=POLICY) == []


def test_an_account_that_has_never_had_a_lead_gets_no_stop_proposed() -> None:
    """There is no benchmark, so there is no such thing as worse than usual.

    A brand-new account is exactly where a confident stop would be most
    damaging and least justified.
    """
    burning = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 900_000})
    account = _account(
        burning, totals=Totals(spend_minor=900_000, leads=0, leads_reported=0)
    )

    assert scan(account=account, policy=POLICY) == []


# --- learning ------------------------------------------------------------
def test_nothing_is_proposed_about_an_ad_set_that_is_still_learning() -> None:
    """It has no leads *because* it is learning. A product that read that as
    failure would stop every campaign three days after starting it."""
    fresh = _adset(
        totals={"leads": 0, "qualified": 0, "spend_minor": 900_000},
        is_learning=True,
    )

    assert scan(account=_account(fresh), policy=POLICY) == []


def test_nothing_is_proposed_about_an_ad_set_too_young_to_judge() -> None:
    infant = _adset(
        days_with_spend=2, totals={"leads": 0, "qualified": 0, "spend_minor": 900_000}
    )

    assert scan(account=_account(infant), policy=POLICY) == []


# --- winning -------------------------------------------------------------
def test_cheap_and_pressed_against_its_budget_earns_more_money() -> None:
    star = _adset(
        totals={"leads": 30, "qualified": 20, "spend_minor": 105_000},
        daily_budget_minor=15_000,
    )

    found = scan(account=_account(star), policy=POLICY)

    assert [item.rule for item in found] == [WINNING]
    assert found[0].payload["daily_budget_minor"] == 18_000
    assert found[0].evidence["spend_share"] == 100


def test_cheap_but_not_spending_its_budget_is_not_offered_more() -> None:
    """It already has money it cannot spend. Raising the figure changes a
    number in an interface and nothing in the account."""
    idle_money = _adset(
        totals={"leads": 30, "qualified": 20, "spend_minor": 40_000},
        daily_budget_minor=15_000,
    )

    found = scan(account=_account(idle_money), policy=POLICY)

    assert WINNING not in [item.rule for item in found]


def test_cheap_leads_nobody_marked_still_earn_more_money() -> None:
    """The quality mark is switched off, so a raise rests on leads alone."""
    star = _adset(
        totals={"leads": 30, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
    )

    found = scan(
        account=_account(
            star, totals=Totals(spend_minor=1_000_000, leads=100, leads_reported=100)
        ),
        policy=POLICY,
    )

    assert [item.rule for item in found] == [WINNING]


def test_one_lucky_lead_does_not_earn_a_raise() -> None:
    lucky = _adset(
        totals={"leads": 1, "qualified": 1, "spend_minor": 105_000},
        daily_budget_minor=15_000,
    )

    assert [item.rule for item in scan(account=_account(lucky), policy=POLICY)] != [
        WINNING
    ]


def test_four_cheap_leads_are_not_yet_a_price_to_raise_on() -> None:
    """On four, one lucky day is the whole difference."""
    few = _adset(
        totals={"leads": 4, "qualified": 0, "spend_minor": 20_000},
        daily_budget_minor=3_000,
    )

    assert WINNING not in [
        item.rule for item in scan(account=_account(few), policy=POLICY)
    ]


def test_cheap_leads_under_three_results_worth_are_not_raised_on() -> None:
    """Six leads at 4 000 against the usual 10 000, on 24 000 spent: under
    the 30 000 the brief asks before any budget is changed."""
    early = _adset(
        totals={"leads": 6, "qualified": 0, "spend_minor": 24_000},
        daily_budget_minor=3_500,
    )

    assert WINNING not in [
        item.rule for item in scan(account=_account(early), policy=POLICY)
    ]


def test_a_limited_group_is_not_raised_on_its_price() -> None:
    star = _adset(
        totals={"leads": 30, "qualified": 20, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        learning_limited=True,
    )

    assert WINNING not in [
        item.rule for item in scan(account=_account(star), policy=POLICY)
    ]


# --- expensive -----------------------------------------------------------
def _lately(*, spend: int, leads: int) -> Recent:
    """The last three finished days - the days the brief prices by."""
    return Recent(
        days=3,
        totals=Totals(spend_minor=spend, leads=leads, leads_reported=leads),
    )


def test_working_but_dearer_than_the_account_gets_less_money() -> None:
    """Not a stop: it does produce leads, and switching it off would lose
    them. 21 000 a lead over the last three days against the usual 10 000
    is past twice it - the brief's line for acting."""
    pricey = _adset(
        totals={"leads": 5, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        recent=_lately(spend=63_000, leads=3),
    )

    found = scan(account=_account(pricey), policy=POLICY)

    assert [item.rule for item in found] == [EXPENSIVE]
    assert found[0].payload["daily_budget_minor"] == 12_000
    assert found[0].evidence["cpl_minor"] == 21_000
    assert found[0].evidence["account_cpl_minor"] == 10_000
    assert (found[0].evidence["days"], found[0].evidence["leads"]) == (3, 3)


def test_dearer_but_short_of_the_line_is_left_alone() -> None:
    """Twice the usual exactly is the morning report's warning, not a card."""
    close = _adset(
        totals={"leads": 6, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        recent=_lately(spend=60_000, leads=3),
    )

    found = scan(account=_account(close), policy=POLICY)

    assert EXPENSIVE not in [item.rule for item in found]


def test_dear_lately_on_too_little_money_is_left_alone() -> None:
    """Two and a half times the usual, on a group that spent less than
    three results' usual price: the brief decides nothing on it."""
    thin = _adset(
        totals={"leads": 1, "qualified": 0, "spend_minor": 25_000},
        daily_budget_minor=15_000,
        recent=_lately(spend=25_000, leads=1),
    )

    found = scan(account=_account(thin), policy=POLICY)

    assert EXPENSIVE not in [item.rule for item in found]


def test_a_small_budget_s_dear_days_are_judged_on_the_whole_window() -> None:
    """25 000 for one lead these three days, under three results' worth on
    its own - but the group spent 105 000, and the brief asks whether the
    group has said enough."""
    dear = _adset(
        totals={"leads": 5, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        recent=_lately(spend=25_000, leads=1),
    )

    found = scan(account=_account(dear), policy=POLICY)

    assert EXPENSIVE in [item.rule for item in found]


def test_a_dear_week_with_ordinary_last_days_is_left_alone() -> None:
    """The week's price is dear, the last three days' is not: the price has
    already come back, and cutting the budget now cuts a group that works."""
    recovered = _adset(
        totals={"leads": 5, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        recent=_lately(spend=40_000, leads=4),
    )

    found = scan(account=_account(recovered), policy=POLICY)

    assert EXPENSIVE not in [item.rule for item in found]


def test_a_dear_group_still_learning_is_not_touched() -> None:
    """The provider's early price is the provider still searching."""
    learning = _adset(
        totals={"leads": 5, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        is_learning=True,
    )

    found = scan(account=_account(learning), policy=POLICY)

    assert EXPENSIVE not in [item.rule for item in found]


def test_the_providers_lead_count_keeps_a_group_from_looking_dear() -> None:
    """Five leads reached us and nine were counted by Meta: a lost webhook
    is not a price, and the larger count is the one read."""
    undercounted = _adset(
        totals={
            "leads": 5,
            "leads_reported": 9,
            "qualified": 0,
            "spend_minor": 105_000,
        },
        daily_budget_minor=15_000,
    )

    found = scan(account=_account(undercounted), policy=POLICY)

    assert EXPENSIVE not in [item.rule for item in found]


def test_a_budget_that_would_fall_under_the_floor_is_not_proposed() -> None:
    """A figure the provider rejects on arrival is a button that fails when
    pressed, which is worse than no button."""
    pricey = _adset(
        totals={"leads": 5, "qualified": 0, "spend_minor": 105_000},
        daily_budget_minor=15_000,
        floor_minor=14_000,
    )

    found = scan(account=_account(pricey), policy=POLICY)

    assert EXPENSIVE not in [item.rule for item in found]


# --- starved -------------------------------------------------------------
def test_an_ad_set_that_cannot_spend_its_budget_gets_a_wider_audience() -> None:
    """The one rule where more money is the wrong answer. The provider stops
    delivering long before the budget is gone."""
    starving = _adset(
        totals={"leads": 2, "qualified": 1, "spend_minor": 30_000},
        daily_budget_minor=15_000,
        targeting={
            "geo_locations": {
                "custom_locations": [{"radius": 5, "distance_unit": "kilometer"}]
            },
        },
    )

    found = scan(account=_account(starving), policy=POLICY)

    assert [item.rule for item in found] == [STARVED]
    assert found[0].kind == "swap_targeting"
    assert found[0].payload["step"] == "radius"
    widened = found[0].payload["targeting"]["geo_locations"]
    assert widened["custom_locations"][0]["radius"] == 10


def test_a_starved_ad_set_with_nowhere_left_to_widen_is_left_alone() -> None:
    """A suggestion amounting to "we tried" is noise on a screen whose whole
    value is that everything on it is worth reading."""
    stuck = _adset(
        totals={"leads": 2, "qualified": 1, "spend_minor": 30_000},
        daily_budget_minor=15_000,
        targeting={"age_min": 18, "age_max": 65},
    )

    assert scan(account=_account(stuck), policy=POLICY) == []


# --- idle ----------------------------------------------------------------
def test_a_campaign_the_agent_stopped_completely_is_offered_back() -> None:
    stopped = _adset(
        external_id="adset-1",
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 8, "qualified": 5, "spend_minor": 50_000},
    )

    found = scan(account=_account(stopped), policy=POLICY)

    assert [item.rule for item in found] == [IDLE]
    assert found[0].kind == "resume"
    assert found[0].ref.id == "adset-1"


def test_a_campaign_the_owner_stopped_is_not_argued_with() -> None:
    """The shop is closed, the stock ran out, the season is over. A product
    that proposes undoing that every night has mistaken its own opinion for
    information."""
    stopped = _adset(delivery="paused", stopped_by_agent=False)

    assert scan(account=_account(stopped), policy=POLICY) == []


def test_the_cheapest_of_several_stopped_groups_is_the_one_offered() -> None:
    dear = _adset(
        external_id="dear",
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 4, "qualified": 1, "spend_minor": 80_000},
    )
    cheap = _adset(
        external_id="cheap",
        delivery="paused",
        stopped_by_agent=True,
        totals={"leads": 9, "qualified": 6, "spend_minor": 60_000},
    )

    found = scan(account=_account(dear, cheap), policy=POLICY)

    assert [item.ref.id for item in found] == ["cheap"]


def test_a_campaign_with_one_group_still_running_is_not_idle() -> None:
    running = _adset(external_id="running", totals={"leads": 5, "qualified": 2})
    stopped = _adset(external_id="stopped", delivery="paused", stopped_by_agent=True)

    found = scan(account=_account(running, stopped), policy=POLICY)

    assert IDLE not in [item.rule for item in found]


# --- one per object, ranked, capped --------------------------------------
def test_one_object_produces_at_most_one_proposal() -> None:
    """Two buttons about the same ad set are two buttons whose combined
    effect nobody worked out."""
    both = _adset(
        totals={"leads": 0, "qualified": 0, "spend_minor": 90_000},
        daily_budget_minor=100_000,
        targeting={
            "geo_locations": {
                "custom_locations": [{"radius": 5, "distance_unit": "kilometer"}]
            }
        },
    )

    found = scan(account=_account(both), policy=POLICY)

    assert len(found) == 1


def test_the_cap_keeps_the_ones_about_the_most_money() -> None:
    small = _adset(
        external_id="small", totals={"leads": 0, "qualified": 0, "spend_minor": 40_000}
    )
    large = _adset(
        external_id="large", totals={"leads": 0, "qualified": 0, "spend_minor": 900_000}
    )
    middle = _adset(
        external_id="middle", totals={"leads": 0, "qualified": 0, "spend_minor": 90_000}
    )
    account = _account(small, large, middle)

    kept = find(account=account, policy=Policy(max_per_run=2))

    assert [item.ref.id for item in kept] == ["large", "middle"]


def test_a_blocked_object_produces_nothing() -> None:
    """A budget raised yesterday has not had a full day of delivery, so
    tonight's figures describe the ad set before the change."""
    burning = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 90_000})

    assert find(account=_account(burning), policy=POLICY, blocked={"adset-1"}) == []


def test_a_refused_pair_is_not_proposed_again() -> None:
    """The same conclusion from the same arithmetic the morning after a
    rejection is not new information, it is the agent arguing."""
    burning = _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 90_000})

    found = find(
        account=_account(burning), policy=POLICY, refused={(WASTING, "adset-1")}
    )

    assert found == []


def test_a_refusal_gags_one_rule_not_the_object() -> None:
    """ "Do not stop this" is not "have no opinion about this ad set": a
    different rule noticing something new may still speak."""
    burning = _adset(
        totals={"leads": 0, "qualified": 0, "spend_minor": 60_000},
        targeting={"age_min": 25, "age_max": 45},
    )

    unrefused = scan(account=_account(burning), policy=POLICY)
    found = scan(
        account=_account(burning), policy=POLICY, refused={(WASTING, "adset-1")}
    )

    assert [item.rule for item in unrefused] == [WASTING]
    assert [item.rule for item in found] == [STARVED]


# --- the re-check --------------------------------------------------------
def test_a_proposal_still_holding_comes_back_with_tonight_s_figures() -> None:
    """It is the fresh finding that gets carried out, not the stored one: a
    budget computed on Tuesday is the wrong figure to write on Thursday."""
    yesterday = scan(
        account=_account(
            _adset(
                totals={"leads": 30, "qualified": 20, "spend_minor": 105_000},
                daily_budget_minor=15_000,
            )
        ),
        policy=POLICY,
    )[0]
    tonight = scan(
        account=_account(
            _adset(
                totals={"leads": 30, "qualified": 20, "spend_minor": 140_000},
                daily_budget_minor=20_000,
            )
        ),
        policy=POLICY,
    )

    fresh = holds(finding=yesterday, found=tonight)

    assert fresh is not None
    assert fresh.payload["daily_budget_minor"] == 24_000


def test_a_proposal_the_account_moved_past_no_longer_holds() -> None:
    """A stop proposed for an ad set with no leads is not a stop to make
    once it has brought one in."""
    tuesday = scan(
        account=_account(
            _adset(totals={"leads": 0, "qualified": 0, "spend_minor": 90_000})
        ),
        policy=POLICY,
    )[0]
    thursday = scan(
        account=_account(
            _adset(totals={"leads": 3, "qualified": 2, "spend_minor": 92_000})
        ),
        policy=POLICY,
    )

    assert holds(finding=tuesday, found=thursday) is None


def test_two_dear_leads_are_not_yet_a_price_to_cut_on() -> None:
    """Twice the usual on two leads: a bad day, not a price."""
    two = _adset(
        totals={"leads": 2, "qualified": 0, "spend_minor": 40_000},
        daily_budget_minor=15_000,
    )

    assert EXPENSIVE not in [
        item.rule for item in scan(account=_account(two), policy=POLICY)
    ]


def test_three_times_the_usual_price_is_said_on_two_leads() -> None:
    far = _adset(
        totals={"leads": 2, "qualified": 0, "spend_minor": 60_000},
        daily_budget_minor=15_000,
        recent=_lately(spend=60_000, leads=2),
    )

    assert EXPENSIVE in [
        item.rule for item in scan(account=_account(far), policy=POLICY)
    ]


def test_a_group_alone_on_its_account_has_nothing_to_be_dearer_than() -> None:
    alone = _adset(totals={"leads": 5, "qualified": 0, "spend_minor": 500_000})

    found = scan(account=_account(alone, totals=Totals()), policy=POLICY)

    assert [item.rule for item in found if item.rule in (EXPENSIVE, WINNING)] == []
