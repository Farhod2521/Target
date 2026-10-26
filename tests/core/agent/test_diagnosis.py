"""The diagnosis, one cause at a time.

No database and no clock. Most cases are two lead groups on one account:
the one being judged and a steady one beside it, whose figures are the
account's own - the only thing any rate here is compared with.
"""

from typing import Any

from adskit import ProviderName

from core.agent import (
    AccountFacts,
    AdFacts,
    AdSetFacts,
    Funnel,
    Half,
    Landing,
    Policy,
    Recent,
)
from core.agent.diagnosis import CAUSE_OF, CAUSES, Diagnosis, diagnose
from core.agent.signals import SIGNALS
from core.agent.usual import Usual
from core.metrics import SegmentFigures, Totals
from tests.core.agent.pace import at_week_pace

META = ProviderName("meta")
POLICY = Policy()


def group(**overrides: Any) -> AdSetFacts:
    """A lead group that spent a week. The defaults are the steady neighbour's."""
    spend = overrides.pop("spend", 300_000)
    impressions = overrides.pop("impressions", 100_000)
    clicks = overrides.pop("link_clicks", 1_500)
    leads = overrides.pop("leads", 30)
    reported = overrides.pop("reported", leads)
    results = overrides.pop("results", 0)
    totals = Totals(
        spend_minor=spend,
        impressions=impressions,
        clicks=clicks,
        leads=leads,
        leads_reported=reported,
        results=results,
    )
    overrides.setdefault("recent", at_week_pace(totals))
    return AdSetFacts(
        external_id=overrides.pop("external_id", "judged"),
        campaign_external_id="camp-1",
        name=overrides.pop("name", "Qish aksiyasi"),
        delivery=overrides.pop("delivery", "active"),
        totals=totals,
        days_with_spend=overrides.pop("days_with_spend", 7),
        counts_leads=overrides.pop("counts_leads", True),
        funnel=Funnel(
            spend_minor=spend,
            impressions=impressions,
            link_clicks=clicks,
            landing_page_views=overrides.pop("landing_page_views", 0),
            video_plays=overrides.pop("video_plays", 0),
            video_views_3s=overrides.pop("video_views_3s", 0),
        ),
        **overrides,
    )


def steady(**overrides: Any) -> AdSetFacts:
    return group(external_id="steady", name="Bahor", **overrides)


def advert(**rankings: str) -> AdFacts:
    """The group's only advert, carrying all of its money."""
    return AdFacts(
        name="Rasm",
        delivery="active",
        figures=SegmentFigures(segment="ad-1", spend_minor=300_000),
        quality_ranking=rankings.get("quality", "average"),
        engagement_ranking=rankings.get("engagement", "average"),
        conversion_ranking=rankings.get("conversion", "average"),
    )


def verdict(judged: AdSetFacts, *others: AdSetFacts) -> Diagnosis:
    account = AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(judged, *(others or (steady(),))),
    )
    found = {item.adset_id: item for item in diagnose(account=account, policy=POLICY)}
    return found[judged.external_id]


# --- well -----------------------------------------------------------------
def test_a_group_like_the_rest_of_the_account_has_no_problem() -> None:
    found = verdict(group())

    assert (found.cause, found.signals) == ("no_problem", ())


def test_a_weak_advert_on_a_cheap_group_is_still_named() -> None:
    """Leads cost what they cost everywhere here, and the advert is clicked
    a third as often. The brief reads top down and the first step that
    failed is the cause, whatever the price."""
    found = verdict(group(link_clicks=500, leads=30))

    assert (found.cause, found.signals[0]) == ("weak_creative", "low_ctr")


def test_a_lost_webhook_does_not_read_as_a_stalled_form() -> None:
    """Our count is nought, the provider's is thirty. The larger is read."""
    found = verdict(group(leads=0, reported=30))

    assert found.cause == "no_problem"


# --- facts ----------------------------------------------------------------
def test_a_group_the_provider_stopped_is_that_whatever_else_is_wrong() -> None:
    found = verdict(
        group(delivery="error", issue_codes=("1815",), link_clicks=500, leads=0)
    )

    assert found.cause == "provider_stopped"
    assert found.evidence["issue_codes"] == ["1815"]


def test_a_page_that_does_not_open_comes_before_the_advert() -> None:
    down = Landing(down_urls=("https://osh.example/",))
    found = verdict(group(link_clicks=500, leads=0, landing=down))

    assert found.cause == "landing_blocks"
    assert found.signals[0] == "site_down"
    assert found.evidence["down_urls"] == ["https://osh.example/"]


def test_a_learning_group_is_too_early_even_with_no_leads() -> None:
    found = verdict(group(is_learning=True, leads=0, days_with_spend=4))

    assert found.cause == "too_early"


def test_a_week_of_learning_far_short_of_fifty_results_is_stuck() -> None:
    """Waiting will not finish it: the advice is a wider audience, a bigger
    budget or fewer groups, not patience."""
    found = verdict(group(is_learning=True, leads=3, days_with_spend=7))

    assert found.cause == "learning_limited"
    assert "learning_stuck" in found.signals


def test_under_the_providers_own_floor_is_too_early() -> None:
    found = verdict(group(impressions=400, link_clicks=5, leads=0))

    assert found.cause == "too_early"
    assert "few_impressions" in found.signals


def test_a_group_its_owner_paused_gets_no_diagnosis() -> None:
    account = AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(group(delivery="paused"), steady()),
    )

    found = diagnose(account=account, policy=POLICY)

    assert [item.adset_id for item in found] == ["steady"]


# --- shown and clicked ----------------------------------------------------
def test_nobody_clicking_is_the_advert() -> None:
    found = verdict(group(link_clicks=500, leads=0))

    assert found.cause == "weak_creative"
    assert found.signals[0] == "low_ctr"
    # The account's figure is the neighbour's alone: a group is never
    # compared with a sum it is part of.
    assert (found.evidence["link_ctr_bp"], found.evidence["account_link_ctr_bp"]) == (
        50,
        150,
    )


def test_dear_to_show_comes_before_the_advert() -> None:
    """The brief reads the price of a thousand showings in its third step,
    whether the group is shown, and the advert in its fourth."""
    found = verdict(group(impressions=40_000, link_clicks=100, leads=0))

    assert {"low_ctr", "high_cpm"} <= set(found.signals)
    assert found.cause == "costly_audience"


def test_dear_to_show_with_ordinary_clicks_is_the_audience() -> None:
    placements = (
        SegmentFigures(
            segment="instagram|reels", spend_minor=200_000, impressions=20_000
        ),
        SegmentFigures(
            segment="facebook|feed", spend_minor=100_000, impressions=20_000
        ),
    )
    found = verdict(
        group(
            impressions=40_000,
            link_clicks=600,
            leads=10,
            slices={"platform_position": placements},
        )
    )

    assert found.cause == "costly_audience"
    assert found.evidence["costly_slice"] == {
        "kind": "platform_position",
        "segment": "instagram|reels",
        "spend_minor": 200_000,
        "spend_share_pct": 67,
        "cpm_minor": 10_000,
    }


def test_the_same_people_seeing_it_again_is_worn_out_not_weak() -> None:
    found = verdict(
        group(
            link_clicks=1_300,
            leads=0,
            early=Half(days=3, impressions=40_000, link_clicks=800),
            late=Half(days=4, impressions=60_000, link_clicks=500),
            week_frequency=220,
        )
    )

    assert found.cause == "worn_out"


def test_a_frequency_under_the_first_bar_is_not_wear() -> None:
    """1,25 times a week is under the 1,70 the morning's levels start at, and
    nobody is tired of anything - the diagnosis and the levels read one bar."""
    found = verdict(
        group(
            link_clicks=1_300,
            leads=0,
            early=Half(days=3, impressions=40_000, link_clicks=800),
            late=Half(days=4, impressions=60_000, link_clicks=500),
            week_frequency=125,
            prior_week_frequency=110,
        )
    )

    assert "worn_out" not in found.signals


def test_a_provider_verdict_that_people_ignore_it_is_the_advert() -> None:
    found = verdict(group(leads=0, ads=(advert(engagement="below_average_10"),)))

    assert found.cause == "weak_creative"
    assert found.signals[0] == "low_ranking"


def test_a_video_that_loses_people_in_three_seconds_is_the_advert() -> None:
    judged = group(leads=0, video_plays=5_000, video_views_3s=2_000)
    beside = steady(video_plays=5_000, video_views_3s=10_000)

    found = verdict(judged, beside)

    assert found.signals[0] == "weak_hook"
    assert found.cause == "weak_creative"


def test_an_image_has_no_opening_to_fail() -> None:
    beside = steady(video_plays=5_000, video_views_3s=10_000)

    found = verdict(group(leads=0), beside)

    assert "weak_hook" not in found.signals


# --- after the click ------------------------------------------------------
def test_engaging_and_judged_low_quality_is_the_promise() -> None:
    found = verdict(group(leads=10, ads=(advert(quality="below_average_35"),)))

    assert found.cause == "promise_mismatch"


def test_clicks_without_leads_is_the_form_or_the_site() -> None:
    found = verdict(group(leads=0))

    assert (found.cause, found.signals) == ("landing_blocks", ("low_click_to_lead",))


def dear_for_no_one_reason(**overrides: Any) -> AdSetFacts:
    """Every step a little worse than the neighbour's and none past its line.

    A thousand showings 1,4 times dearer, three quarters of the clicks and
    six tenths of the leads per click: a lead three times the price, and no
    single figure that says why.
    """
    return group(spend=420_000, link_clicks=1_125, leads=13, **overrides)


def test_nought_arrivals_on_a_page_without_the_pixel_says_nothing() -> None:
    silent = verdict(dear_for_no_one_reason())
    counted = verdict(dear_for_no_one_reason(landing=Landing(pixel_seen=True)))

    assert (silent.cause, counted.cause) == ("unclear", "landing_blocks")
    assert counted.signals == ("low_arrival",)


def test_poor_results_with_nothing_to_point_at_is_unclear() -> None:
    found = verdict(dear_for_no_one_reason())

    assert (found.cause, found.signals) == ("unclear", ())


def test_a_limited_group_says_the_provider_cannot_learn_on_it() -> None:
    found = verdict(dear_for_no_one_reason(learning_limited=True))

    assert (found.cause, found.signals) == ("learning_limited", ("learning_limited",))


def test_a_limited_group_doing_well_is_still_told_it_cannot_learn() -> None:
    assert verdict(group(learning_limited=True)).cause == "learning_limited"


def test_an_unpaid_account_comes_before_everything() -> None:
    account = AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(group(link_clicks=500, leads=0), steady()),
        payment_due=True,
    )

    found = {item.adset_id: item for item in diagnose(account=account, policy=POLICY)}

    assert found["judged"].cause == "unpaid"
    assert found["judged"].signals[0] == "unpaid"
    assert found["steady"].cause == "unpaid"


def test_a_group_waiting_on_an_unpaid_bill_is_diagnosed() -> None:
    """The provider calls the wait "pending"; on an account that owes money
    the bill is what it waits on."""
    waiting = group(delivery="pending")
    owed = AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(waiting, steady()),
        payment_due=True,
    )
    paid = AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(waiting, steady()),
    )

    assert "judged" in {item.adset_id for item in diagnose(account=owed, policy=POLICY)}
    assert "judged" not in {
        item.adset_id for item in diagnose(account=paid, policy=POLICY)
    }


def test_without_a_usual_price_too_few_clicks_is_too_early() -> None:
    """The brief's other bar, where nothing says what a result costs: a
    thousand showings and thirty clicks."""
    found = verdict(group(link_clicks=20, leads=0), group(external_id="other", leads=0))

    assert found.cause == "too_early"
    assert "thin_data" in found.signals


def test_a_long_form_explains_what_was_otherwise_unclear() -> None:
    found = verdict(dear_for_no_one_reason(landing=Landing(form_questions=7)))

    assert found.cause == "landing_blocks"
    assert found.evidence["form_questions"] == 7


# --- goals without leads --------------------------------------------------
def chat(**overrides: Any) -> AdSetFacts:
    """A conversation group: no lead can happen, conversations are counted."""
    return group(counts_leads=False, outcome="chat", leads=0, **overrides)


def test_cheap_conversations_with_few_clicks_name_the_advert() -> None:
    """35 conversations at the usual price, and a click rate well under the
    account's: the advert is the first step that failed."""
    judged = chat(link_clicks=1_120, results=35, spend=875)
    neighbour = chat(
        external_id="steady", name="Bahor", link_clicks=2_500, results=35, spend=875
    )

    found = verdict(judged, neighbour)

    assert (found.cause, found.signals[0]) == ("weak_creative", "low_ctr")
    assert found.evidence["outcome"] == "chat"
    assert (found.evidence["results"], found.evidence["cost_minor"]) == (35, 25)


def test_dear_conversations_are_explained_by_the_advert() -> None:
    judged = chat(link_clicks=600, results=10, spend=900)
    neighbour = chat(
        external_id="steady", name="Bahor", link_clicks=1_630, results=36, spend=900
    )

    found = verdict(judged, neighbour)

    assert (found.cause, found.signals[0]) == ("weak_creative", "low_ctr")
    assert found.evidence["cost_minor"] == 90


def test_a_provider_verdict_on_a_working_group_is_a_cause() -> None:
    """Meta's ranking is one of the brief's advert figures, read in its
    fourth step whatever the price."""
    found = verdict(
        chat(results=40, spend=900, ads=(advert(engagement="below_average_20"),)),
        chat(external_id="steady", name="Bahor", results=40, spend=900),
    )

    assert (found.cause, found.signals) == ("weak_creative", ("low_ranking",))


def test_a_group_whose_result_nothing_counts_is_read_by_its_steps() -> None:
    """A sale on somebody else's website has no price here, so it is never
    called dear - but its advert is still read."""
    weak = verdict(
        group(counts_leads=False, leads=0, ads=(advert(engagement="below_average_20"),))
    )
    fine = verdict(group(counts_leads=False, leads=0))

    assert weak.cause == "weak_creative"
    assert weak.evidence["results"] is None
    assert fine.cause == "no_problem"


def test_a_group_is_only_compared_with_groups_of_its_own_kind() -> None:
    """A group bought for clicks has a rate no lead group reaches, and would
    otherwise make every lead group beside it look weak."""
    clicks_group = steady(
        counts_leads=False, outcome="click", link_clicks=10_000, leads=0
    )

    found = verdict(group(), clicks_group)

    assert "low_ctr" not in found.signals


def test_conversations_are_not_compared_with_visits() -> None:
    """Two goals that both bring no lead are still two goals. A website
    group lives on clicks and would make every chat group look ignored."""
    visits = steady(counts_leads=False, outcome="click", link_clicks=10_000, leads=0)

    found = verdict(chat(results=35), visits)

    assert "low_ctr" not in found.signals


def test_showings_are_priced_by_the_thousand() -> None:
    found = verdict(
        group(counts_leads=False, outcome="view", leads=0, spend=50_000),
        steady(counts_leads=False, outcome="view", leads=0, spend=50_000),
    )

    assert (found.evidence["cost_minor"], found.evidence["account_cost_minor"]) == (
        500,
        500,
    )


# --- the table ------------------------------------------------------------
def test_every_signal_points_at_a_cause_in_funnel_order() -> None:
    assert list(CAUSE_OF) == list(SIGNALS)
    assert {*CAUSE_OF.values(), "no_problem", "unclear"} == set(CAUSES)


# --- delivery ---------------------------------------------------------------
def test_a_group_that_cannot_spend_its_budget_is_not_being_shown() -> None:
    """Checked before the advert: a group shown to a trickle has rates read
    off a trickle. A third of a 100 000 budget over the week, and dear."""
    found = verdict(group(daily_budget_minor=100_000, spend=230_000, leads=5))

    assert found.cause == "not_delivering"
    assert found.evidence["spend_share"] == 33


def test_spending_most_of_the_budget_is_not_under_delivery() -> None:
    found = verdict(group(daily_budget_minor=45_000, spend=300_000))

    assert "underspending" not in found.signals


# --- trends -----------------------------------------------------------------
def test_an_advert_clicked_far_less_than_when_it_was_new_is_tired() -> None:
    """Two percent in its first three days, under one in its last three."""
    tired = group(
        leads=10,
        launch_ctr_bp=200,
        recent=Recent(days=3, totals=Totals(impressions=20_000), link_clicks=150),
    )

    found = verdict(tired)

    assert "fatigued" in found.signals
    assert (found.evidence["launch_ctr_bp"], found.evidence["recent_ctr_bp"]) == (
        200,
        75,
    )


def test_a_price_twice_the_usual_these_three_days_is_a_problem_already() -> None:
    """The week still reads like the account; the last three days do not."""
    climbing = group(
        recent=Recent(
            days=3,
            totals=Totals(
                spend_minor=120_000, impressions=30_000, leads=3, leads_reported=3
            ),
            link_clicks=300,
        )
    )
    account = AccountFacts(
        provider=META,
        currency="USD",
        window_days=7,
        totals=Totals(),
        adsets=(climbing, steady()),
        usual={"lead": Usual(days=14, cost_minor=15_000)},
    )

    [found] = [
        item
        for item in diagnose(account=account, policy=POLICY)
        if item.adset_id == climbing.external_id
    ]

    assert found.evidence["cost_trend_pct"] == 267
    assert found.cause != "no_problem"


# --- numbers nobody can call --------------------------------------------------
def test_a_tenth_of_the_enquiries_with_bad_numbers_is_the_form() -> None:
    """Cheap on paper: thirty enquiries at the usual price, but six of them
    cannot be called back, so the price is not what it looks like."""
    found = verdict(group(junk_leads=6))

    assert found.cause == "landing_blocks"
    assert "junk_numbers" in found.signals


def test_a_few_bad_numbers_are_ordinary() -> None:
    assert "junk_numbers" not in verdict(group(junk_leads=2)).signals
