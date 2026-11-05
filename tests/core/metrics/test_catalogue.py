"""The metric catalogue: every formula of the base metrics, and every ``–``.

The examples are the ones in ``bazaviy-metrikalar-v3.md``, so a number
here that disagrees with the document is a formula that changed.
"""

from decimal import Decimal

import pytest
from adskit import MinorUnits

from core.metrics.catalogue import (
    BY_KEY,
    CATALOGUE,
    ORDER,
    Figures,
    Setting,
    compute,
    metrics_for,
)

AD = Setting(level="ad")
CAMPAIGN = Setting(level="campaign")


def value(key: str, figures: Figures, setting: Setting = AD) -> object:
    return compute(key, figures, setting).value


def why(key: str, figures: Figures, setting: Setting = AD) -> object:
    return compute(key, figures, setting).missing


# -- the columns ----------------------------------------------------------------------


def test_every_key_in_the_order_is_a_metric_and_none_is_left_out() -> None:
    assert len(ORDER) == len(set(ORDER))
    assert set(ORDER) == set(BY_KEY)
    assert [metric.key for metric in CATALOGUE] == list(ORDER)


def test_a_campaign_and_an_ad_set_show_the_same_columns() -> None:
    campaign = [m.key for m in metrics_for(level="campaign", network="meta")]
    adset = [m.key for m in metrics_for(level="adset", network="meta")]

    assert campaign == adset
    assert "hook_rate" not in campaign
    assert "quality_ranking" not in campaign


def test_an_ad_adds_the_video_rates_and_the_rankings() -> None:
    campaign = {m.key for m in metrics_for(level="campaign", network="meta")}
    ad = {m.key for m in metrics_for(level="ad", network="meta")}

    assert ad - campaign == {
        "hook_rate",
        "hold_rate",
        "quality_ranking",
        "engagement_rate_ranking",
        "conversion_rate_ranking",
    }


def test_another_network_gets_the_common_metrics_and_none_of_metas() -> None:
    google = {m.key for m in metrics_for(level="ad", network="google")}

    assert {"spend", "cpm", "ctr", "cpc", "leads", "cpql"} <= google
    assert not google & {"reach", "frequency", "hook_rate", "quality_ranking"}
    assert why("reach", Figures(reach=10), Setting(level="ad", network="google")) == (
        "not_here"
    )


# -- the document's examples ----------------------------------------------------------


def test_hook_rate() -> None:
    figures = Figures(impressions=10_000, video_plays=3_000, video_views_3s=2_500)

    assert value("hook_rate", figures) == Decimal("25.00")


def test_hold_rate() -> None:
    figures = Figures(video_plays=3_000, video_views_3s=2_500, video_thruplays=500)

    assert value("hold_rate", figures) == Decimal("20.00")


def test_form_conversion_on_an_instant_form_is_over_link_clicks() -> None:
    figures = Figures(link_clicks=200, leads_ours=30, leads_reported=30, impressions=1)

    assert value("form_conversion", figures) == Decimal("15.00")


def test_form_conversion_on_a_website_is_over_page_views() -> None:
    figures = Figures(link_clicks=400, landing_page_views=200, leads_reported=30)
    site = Setting(level="ad", outcome="site_lead")

    assert value("form_conversion", figures, site) == Decimal("15.00")


def test_qualified_share() -> None:
    assert value("qualified_share", Figures(qualified=12, leads_ours=40)) == (
        Decimal("30.00")
    )


def test_cpql() -> None:
    figures = Figures(spend_minor=MinorUnits(6_000), qualified=12)

    assert value("cpql", figures) == 500


def test_cost_per_purchase_on_a_form_goal_is_the_crms_sales() -> None:
    figures = Figures(spend_minor=MinorUnits(6_000), purchases_crm=3, purchases_site=6)

    assert value("cost_per_purchase", figures) == 2_000


def test_cost_per_purchase_on_a_website_goal_is_the_pixels_sales() -> None:
    figures = Figures(spend_minor=MinorUnits(6_000), purchases_crm=3, purchases_site=6)
    site = Setting(level="ad", outcome="site_lead")

    assert value("cost_per_purchase", figures, site) == 1_000


def test_roas_is_sales_value_over_spend() -> None:
    figures = Figures(
        spend_minor=MinorUnits(6_000), purchase_value_site_minor=MinorUnits(18_000)
    )

    assert value("roas", figures) == Decimal("3.00")


# -- the rest of the formulas ---------------------------------------------------------


def test_ctr_and_cpc_count_link_clicks_to_hundredths() -> None:
    figures = Figures(
        spend_minor=MinorUnits(10_000), impressions=6_800, link_clicks=100
    )

    assert value("ctr", figures) == Decimal("1.47")
    assert value("cpc", figures) == 100


def test_cpm() -> None:
    figures = Figures(spend_minor=MinorUnits(5_000), impressions=10_000)

    assert value("cpm", figures) == 500


def test_frequency_is_over_the_ranges_own_reach() -> None:
    assert value("frequency", Figures(impressions=3_000, reach=1_200)) == (
        Decimal("2.50")
    )


def test_cost_per_result_is_per_one_result() -> None:
    figures = Figures(spend_minor=MinorUnits(6_000), results=20)
    chat = Setting(level="campaign", outcome="chat")

    assert value("results", figures, chat) == 20
    assert value("cost_per_result", figures, chat) == 300


def test_cost_per_result_of_a_reach_campaign_is_per_thousand_as_in_ads_manager() -> (
    None
):
    figures = Figures(spend_minor=MinorUnits(5_000), impressions=10_000)
    view = Setting(level="campaign", outcome="view")

    assert value("results", figures, view) == 10_000
    assert value("cost_per_result", figures, view) == 500


def test_leads_are_the_networks_once_it_has_read_the_range() -> None:
    read = Figures(spend_minor=MinorUnits(100), leads_ours=9, leads_reported=10)
    unread = Figures(leads_ours=9)

    assert value("leads", read, CAMPAIGN) == 10
    assert value("leads", unread, CAMPAIGN) == 9
    assert value("leads", Figures(leads_ours=9, read=False), CAMPAIGN) == 9


def test_a_ranking_is_the_networks_word() -> None:
    figures = Figures(impressions=800, quality_ranking="below_average_20")

    assert value("quality_ranking", figures) == "below_average_20"


# -- every reason for a dash ----------------------------------------------------------


def test_a_messaging_campaign_has_no_link_figures() -> None:
    figures = Figures(impressions=1_000, link_clicks=0, unique_link_clicks=0)
    chat = Setting(level="campaign", outcome="chat")

    for key in ("link_clicks", "unique_link_clicks", "ctr", "cpc", "form_conversion"):
        assert why(key, figures, chat) == "no_link", key


def test_an_image_advert_has_no_video_rates() -> None:
    figures = Figures(impressions=1_000)

    assert why("hook_rate", figures) == "not_video"
    assert why("hold_rate", figures) == "not_video"


@pytest.mark.parametrize(
    ("figures", "reason"),
    [
        (Figures(impressions=499, quality_ranking="average"), "few_impressions"),
        (Figures(impressions=900, quality_ranking="unknown"), "few_impressions"),
        (Figures(impressions=900), "not_read"),
    ],
)
def test_a_ranking_without_a_verdict(figures: Figures, reason: str) -> None:
    assert why("quality_ranking", figures) == reason


def test_people_counts_not_read_for_the_range_are_not_summed_days() -> None:
    figures = Figures(impressions=3_000)

    assert why("reach", figures) == "not_asked"
    assert why("frequency", figures) == "not_asked"
    assert why("unique_link_clicks", figures) == "not_asked"


def test_a_cost_says_whether_the_spend_or_the_count_was_missing() -> None:
    assert why("cpql", Figures(qualified=3)) == "no_spend"
    assert why("cpql", Figures(spend_minor=MinorUnits(100))) == "no_base"
    assert why("roas", Figures()) == "no_spend"


def test_a_goal_counted_elsewhere_has_no_result() -> None:
    other = Setting(level="campaign", outcome="none")

    assert why("results", Figures(results=5), other) == "uncounted"
    assert why("cost_per_result", Figures(results=5), other) == "uncounted"
    assert why("form_conversion", Figures(), other) == "other_goal"


def test_an_unread_range_hides_the_networks_figures_and_keeps_ours() -> None:
    figures = Figures(spend_minor=MinorUnits(100), qualified=2, read=False)

    assert why("spend", figures) == "not_read"
    assert why("cpql", figures) == "not_read"
    assert value("qualified", figures) == 2
    assert value("purchases_crm", Figures(purchases_crm=1, read=False)) == 1


def test_a_metric_asked_at_a_level_it_does_not_exist_at() -> None:
    figures = Figures(impressions=10_000, video_views_3s=2_500, video_plays=1)

    assert why("hook_rate", figures, CAMPAIGN) == "not_here"
