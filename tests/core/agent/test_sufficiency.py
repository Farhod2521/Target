"""The brief's "enough to judge", asked by the night's verdict too.

No database. A group on an account with no usual price yet: before, any
money spent for nothing was "poor" and the card said so while the agent's
own stop and the new group's watch still said "wait". Now all three read
the same bar - 1 000 showings and 30 clicks.
"""

from core.agent import AdSetFacts, Funnel
from core.agent.benchmark import Benchmark, count_in, results_are_poor
from core.agent.sufficiency import enough_spent, enough_to_decide
from core.metrics import Totals


def group(*, impressions: int, link_clicks: int, leads: int = 0) -> AdSetFacts:
    return AdSetFacts(
        external_id="g",
        campaign_external_id="c",
        name="Bahor",
        delivery="active",
        totals=Totals(
            spend_minor=40_000,
            impressions=impressions,
            leads=leads,
            leads_reported=leads,
        ),
        days_with_spend=3,
        counts_leads=True,
        funnel=Funnel(
            spend_minor=40_000, impressions=impressions, link_clicks=link_clicks
        ),
    )


NO_USUAL = Benchmark()


def test_three_results_worth_is_enough_and_a_coin_less_is_not() -> None:
    assert enough_spent(spend_minor=3_000, usual_cost_minor=1_000)
    assert not enough_spent(spend_minor=2_999, usual_cost_minor=1_000)


def test_with_no_usual_price_the_showings_and_clicks_decide() -> None:
    def decide(impressions: int, clicks: int) -> bool:
        return enough_to_decide(
            spend_minor=10**9,
            usual_cost_minor=None,
            impressions=impressions,
            link_clicks=clicks,
        )

    assert decide(1_000, 30)
    assert not decide(999, 30)
    assert not decide(9_000, 29)


def test_the_card_waits_for_the_showings_where_no_price_exists() -> None:
    assert not results_are_poor(
        item=group(impressions=700, link_clicks=12), bench=NO_USUAL
    )
    assert results_are_poor(
        item=group(impressions=1_000, link_clicks=30), bench=NO_USUAL
    )


def test_a_website_lead_is_counted_from_the_provider() -> None:
    """The daily message and the screens count it; the card did not."""
    totals = Totals(spend_minor=10_000, leads_reported=4)

    assert count_in(totals=totals, link_clicks=0, family="site_lead") == 4
