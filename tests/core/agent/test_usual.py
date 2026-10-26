"""core/agent/usual: what a pair usually does, and what it is used for.

The usual level is the median day of the pair's last fortnight. It prices a
group that has no other group of its kind beside it - the one shape the
peer comparison could say nothing about.
"""

from dataclasses import replace

from adskit import ProviderName

from core.agent import AccountFacts, AdSetFacts, Policy, scan
from core.agent.benchmark import Benchmark
from core.agent.funnel import Funnel
from core.agent.rules import WASTING
from core.agent.usual import MIN_USUAL_DAYS, DayFigures, Usual, usual_level
from core.metrics import Totals

POLICY = Policy()


def day(spend: int, results: int, **extra: int) -> DayFigures:
    return DayFigures(spend_minor=spend, impressions=10_000, results=results, **extra)


def test_the_usual_price_is_the_middle_day_not_the_total() -> None:
    """One day of a broken form moves a fortnight's total, not its middle."""
    days = [day(10_000, 2)] * 6 + [day(90_000, 1)]

    assert usual_level(days).cost_minor == 5_000


def test_a_day_with_no_result_counts_as_the_dearest() -> None:
    """Left out, a fortnight of mostly empty days would read as cheap."""
    days = [day(10_000, 2)] * 2 + [day(10_000, 0)] * 3

    # The middle day brought nothing, so the fortnight is pooled instead.
    assert usual_level(days).cost_minor == 50_000 // 4


def test_too_few_days_have_no_usual_level() -> None:
    days = [day(10_000, 2)] * (MIN_USUAL_DAYS - 1)

    assert usual_level(days) == Usual(days=MIN_USUAL_DAYS - 1)


def test_days_that_spent_nothing_are_not_days() -> None:
    days = [day(10_000, 2)] * MIN_USUAL_DAYS + [day(0, 0)] * 9

    assert usual_level(days).days == MIN_USUAL_DAYS


def test_each_step_has_its_own_middle() -> None:
    days = [
        DayFigures(
            spend_minor=20_000,
            impressions=10_000,
            link_clicks=100,
            results=4,
            video_impressions=10_000,
            video_views_3s=2_500,
        )
    ] * MIN_USUAL_DAYS

    usual = usual_level(days)

    assert usual.link_ctr_bp == 100
    assert usual.cpm_minor == 2_000
    assert usual.hook_bp == 2_500


# --- what it is for ---------------------------------------------------------
def lone(**figures: int) -> AccountFacts:
    """A pair with one lead group, which has no other group to be priced by."""
    item = AdSetFacts(
        external_id="g-1",
        campaign_external_id="c-1",
        name="Yagona",
        delivery="active",
        totals=Totals(**figures),
        days_with_spend=7,
        daily_budget_minor=20_000,
        counts_leads=True,
        is_ours=True,
    )
    return AccountFacts(
        provider=ProviderName("meta"),
        currency="USD",
        window_days=7,
        totals=item.totals,
        lead_totals=item.totals,
        adsets=(item,),
    )


def test_a_lone_group_burning_money_is_priced_by_its_own_fortnight() -> None:
    """With nothing beside it the group used to be unpriced, and no stop was
    ever proposed on the account that most needed one."""
    burning = lone(spend_minor=140_000, impressions=50_000)

    assert [f.rule for f in scan(account=burning, policy=POLICY)] == []

    with_history = replace(burning, usual={"lead": Usual(days=14, cost_minor=10_000)})

    assert WASTING in [f.rule for f in scan(account=with_history, policy=POLICY)]


# --- one "odatda" -----------------------------------------------------------
def test_the_fortnight_is_the_usual_price_even_beside_other_groups() -> None:
    """Every card, report and message quotes one "odatda": the pair's own
    fortnight. The other groups' price only where it has no middle day."""
    priced = Benchmark(
        funnel=Funnel(spend_minor=100_000, impressions=10_000),
        results=10,
        usual_cost_minor=8_000,
    )
    assert priced.cost_minor == 8_000
    assert replace(priced, usual_cost_minor=None).cost_minor == 10_000


def test_no_fortnight_and_no_other_group_is_no_usual_price() -> None:
    assert Benchmark().cost_minor is None


def test_every_rate_is_read_against_the_fortnight_first() -> None:
    """Clicks, a thousand showings and the opening are each read against the
    pair's fourteen-day median, the same reference the price is."""
    other = Benchmark(
        funnel=Funnel(spend_minor=100_000, impressions=50_000, link_clicks=500),
        video_impressions=10_000,
        video_views_3s=3_000,
    )
    fortnight = replace(
        other, usual_link_ctr_bp=80, usual_cpm_minor=1_500, usual_hook_bp=2_200
    )

    assert (other.link_ctr_bp, other.cpm_minor, other.hook_bp) == (100, 2_000, 3_000)
    assert (fortnight.link_ctr_bp, fortnight.cpm_minor, fortnight.hook_bp) == (
        80,
        1_500,
        2_200,
    )
