"""What a creative did with the attention it was given.

Ratios, and the rule that governs all of them: **none is additive**. A
week's link CTR is its link clicks over its impressions, never the mean of
its days, which is why every function here takes counts rather than a list
of them.

No Django, no database, no provider.
"""

from adskit import MinorUnits

from core.metrics import (
    EngagementFigures,
    click_quality,
    completion_rate,
    frequency,
    hold_rate,
    hook_rate,
    link_ctr,
    unique_ctr,
    value_per_spend,
)


def test_the_honest_ctr_counts_only_the_clicks_that_went_somewhere() -> None:
    """The headline CTR counts caption taps and profile opens too, so an ad
    can look busy on it while sending nobody anywhere."""
    figures = EngagementFigures(impressions=1_000, clicks=100, inline_link_clicks=30)

    assert link_ctr(figures) == 3


def test_click_quality_shows_a_crowd_of_one() -> None:
    """A hundred means everybody clicked once. Low means a handful of
    people kept tapping, which wears the budget down invisibly."""
    assert click_quality(EngagementFigures(clicks=100, unique_clicks=100)) == 100
    assert click_quality(EngagementFigures(clicks=100, unique_clicks=20)) == 20


def test_unique_ctr_is_people_over_people() -> None:
    figures = EngagementFigures(reach=800, unique_clicks=200)

    assert unique_ctr(figures) == 25


def test_the_video_ratios_read_the_shape_of_the_drop_off() -> None:
    """An ad that loses everybody at the start has a different problem from
    one that loses them at the end, and one ratio cannot say which."""
    figures = EngagementFigures(
        impressions=10_000, video_plays=2_000, video_thruplays=500, video_p100=200
    )

    assert hook_rate(figures) == 20
    assert hold_rate(figures) == 25
    assert completion_rate(figures) == 10


def test_an_image_ad_scores_zero_rather_than_failing() -> None:
    """Every video count is absent on one, which is the ordinary case."""
    figures = EngagementFigures(impressions=10_000, clicks=50)

    assert hook_rate(figures) == 0
    assert hold_rate(figures) == 0
    assert completion_rate(figures) == 0


def test_a_day_with_no_impressions_divides_to_zero() -> None:
    assert link_ctr(EngagementFigures()) == 0
    assert unique_ctr(EngagementFigures()) == 0
    assert click_quality(EngagementFigures()) == 0


def test_value_against_spend_is_a_ratio_and_not_a_percentage_of_itself() -> None:
    """``250`` means the provider valued the leads at two and a half times
    what they cost."""
    figures = EngagementFigures(
        spend_minor=MinorUnits(10_000), lead_value_minor=MinorUnits(25_000)
    )

    assert value_per_spend(figures) == 250


def test_a_return_on_nothing_spent_is_not_infinite() -> None:
    """It is a question nobody asked, so it is answered with nothing rather
    than with a number somebody would put on a screen."""
    assert value_per_spend(EngagementFigures(lead_value_minor=MinorUnits(500))) is None


def test_most_lead_campaigns_report_no_value_at_all() -> None:
    """Not a bug. A value exists only if the advertiser sends one back, and
    the revenue this product reasons about is a sale somebody marks."""
    assert value_per_spend(EngagementFigures(spend_minor=MinorUnits(10_000))) == 0


# --- How often the same person saw it -------------------------------------
def test_frequency_is_impressions_over_the_people_who_saw_them() -> None:
    """In hundredths, like everything else here: 240 is two and a bit
    showings each. It passes a hundred as soon as anybody sees the ad twice,
    which is normal and is the point of it."""
    assert frequency(EngagementFigures(impressions=4_800, reach=2_000)) == 240
    assert frequency(EngagementFigures(impressions=2_000, reach=2_000)) == 100


def test_frequency_is_never_asked_for_because_both_halves_are_collected() -> None:
    """The rule the whole breakdown request rests on - counts are asked for
    and ratios are not - written as arithmetic so that a provider's own copy
    could be checked against it rather than trusted instead of it."""
    figures = EngagementFigures(impressions=7_000, reach=2_500)

    assert frequency(figures) == round(figures.impressions / figures.reach * 100)


def test_a_placement_nobody_has_seen_yet_divides_to_zero() -> None:
    """A slice with no reach is a slice with no delivery, not a division by
    zero and not a frequency of one."""
    assert frequency(EngagementFigures(impressions=0, reach=0)) == 0


def test_the_same_ad_set_carries_different_frequencies_per_placement() -> None:
    """Why the figure is worth deriving at all. A story is shown to the same
    person several times as often as a feed is, and the gap is the earliest
    sign of a creative wearing out in one placement and not the other."""
    feed = EngagementFigures(impressions=3_000, reach=2_400)
    story = EngagementFigures(impressions=6_000, reach=2_000)

    assert frequency(feed) == 125
    assert frequency(story) == 300
