"""The expert dashboard's funnel, ranking and troubled adverts."""

from decimal import Decimal

from adskit import MinorUnits

from core.metrics.catalogue import Figures, Setting
from core.metrics.catalogue.board import funnel, ranked, troubles

CAMPAIGN = Setting(level="campaign")
AD = Setting(level="ad")


def test_the_funnel_shares_are_each_step_over_the_one_above() -> None:
    figures = Figures(
        spend_minor=MinorUnits(100),
        impressions=10_000,
        link_clicks=200,
        leads_ours=30,
        leads_reported=30,
        qualified=9,
        purchases_crm=3,
    )

    steps = funnel(figures, CAMPAIGN)

    assert [step.count.value for step in steps] == [10_000, 200, 30, 9, 3]
    assert steps[0].rate is None
    assert [step.rate.value for step in steps[1:]] == [  # type: ignore[union-attr]
        Decimal("2.00"),
        Decimal("15.00"),
        Decimal("30.00"),
        Decimal("33.33"),
    ]


def test_without_a_crm_the_funnel_stops_at_the_lead() -> None:
    figures = Figures(impressions=100, link_clicks=10, leads_ours=2, crm=False)

    steps = funnel(figures, CAMPAIGN)

    assert steps[3].count.missing == "no_crm"
    assert steps[4].count.missing == "no_crm"
    assert steps[4].rate.missing == "no_crm"  # type: ignore[union-attr]


def _row(spend: int, leads: int) -> Figures:
    return Figures(
        spend_minor=MinorUnits(spend), leads_ours=leads, leads_reported=leads
    )


def test_campaigns_are_ranked_against_their_goals_average() -> None:
    rows = [
        ("cheap", _row(500, 10), CAMPAIGN),
        ("dear", _row(3_000, 10), CAMPAIGN),
        ("few", _row(100, 2), CAMPAIGN),
        ("barren", _row(2_000, 0), CAMPAIGN),
    ]
    goal = Figures(spend_minor=MinorUnits(5_600), leads_ours=22, leads_reported=22)

    best, worst = ranked(rows, totals={"lead": goal})

    assert [(r.id, r.index) for r in best] == [("cheap", 20)]
    assert [(r.id, r.index) for r in worst] == [("barren", None), ("dear", 118)]


def test_an_advert_past_its_norms_says_which_ones() -> None:
    figures = Figures(
        impressions=10_000,
        reach=2_500,
        video_plays=2_000,
        video_views_3s=1_500,
        video_thruplays=100,
        quality_ranking="below_average_10",
        engagement_rate_ranking="average",
    )

    found = {trouble.key for trouble in troubles(figures, AD)}

    assert found == {"hook_rate", "hold_rate", "frequency", "quality_ranking"}


def test_too_few_impressions_is_not_a_trouble() -> None:
    assert troubles(Figures(impressions=400, video_plays=1), AD) == ()
