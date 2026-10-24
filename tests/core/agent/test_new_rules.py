"""Three rules, argued one boundary at a time.

No database and no clock, like the five beside them. What each one needs
to see is handed in as a value, which is what lets "not quite enough
evidence" be a test rather than something noticed on a customer's account
a fortnight later.
"""

from typing import Any

from adskit import MinorUnits, ProviderName

from core.agent import AccountFacts, AdSetFacts, Funnel, Half, Policy, scan
from core.agent.rules import JUNK, NARROW_AUDIENCE, SATURATED, junk
from core.agent.rules.audience import MIN_HALF_IMPRESSIONS
from core.metrics import SegmentFigures, Totals, compare_segments

META = ProviderName("meta")
POLICY = Policy()

# A spec whose audience is the advertiser's own - the precondition every
# narrowing has, see ``core.agent.narrow.keeps_its_audience``.
CHOSEN: dict[str, Any] = {
    "age_min": 18,
    "age_max": 65,
    "targeting_automation": {"advantage_audience": 0},
}


def _adset(**overrides: Any) -> AdSetFacts:
    figures = {
        "spend_minor": 300_000,
        "impressions": 60_000,
        "clicks": 900,
        "leads": 0,
        "qualified": 0,
        "leads_reported": 0,
    }
    figures.update(overrides.pop("totals", {}))
    # The funnel the diagnosis and the price benchmark read, from the same
    # figures - a group nobody was shown is left out of every average.
    overrides.setdefault(
        "funnel",
        Funnel(
            spend_minor=figures["spend_minor"],
            impressions=figures["impressions"],
            link_clicks=figures["clicks"],
        ),
    )
    return AdSetFacts(
        external_id=overrides.pop("external_id", "adset-1"),
        campaign_external_id="camp-1",
        name="Yosh onalar",
        delivery=overrides.pop("delivery", "active"),
        totals=Totals(**figures),
        days_with_spend=overrides.pop("days_with_spend", 7),
        daily_budget_minor=overrides.pop("daily_budget_minor", 15_000),
        counts_leads=overrides.pop("counts_leads", True),
        # A campaign this product built, unless a test says otherwise. The
        # dataclass defaults the other way - the safe way - so a caller who
        # forgets loses a proposal rather than rewriting the audience of a
        # campaign somebody built in Ads Manager. See ``AdSetFacts.is_ours``.
        is_ours=overrides.pop("is_ours", True),
        **overrides,
    )


def _account(*adsets: AdSetFacts, **overrides: Any) -> AccountFacts:
    totals = overrides.pop(
        "totals", Totals(spend_minor=1_000_000, leads=100, qualified=40)
    )
    return AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=totals,
        lead_totals=overrides.pop("lead_totals", totals),
        adsets=adsets,
    )


def _codes(account: AccountFacts) -> list[str]:
    return [item.rule for item in scan(account=account, policy=POLICY)]


# --- junk: leads arrive, none of them are wanted --------------------------
def _junking(**overrides: Any) -> AdSetFacts:
    figures: dict[str, Any] = {"totals": {"leads": 20, "qualified": 0}}
    figures.update(overrides)
    return _adset(**figures)


def test_the_night_proposes_nothing_from_marks_made_before_they_were_switched_off() -> (
    None
):
    """The owner's quality mark is switched off, and a verdict read from the
    marks made before that is a verdict nobody gives any more. The rule is
    kept for when the mark comes back, and asked directly below."""
    assert JUNK not in _codes(_account(_junking()))


def test_leads_the_owner_wants_none_of_is_a_stop() -> None:
    found = junk(account=_account(_junking()), policy=POLICY)

    assert [item.rule for item in found] == [JUNK]
    assert found[0].kind == "pause"
    assert found[0].evidence["leads"] == 20
    assert found[0].evidence["account_quality_share"] == 40


def test_too_few_leads_to_expect_a_good_one_says_nothing() -> None:
    """At an expectation under three, seeing none is a coin this rule would
    lose too often - and losing it stops a campaign doing nothing wrong."""
    thin = _junking(totals={"leads": 5, "qualified": 0})

    assert junk(account=_account(thin), policy=POLICY) == []


def test_one_good_lead_is_enough_to_leave_it_alone() -> None:
    """The complaint is that *none* of them were wanted. One that was is a
    different conversation, and the cost rules are already having it."""
    working = _junking(totals={"leads": 20, "qualified": 1})

    assert junk(account=_account(working), policy=POLICY) == []


def test_an_account_that_marks_nothing_gets_no_verdict_from_this_rule() -> None:
    """An owner's silence is a fact about their habits, not about a
    campaign - and this is the one rule that could mistake the two."""
    unmarked = Totals(spend_minor=1_000_000, leads=100, qualified=0)

    assert junk(account=_account(_junking(), lead_totals=unmarked), policy=POLICY) == []


# --- saturated: the same people, more often, clicking less ----------------
def _worn(**overrides: Any) -> AdSetFacts:
    figures: dict[str, Any] = {
        "early": Half(days=3, impressions=30_000, link_clicks=300, frequency=120),
        "late": Half(days=4, impressions=30_000, link_clicks=120, frequency=180),
        "targeting": {"age_min": 25, "age_max": 45},
        "totals": {"leads": 4, "qualified": 2},
    }
    figures.update(overrides)
    return _adset(**figures)


def _neighbour() -> AdSetFacts:
    """A lead group on the same account whose leads come cheap - what makes
    the worn group's four leads dear rather than simply the account's price."""
    return _adset(external_id="steady", totals={"leads": 60, "qualified": 20})


def _saturated(*adsets: AdSetFacts) -> list[Any]:
    found = scan(account=_account(*adsets, _neighbour()), policy=POLICY)
    return [item for item in found if item.rule == SATURATED]


def test_a_falling_click_rate_beside_a_climbing_frequency_is_fatigue() -> None:
    found = _saturated(_worn())

    assert [item.kind for item in found] == ["swap_targeting"]
    assert found[0].evidence["ctr_drop_pct"] == 60
    assert found[0].evidence["late_ctr_bp"] == 40
    assert (found[0].evidence["outcome"], found[0].evidence["results"]) == ("lead", 4)
    assert found[0].evidence["cost_minor"] == 75_000


def test_fatigue_on_a_group_whose_leads_are_still_cheap_is_left_alone() -> None:
    """Tired attention is not a result. Leads at the account's usual price
    mean the group is working, and its audience is not thrown away."""
    cheap = _worn(totals={"leads": 60, "qualified": 20})

    assert _saturated(cheap) == []


def test_fatigue_on_a_campaign_built_elsewhere_is_left_alone() -> None:
    assert _saturated(_worn(is_ours=False)) == []


def test_a_falling_click_rate_alone_is_just_a_bad_week() -> None:
    """Without the frequency climbing, this is a dip - a competitor
    outbidding us, a season, a holiday - and widening answers none of it."""
    dipping = _worn(
        late=Half(days=4, impressions=30_000, link_clicks=120, frequency=118)
    )

    assert _saturated(dipping) == []


def test_a_climbing_frequency_that_still_converts_is_left_alone() -> None:
    steady = _worn(
        late=Half(days=4, impressions=30_000, link_clicks=290, frequency=180)
    )

    assert _saturated(steady) == []


def test_a_half_too_thin_to_measure_says_nothing() -> None:
    """A rate over a few hundred impressions moves by a third on one or two
    clicks, which is the whole trap - the drop is a percentage of noise."""
    sparse = _worn(
        early=Half(
            days=3, impressions=MIN_HALF_IMPRESSIONS - 1, link_clicks=10, frequency=120
        ),
    )

    assert _saturated(sparse) == []


def test_one_day_a_side_is_not_a_direction() -> None:
    quick = _worn(
        early=Half(days=1, impressions=30_000, link_clicks=300, frequency=120)
    )

    assert _saturated(quick) == []


def test_an_audience_already_at_its_widest_gets_no_proposal() -> None:
    """The diagnosis stands and there is nothing to propose, which is the
    honest end of it - the same answer ``starved`` gives."""
    widest = _worn(targeting={"age_min": 18, "age_max": 65})

    assert _saturated(widest) == []


# --- narrow_audience: a slice that only ever spent ------------------------
def _cut(*rows: tuple[str, int, int]) -> Any:
    return compare_segments(
        [
            SegmentFigures(
                segment=segment,
                spend_minor=MinorUnits(spend),
                impressions=spend // 5,
                clicks=spend // 300,
                leads_reported=leads,
            )
            for segment, spend, leads in rows
        ]
    )


def _split(**overrides: Any) -> AdSetFacts:
    figures: dict[str, Any] = {
        "targeting": CHOSEN,
        # Priced exactly at the account's own average: this ad set is
        # not cheap and not dear, so the only thing wrong with it is
        # where a third of its money is going.
        "totals": {"spend_minor": 300_000, "leads": 20, "qualified": 12},
        "segments": _cut(
            ("18-24|male", 120_000, 0),
            ("25-34|male", 90_000, 12),
            ("35-44|female", 90_000, 10),
        ),
    }
    figures.update(overrides)
    return _adset(**figures)


def test_a_dead_age_band_taking_real_money_is_cut_out() -> None:
    found = scan(account=_account(_split()), policy=POLICY)

    assert [item.rule for item in found] == [NARROW_AUDIENCE]
    assert found[0].kind == "narrow_targeting"
    assert found[0].payload["targeting"]["age_min"] == 25
    assert found[0].evidence["dead_share_pct"] == 40


def test_a_dead_slice_too_small_to_matter_is_left_where_it_is() -> None:
    """Replacing an audience throws away the delivery learned so far, and
    doing that to reclaim a rounding error is the worse trade."""
    trivial = _split(
        totals={"spend_minor": 1_500_000, "leads": 100, "qualified": 60},
        segments=_cut(
            ("18-24|male", 120_000, 0),
            ("25-34|male", 690_000, 40),
            ("35-44|female", 690_000, 40),
        ),
    )

    assert NARROW_AUDIENCE not in _codes(_account(trivial))


def test_a_cut_where_nothing_converted_produces_no_dead_slice() -> None:
    """A goal the provider counts no leads for has no rate to judge
    against - which is why these rules need no ``needs_leads`` flag."""
    uncounted = _split(
        segments=_cut(
            ("18-24|male", 120_000, 0),
            ("25-34|male", 90_000, 0),
            ("35-44|female", 90_000, 0),
        ),
    )

    assert NARROW_AUDIENCE not in _codes(_account(uncounted))


def test_an_ad_set_with_no_segments_is_simply_not_judged() -> None:
    assert NARROW_AUDIENCE not in _codes(_account(_adset()))


def test_the_provider_choosing_the_audience_blocks_the_cut() -> None:
    automatic = _split(
        targeting={"age_min": 18, "age_max": 65}
        | {"targeting_automation": {"advantage_audience": 1}}
    )

    assert NARROW_AUDIENCE not in _codes(_account(automatic))


# --- the shared gate ------------------------------------------------------
def test_none_of_the_three_judges_a_learning_ad_set() -> None:
    learning = [
        _junking(is_learning=True),
        _worn(external_id="adset-2", is_learning=True),
        _split(external_id="adset-3", is_learning=True),
    ]

    assert _codes(_account(*learning)) == []


def test_none_of_the_three_judges_an_ad_set_without_enough_days() -> None:
    young = [
        _junking(days_with_spend=1),
        _worn(external_id="adset-2", days_with_spend=1),
        _split(external_id="adset-3", days_with_spend=1),
    ]

    assert _codes(_account(*young)) == []
