"""Summing a campaign's days into the figures its panel draws.

One rule runs through all of it and every test here is a way of breaking
it: **a count of events may be added across days and a count of people may
not.** Reach and unique clicks are people. Somebody shown the ad on Monday
and again on Tuesday is two rows and one person, so a thirty-day reach
summed out of thirty rows is larger than the truth - and every ratio built
on it, frequency above all, is wrong in the direction that says an ad is
fresher than it is.

The shape enforces it rather than a comment: :class:`PanelTotals` has no
reach field at all, so the sum cannot be written by accident.
"""

from datetime import date

from adskit import MinorUnits

from core.metrics import panel


def a_day(day: int, **figures: int) -> panel.PanelDay:
    return panel.PanelDay(day=date(2026, 8, day), **figures)  # type: ignore[arg-type]


def test_the_totals_never_add_up_a_count_of_people() -> None:
    """Reach is the provider's count for the range or nothing - never a sum."""
    total = panel.panel_total(
        [a_day(1, impressions=100, reach=80), a_day(2, impressions=100, reach=90)]
    )
    assert total.reach == 0
    assert not hasattr(panel.PanelTotals(), "unique_clicks")


def test_events_are_added_across_days() -> None:
    total = panel.panel_total(
        [
            a_day(1, spend_minor=MinorUnits(1000), impressions=100, clicks=4, leads=1),
            a_day(2, spend_minor=MinorUnits(2000), impressions=300, clicks=6, leads=2),
        ]
    )
    assert total.spend_minor == 3000
    assert total.impressions == 400
    assert total.clicks == 10
    assert total.leads == 3


def test_a_cost_with_no_leads_behind_it_is_not_a_cheap_campaign() -> None:
    """Spend and nothing to show for it is the most expensive state there is."""
    total = panel.panel_total([a_day(1, spend_minor=MinorUnits(5000))])
    assert total.cpl_minor is None
    assert total.cpql_minor is None


def test_leads_with_no_spend_yet_do_not_read_as_free() -> None:
    """Leads arrive all day and spend is collected once a night."""
    total = panel.panel_total([a_day(1, leads=4, qualified=2)])
    assert total.cpl_minor is None
    assert total.cpql_minor is None


def test_the_two_costs_divide_by_different_things() -> None:
    total = panel.panel_total(
        [a_day(1, spend_minor=MinorUnits(10_000), leads=10, qualified=4)]
    )
    assert total.cpl_minor == 1_000
    assert total.cpql_minor == 2_500
    assert total.quality_share == 40


def test_a_thousand_showings_is_the_unit_a_cpm_is_quoted_in() -> None:
    total = panel.panel_total(
        [a_day(1, spend_minor=MinorUnits(20_000), impressions=10_000)]
    )
    assert total.cpm_minor == 2_000


def test_a_click_through_rate_below_one_percent_still_has_two_digits() -> None:
    """The whole reason these rates are not built on ``share``.

    Half a percent is an ordinary rate here. Rounded to whole percent it
    is nought, and a panel reporting nought for every campaign it runs is
    one nobody would look at twice.
    """
    total = panel.panel_total([a_day(1, impressions=10_000, clicks=50)])
    assert total.ctr_bp == 50  # 0.50%


def test_the_link_rate_and_the_headline_rate_are_different_questions() -> None:
    """A campaign can look busy on one and send nobody anywhere."""
    total = panel.panel_total([a_day(1, impressions=1_000, clicks=100, link_clicks=5)])
    assert total.ctr_bp == 1_000  # 10.00%
    assert total.link_ctr_bp == 50  # 0.50%


def test_a_rate_over_nothing_is_nought_rather_than_a_crash() -> None:
    assert panel.rate_bp(part=5, whole=0) == 0
    assert panel.panel_total([]).ctr_bp == 0


def test_the_people_figures_come_from_the_newest_day_that_ran() -> None:
    """A paused campaign's trailing zeros are not an audience that vanished."""
    days = [
        a_day(1, impressions=1_000, reach=400),
        a_day(2, impressions=2_000, reach=500, unique_clicks=30),
        a_day(3),
        a_day(4),
    ]
    latest = panel.newest_measured(days)
    assert latest is not None
    assert latest.day == date(2026, 8, 2)
    assert latest.reach == 500
    assert latest.unique_clicks == 30


def test_a_campaign_that_never_ran_has_no_day_to_read_people_from() -> None:
    assert panel.newest_measured([a_day(1), a_day(2)]) is None


def test_frequency_is_impressions_over_the_people_who_saw_them() -> None:
    """``240`` is two and a bit showings each, not two hundred percent."""
    assert panel.frequency_bp(a_day(1, impressions=1_200, reach=500)) == 240


def test_frequency_with_nobody_reached_says_nothing() -> None:
    assert panel.frequency_bp(a_day(1, impressions=1_200)) == 0


def test_a_video_share_is_over_the_people_who_started_it() -> None:
    """Not over impressions: hooking nobody and holding everybody is a
    different problem from the opposite, and one ratio cannot say both."""
    total = panel.panel_total([a_day(1, video_plays=200, video_thruplays=50)])
    assert total.hold_share == 25


def test_a_campaign_with_no_video_reports_no_hold_rather_than_zero_percent() -> None:
    """Guarded at the screen, but the arithmetic must not invent a share."""
    assert panel.panel_total([a_day(1, impressions=500)]).hold_share == 0
