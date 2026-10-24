"""The arithmetic behind the numbers screen.

No database, no provider, no clock - which is the point: what a cost per
qualified lead *is* can be checked without a migration or a fixture, and
these are the figures somebody moves a budget on.

Two rules run through every test here. A rate with nothing to divide by is
``None`` and never zero, because zero reads as free. And a rate over a range
is recomputed from that range's sums, never averaged across its days.
"""

from datetime import date, timedelta

from adskit import MinorUnits

from core.metrics import DayFigures, daily_rate, funnel, movement, total


def day(
    offset: int = 0,
    *,
    spend: int = 0,
    impressions: int = 0,
    clicks: int = 0,
    link_clicks: int = 0,
    leads: int = 0,
    qualified: int = 0,
    reported: int = 0,
) -> DayFigures:
    return DayFigures(
        day=date(2026, 8, 1) + timedelta(days=offset),
        spend_minor=MinorUnits(spend),
        impressions=impressions,
        clicks=clicks,
        link_clicks=link_clicks,
        leads=leads,
        qualified=qualified,
        leads_reported=reported,
    )


# --- The two costs -------------------------------------------------------
def test_the_cost_of_a_usable_lead_is_the_figure_the_product_exists_for() -> None:
    """No ad platform can compute this: it needs a verdict only the
    advertiser has. The gap between it and the cost below is the claim."""
    figures = total([day(spend=100_000, leads=10, qualified=4)])

    assert figures.cpql_minor == 25_000
    assert figures.cpl_minor == 10_000


def test_spend_with_no_leads_has_no_cost_per_lead_rather_than_a_free_one() -> None:
    """Zero is a number somebody reads as free, and a range that spent
    money and produced nothing is the most expensive state there is."""
    figures = total([day(spend=100_000)])

    assert figures.cpl_minor is None
    assert figures.cpql_minor is None


def test_leads_with_no_spend_have_no_cost_per_lead_either() -> None:
    """The other half of the same guard.

    A cabinet whose leads arrive from an ad account its figures do not
    come from reads exactly like this: hundreds of leads, nothing spent.
    Dividing them gives nought, and nought here is not "free" - it is the
    most flattering number the screen can show, arrived at by measuring
    two things that have nothing to do with each other.

    The same shape occurs harmlessly every morning, before the nightly
    sync has brought the day's spend, and it must not be reported then
    either.
    """
    figures = total([day(leads=531, qualified=100)])

    assert figures.cpl_minor is None
    assert figures.cpql_minor is None


def test_a_day_with_leads_and_no_spend_is_not_plotted_as_free() -> None:
    """The chart and the headline have to refuse the same days, or the
    line disagrees with the number above it."""
    days = [day(0, spend=100_000, leads=10), day(1, leads=531)]

    assert daily_rate(days) == [10_000, None]


def test_leads_nobody_marked_leave_the_qualified_cost_unanswered() -> None:
    """Not the same as leads that were marked and found useless. The screen
    has to be able to tell somebody the figure is waiting on them."""
    figures = total([day(spend=100_000, leads=10)])

    assert figures.cpl_minor == 10_000
    assert figures.cpql_minor is None


def test_a_rate_over_a_range_is_recomputed_and_not_averaged() -> None:
    """The mistake worth a test of its own.

    Two days: one spent 90 000 for nine leads, the other 10 000 for one.
    Both cost 10 000 a lead, so an average agrees by luck. Change the second
    day and the average drifts from the truth - which is what a month of
    quiet days does to a month with one good week in it.
    """
    days = [day(0, spend=90_000, leads=9), day(1, spend=10_000, leads=1)]

    assert total(days).cpl_minor == 10_000

    lopsided = [day(0, spend=90_000, leads=1), day(1, spend=10_000, leads=9)]
    # The mean of the two daily rates would be 45 500. The month's actual
    # cost per lead is a tenth of that.
    assert total(lopsided).cpl_minor == 10_000


def test_the_quality_share_is_over_every_lead_and_not_over_the_marked_ones() -> None:
    """A share computed only over marked leads climbs whenever somebody
    marks a good one and stalls when they stop looking, which makes it a
    measure of their attention rather than of the campaign."""
    figures = total([day(leads=10, qualified=2)])

    assert figures.quality_share == 20


def test_reach_is_not_summed_anywhere() -> None:
    """It counts people. Two ad sets that showed the same person an ad both
    report that person, so a total is an overcount the provider would never
    print - and the only safe total is one asked for."""
    assert not hasattr(total([day()]), "reach")


# --- Movement ------------------------------------------------------------
def test_a_falling_cost_is_good_news_and_a_falling_lead_count_is_not() -> None:
    """A screen that colours every arrow the same way teaches people to
    ignore it."""
    cheaper = movement(now=800, before=1000, lower_is_better=True)
    fewer = movement(now=8, before=10, lower_is_better=False)

    assert cheaper.direction == fewer.direction == "down"
    assert cheaper.is_good
    assert not fewer.is_good


def test_a_first_period_compares_against_nothing_rather_than_improving() -> None:
    """An account that started last week did not improve infinitely."""
    assert movement(now=500, before=0, lower_is_better=True).direction == "flat"


def test_a_missing_figure_on_either_side_is_flat() -> None:
    """A cost per lead is ``None`` when there were no leads, and inventing
    an improvement out of a week nobody bought anything in is how a budget
    gets raised for the wrong reason."""
    assert movement(now=None, before=1000, lower_is_better=True).direction == "flat"
    assert movement(now=1000, before=None, lower_is_better=True).direction == "flat"


def test_the_percentage_is_reported_without_its_sign() -> None:
    """The arrow carries the direction; a minus beside it would say it
    twice and once wrongly."""
    assert movement(now=800, before=1000, lower_is_better=True).percent == 20


# --- The funnel ----------------------------------------------------------
def test_each_step_is_a_share_of_the_one_above_it() -> None:
    """Against the top, every later step is a rounding error and the chart
    answers a question nobody has."""
    figures = total(
        [
            day(
                impressions=10_000,
                clicks=900,
                link_clicks=500,
                leads=50,
                qualified=10,
            )
        ]
    )

    assert funnel(figures) == (
        ("shown", 10_000, None),
        ("clicked", 500, 5),
        ("submitted", 50, 10),
        # A fourth rung stood here - ``("qualified", 10, 20)`` - and it is
        # withdrawn with the marking that filled it. See the note in
        # :func:`core.metrics.derive.funnel`.
    )


def test_the_clicked_step_counts_only_the_clicks_that_went_somewhere() -> None:
    """The one place this funnel could be wrong without anybody noticing.

    ``clicks`` counts expanding the caption and opening the page's profile.
    Counted as a step, it inflates the second rung and deflates the third -
    so a healthy creative reads as a form nobody will fill in, which is the
    opposite of what to go and fix.
    """
    figures = total([day(impressions=1000, clicks=900, link_clicks=100, leads=50)])

    _shown, clicked, submitted = funnel(figures)

    assert clicked[1] == 100
    # Half of the people who actually arrived, not one in eighteen taps.
    assert submitted[2] == 50


def test_a_funnel_with_nothing_in_it_has_no_shares_rather_than_zero_ones() -> None:
    """A brand new account opens this screen before anything has run.

    Nought percent is a claim - "everybody who saw it left" - and there is
    nothing here to make it about. Absent is the honest answer and the
    screen draws no bar for it.
    """
    assert funnel(total([])) == (
        ("shown", 0, None),
        ("clicked", 0, None),
        ("submitted", 0, None),
    )


def test_a_step_below_one_the_provider_never_counted_has_no_share() -> None:
    """Link clicks can be absent on a range that plainly had clicks.

    That is the provider saying nothing rather than saying nought, and a
    share computed from it would read as a total collapse at that rung.
    """
    figures = total([day(impressions=1000, clicks=400, link_clicks=0, leads=7)])

    _shown, _clicked, submitted = funnel(figures)

    assert submitted[2] is None


def test_the_funnel_names_carry_no_language() -> None:
    """Three languages read these. A step called "Bosildi" here is a step
    the Russian screen cannot rename."""
    for name, _value, _pct in funnel(total([day()])):
        assert name.isascii()


# --- The plotted line ----------------------------------------------------
def test_a_day_with_no_leads_plots_as_nothing_rather_than_as_free() -> None:
    """Zero draws the line to the floor as though the day were free;
    ``None`` lets the chart say the day had no answer."""
    days = [day(0, spend=50_000, leads=5, qualified=5), day(1, spend=50_000)]

    assert daily_rate(days, field="qualified") == [10_000, None]


def test_the_plotted_cost_follows_the_series_that_was_asked_for() -> None:
    days = [day(0, spend=100_000, leads=10, qualified=2)]

    assert daily_rate(days, field="qualified") == [50_000]
    assert daily_rate(days) == [10_000]
