"""core/metrics/lead_count: the one lead count every surface shows.

The provider's wherever it has read the figures, because that is what Ads
Manager prints and a second number beside it is the one the owner stops
trusting. Ours only before the provider has said anything.
"""

from core.metrics import Totals, counted_leads, heard_leads, measured


def test_the_provider_count_is_shown_wherever_it_has_read_the_figures() -> None:
    """Fewer of ours - a lost webhook - and more of ours - a test lead or a
    lead either side of midnight - both show the provider's count."""
    assert Totals(spend_minor=50_000, leads=3, leads_reported=5).counted_leads == 5
    assert Totals(spend_minor=50_000, leads=7, leads_reported=5).counted_leads == 5


def test_ours_stands_in_only_before_the_provider_has_read_anything() -> None:
    assert Totals(leads=3).counted_leads == 3
    assert counted_leads(ours=3, reported=0, measured=False) == 3


def test_a_measured_day_with_no_provider_lead_is_nought_not_ours() -> None:
    """Spend and impressions with no lead counted is a fact the provider
    stated, and Ads Manager prints nought for it."""
    assert Totals(spend_minor=10_000, impressions=900, leads=2).counted_leads == 0


def test_measured_is_any_figure_from_the_provider() -> None:
    assert not measured(spend_minor=0, impressions=0, reported=0)
    assert measured(spend_minor=0, impressions=1, reported=0)
    assert measured(spend_minor=0, impressions=0, reported=1)


def test_the_stop_and_warn_question_hears_either_side() -> None:
    """Only for "has anything come today": a lead the provider has not
    counted yet must hold off a stop."""
    assert heard_leads(ours=1, reported=0) == 1
    assert heard_leads(ours=0, reported=2) == 2
