"""Reading daily performance off Meta.

Most of this file is about two things that are silent when they go wrong and
expensive when they do.

**Spend is in whole currency.** ``"12.34"`` is twelve dollars and thirty-four
cents, while a budget on the same object is ``"1234"`` minor units - also a
string, also digits, indistinguishable in a payload and a hundredfold apart.

**Leads are inside ``actions``.** There is no lead field. Read the wrong
entry and a working campaign reports zero leads, which is the shape of a
bug nobody notices because the screen looks fine.
"""

from datetime import date
from decimal import Decimal
from typing import Any
from unittest.mock import patch
from urllib.parse import unquote

import httpx
import pytest
from adskit import ExternalRef
from adskit.errors import InvalidRequest
from metaads.adapter import MetaMetrics
from metaads.client import GraphClient
from metaads.insights import (
    ATTRIBUTION_WINDOWS,
    REACTION_ACTIONS,
    SHARE_ACTIONS,
    action_count,
    fetch_action_totals,
    fetch_insights,
    fields_for,
    lead_count,
    single_value,
)

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")

ROW: dict[str, Any] = {
    "date_start": "2026-08-01",
    "date_stop": "2026-08-01",
    "account_currency": "USD",
    "campaign_id": "120210",
    "campaign_name": "Tushlik",
    "adset_id": "120211",
    "adset_name": "Chilonzor",
    "spend": "12.34",
    "impressions": "4200",
    "reach": "3100",
    "clicks": "180",
    "frequency": "1.3548",
    "ctr": "4.2857",
    "cpm": "2.94",
    "cpc": "0.07",
    "actions": [
        {"action_type": "post_engagement", "value": "260"},
        {"action_type": "lead", "value": "7"},
    ],
}


def answering(payload: dict) -> GraphClient:
    return GraphClient(
        token="t",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
        ),
    )


def recording(payload: dict) -> tuple[GraphClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    return (
        GraphClient(
            token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
        seen,
    )


def read(rows: list[dict], *, level: str = "adset") -> list:
    with patch("metaads.adapter.GraphClient", return_value=answering({"data": rows})):
        return MetaMetrics().fetch_daily(
            account=ACCOUNT,
            since=date(2026, 8, 1),
            until=date(2026, 8, 3),
            level=level,
            token="t",
        )


# --- What the provider thinks of the ad ----------------------------------
def test_the_ranking_fields_are_asked_for_at_ad_level_only() -> None:
    """Meta refuses them anywhere else. Asking for them on a campaign
    breakdown is an error, not an empty column."""
    assert "quality_ranking" in fields_for("ad")
    assert "quality_ranking" not in fields_for("adset")
    assert "quality_ranking" not in fields_for("campaign")


def test_the_three_verdicts_reach_the_row() -> None:
    row = read(
        [
            ROW
            | {
                "ad_id": "120212",
                "quality_ranking": "ABOVE_AVERAGE",
                "engagement_rate_ranking": "BELOW_AVERAGE_35",
                "conversion_rate_ranking": "AVERAGE",
            }
        ],
        level="ad",
    )[0]

    assert row.quality_ranking == "above_average"
    assert row.engagement_rate_ranking == "below_average_35"
    assert row.conversion_rate_ranking == "average"


def test_not_enough_impressions_yet_is_an_answer_and_not_a_gap() -> None:
    """The normal state of a new ad. Meta says so in words, and reading it
    as "no data" would hide the difference between an ad it cannot judge
    and one it was never asked about."""
    row = read([ROW | {"ad_id": "1", "quality_ranking": "UNKNOWN"}], level="ad")[0]

    assert row.quality_ranking == "unknown"


def test_a_row_that_carries_no_verdict_carries_an_empty_one() -> None:
    """Every campaign and ad set row. The fields were not asked for, which
    is a different thing from the provider having nothing to say."""
    row = read([ROW])[0]

    assert row.quality_ranking == ""
    assert row.engagement_rate_ranking == ""
    assert row.conversion_rate_ranking == ""


def test_a_verdict_nobody_has_heard_of_does_not_lose_the_day() -> None:
    """Meta has added a step to this scale before.

    A new value becomes ``unknown`` rather than travelling into a column
    typed as a fixed set - and rather than failing the row, which would
    throw away a day of spend over a word.
    """
    row = read([ROW | {"ad_id": "1", "quality_ranking": "BELOW_AVERAGE_5"}], level="ad")

    assert row[0].quality_ranking == "unknown"


# --- The call ------------------------------------------------------------
def test_one_request_answers_a_whole_range() -> None:
    """``time_increment=1`` makes Meta split its own aggregate. Without it a
    ninety-day backfill is ninety requests against a rate limit shared with
    every lead arriving through the same connection."""
    graph, seen = recording({"data": []})

    fetch_insights(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 10, 29),
        level="adset",
        token="t",
        client=graph,
    )

    assert len(seen) == 1
    assert "time_increment=1" in str(seen[0].url)


def test_the_range_travels_as_a_range_and_not_as_two_loose_dates() -> None:
    """``since`` and ``until`` on their own mean something else to this
    endpoint - a relative window - and mixing the spellings returns a range
    nobody asked for."""
    graph, seen = recording({"data": []})

    fetch_insights(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 3),
        level="adset",
        token="t",
        client=graph,
    )

    url = str(seen[0].url)
    assert "time_range" in url
    assert "2026-08-01" in url


def test_the_currency_is_asked_for_beside_the_money() -> None:
    """The amount is in whole currency and only the account says which one.
    Asking for the figure without it is asking for a number with no unit."""
    graph, seen = recording({"data": []})

    fetch_insights(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 1),
        level="adset",
        token="t",
        client=graph,
    )

    assert "account_currency" in str(seen[0].url)


# --- Money ---------------------------------------------------------------
def test_spend_arrives_in_whole_currency_and_is_stored_in_minor_units() -> None:
    """The hundredfold error. Budgets on the same object are minor units,
    and the two look identical in a payload."""
    assert read([ROW])[0].spend_minor == 1234


def test_a_currency_with_no_subunit_is_not_multiplied_by_a_hundred() -> None:
    """A yen has no sen. Scaling it would report a hundred times the spend
    to somebody whose whole account is denominated in it."""
    row = {**ROW, "account_currency": "JPY", "spend": "1500"}

    assert read([row])[0].spend_minor == 1500


def test_a_fraction_of_a_unit_is_rounded_rather_than_dropped() -> None:
    """A provider reporting a third of a cent is reporting real money, and
    truncating it on every row of a ninety-day range loses spend."""
    assert read([{**ROW, "spend": "0.005"}])[0].spend_minor == 1


def test_the_derived_costs_go_through_the_same_conversion() -> None:
    assert read([ROW])[0].cpm_minor == 294
    assert read([ROW])[0].cpc_minor == 7


# --- Leads ---------------------------------------------------------------
def test_a_lead_is_found_inside_the_action_list() -> None:
    assert read([ROW])[0].leads_reported == 7


def test_the_overlapping_spellings_are_not_added_together() -> None:
    """``lead`` and ``leadgen_grouped`` are the same submission counted
    twice. Adding them doubles a lead count and halves a reported cost."""
    actions = [
        {"action_type": "lead", "value": "7"},
        {"action_type": "leadgen_grouped", "value": "7"},
    ]

    assert lead_count(actions, goal="LEAD_GENERATION") == 7


def test_the_instant_form_wins_over_the_whole_count() -> None:
    """``lead`` adds the website's pixel leads to the form's. A form
    campaign's day read 36 where 26 people filled the form - every price a
    quarter too cheap, and ten leads "missing" that were never form leads.
    The shape is a real v26.0 answer."""
    actions = [
        {"action_type": "lead", "value": "36"},
        {"action_type": "onsite_conversion.lead_grouped", "value": "26"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "10"},
        {"action_type": "onsite_web_lead", "value": "10"},
    ]

    assert lead_count(actions, goal="LEAD_GENERATION") == 26


def test_a_day_nobody_filled_a_form_in_reports_none_rather_than_failing() -> None:
    """The normal answer for a day an ad ran. Not a gap and not an error."""
    assert lead_count(None, goal="") == 0
    assert (
        read([{k: v for k, v in ROW.items() if k != "actions"}])[0].leads_reported == 0
    )


# --- What people did with the post ---------------------------------------
def test_the_social_counts_come_out_of_the_array_already_being_fetched() -> None:
    """Four figures that cost no request at all.

    They arrive inside ``actions`` on a field list that is already asked
    for. The names are Meta's own, and two of them are the sort a
    hard-coded index gets wrong: a share is filed under the bare word
    ``post``, and a save under a namespaced one.
    """
    row = ROW | {
        "actions": [
            {"action_type": "post_engagement", "value": "260"},
            {"action_type": "lead", "value": "7"},
            {"action_type": "post_reaction", "value": "34"},
            {"action_type": "comment", "value": "6"},
            {"action_type": "post", "value": "3"},
            {"action_type": "onsite_conversion.post_save", "value": "2"},
        ]
    }

    metrics = read([row])[0]

    assert (metrics.reactions, metrics.comments) == (34, 6)
    assert (metrics.shares, metrics.saves) == (3, 2)


def test_a_share_is_not_read_off_the_engagement_roll_up() -> None:
    """``post_engagement`` counts every one of these together. Reading it
    for any single figure would report the total four times over."""
    actions = [{"action_type": "post_engagement", "value": "260"}]

    assert action_count(actions, SHARE_ACTIONS) == 0
    assert action_count(actions, REACTION_ACTIONS) == 0


def test_a_day_nobody_reacted_reports_nought_rather_than_failing() -> None:
    """The ordinary answer, and the same one an older row gives: these
    columns did not exist when it was written."""
    assert action_count(None, REACTION_ACTIONS) == 0
    assert read([{k: v for k, v in ROW.items() if k != "actions"}])[0].saves == 0


# --- Shape ---------------------------------------------------------------
def test_the_row_says_where_in_the_hierarchy_it_sits() -> None:
    """Plain ids rather than refs: figures arrive before the mirror has
    necessarily caught up, and a row that cannot be stored until its parent
    exists goes missing on the day somebody adds a campaign."""
    row = read([ROW])[0]

    assert row.ref == ExternalRef(provider="meta", level="adset", id="120211")
    assert row.campaign_external_id == "120210"
    assert row.adset_external_id == "120211"


def test_the_ratios_are_kept_as_the_provider_computed_them() -> None:
    """So a single day can be checked against the provider's own dashboard.
    A period's CTR is still its clicks over its impressions."""
    row = read([ROW])[0]

    assert row.ctr == Decimal("4.2857")
    assert row.frequency == Decimal("1.3548")


def test_the_day_is_taken_from_the_provider_and_not_from_a_clock() -> None:
    assert read([ROW])[0].day == date(2026, 8, 1)


def test_a_row_with_no_day_is_dropped_rather_than_stored_undated() -> None:
    """Meta sends them for days an object did not exist. A row with no date
    cannot be deduplicated, stored or plotted."""
    assert read([{**ROW, "date_start": ""}]) == []


def test_a_level_meta_has_no_breakdown_for_is_refused_by_name() -> None:
    """The domain's levels include a lead form and an interest. Asking this
    endpoint about either returns an error that reads like our bug."""
    with pytest.raises(InvalidRequest) as caught:
        MetaMetrics().fetch_daily(
            account=ACCOUNT,
            since=date(2026, 8, 1),
            until=date(2026, 8, 1),
            level="form",
            token="t",
        )

    assert "form" in str(caught.value)


# --- Which conversions count, and over how long --------------------------
def test_the_attribution_window_is_stated_rather_than_assumed() -> None:
    """A figure whose basis is implicit is a figure nobody can check
    against the provider's own dashboard."""
    client, seen = recording({"data": []})

    fetch_insights(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 3),
        level="adset",
        token="t",
        client=client,
    )

    url = str(seen[0].url)
    assert "action_attribution_windows" in url
    for window in ATTRIBUTION_WINDOWS:
        assert window in url


# --- What the click actually was -----------------------------------------
def test_the_click_breakdown_reaches_the_row() -> None:
    row = read(
        [
            ROW
            | {
                "unique_clicks": "150",
                "inline_link_clicks": "90",
                "unique_inline_link_clicks": "80",
                "outbound_clicks": [{"action_type": "outbound_click", "value": "70"}],
            }
        ]
    )[0]

    assert (row.unique_clicks, row.inline_link_clicks) == (150, 90)
    assert (row.unique_inline_link_clicks, row.outbound_clicks) == (80, 70)


def test_a_row_without_the_click_breakdown_reads_as_zero() -> None:
    """Not every account reports every one of them, and a missing count is
    a count of nothing rather than an answer nobody gave."""
    row = read([ROW])[0]

    assert (row.unique_clicks, row.inline_link_clicks, row.outbound_clicks) == (0, 0, 0)


# --- How far into the video people got -----------------------------------
def test_the_video_figures_reach_the_row() -> None:
    row = read(
        [
            ROW
            | {
                "video_play_actions": [{"action_type": "video_view", "value": "900"}],
                "video_thruplay_watched_actions": [
                    {"action_type": "video_view", "value": "300"}
                ],
                "video_p25_watched_actions": [
                    {"action_type": "video_view", "value": "700"}
                ],
                "video_p100_watched_actions": [
                    {"action_type": "video_view", "value": "120"}
                ],
            }
        ]
    )[0]

    assert (row.video_plays, row.video_thruplays) == (900, 300)
    assert (row.video_p25, row.video_p100) == (700, 120)


def test_an_image_ad_has_no_video_figures_and_that_is_not_a_gap() -> None:
    """Meta omits every one of them rather than sending zeroes."""
    row = read([ROW])[0]

    assert (row.video_plays, row.video_thruplays) == (0, 0)
    assert (row.video_p25, row.video_p50, row.video_p75, row.video_p100) == (0, 0, 0, 0)


def test_a_single_entry_array_is_read_rather_than_summed() -> None:
    """A sum would be right today and would double-count the day Meta adds
    a second row to one of these."""
    assert single_value([{"action_type": "video_view", "value": "42"}]) == 42
    assert single_value([]) == 0
    assert single_value(None) == 0


# --- Past the click, and past the first frame ----------------------------
def test_the_site_arrivals_and_three_second_views_reach_the_row() -> None:
    """Both out of ``actions``, which every response already carries."""
    row = read(
        [
            ROW
            | {
                "actions": [
                    {"action_type": "link_click", "value": "90"},
                    {"action_type": "landing_page_view", "value": "61"},
                    {"action_type": "video_view", "value": "1200"},
                    {"action_type": "lead", "value": "7"},
                ]
            }
        ]
    )[0]

    assert (row.landing_page_views, row.video_views_3s) == (61, 1200)
    assert row.leads_reported == 7


def test_a_three_second_view_is_not_read_off_the_plays() -> None:
    """``video_play_actions`` files its starts under the same ``video_view``
    name. A reader that looked at the wrong array would call every start a
    viewer who stayed."""
    row = read(
        [
            ROW
            | {
                "video_play_actions": [{"action_type": "video_view", "value": "900"}],
                "actions": [{"action_type": "video_view", "value": "400"}],
            }
        ]
    )[0]

    assert (row.video_plays, row.video_views_3s) == (900, 400)


def test_a_site_without_the_tag_reports_no_arrivals_rather_than_failing() -> None:
    assert (read([ROW])[0].landing_page_views, read([ROW])[0].video_views_3s) == (0, 0)


def test_the_action_totals_are_every_entry_meta_sent_for_the_range() -> None:
    """One row for the account and the range, passed through untidied:
    the attribution columns are part of what somebody came to look at."""
    client, seen = recording(
        {
            "data": [
                {
                    "actions": [
                        {"action_type": "lead", "value": "7", "7d_click": "6"},
                        {"action_type": "landing_page_view", "value": "61"},
                    ],
                    "date_start": "2026-08-01",
                    "date_stop": "2026-08-07",
                }
            ]
        }
    )

    totals = fetch_action_totals(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 7),
        token="t",
        client=client,
    )

    assert [entry["action_type"] for entry in totals] == ["lead", "landing_page_view"]
    assert totals[0]["7d_click"] == "6"
    url = unquote(str(seen[0].url))
    assert "level=account" in url
    assert "time_increment" not in url


def test_an_account_that_did_nothing_has_no_totals() -> None:
    client, _ = recording({"data": [{"date_start": "2026-08-01"}]})

    totals = fetch_action_totals(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 7),
        token="t",
        client=client,
    )

    assert totals == []


# --- What a result cost and what it was worth ----------------------------
def test_the_cost_per_lead_is_read_out_of_the_action_array() -> None:
    """Whole currency, like spend - and a hundredfold error if read as
    minor units."""
    row = read(
        [
            ROW
            | {
                "cost_per_action_type": [
                    {"action_type": "post_engagement", "value": "0.05"},
                    {"action_type": "lead", "value": "1.76"},
                ],
                "action_values": [{"action_type": "lead", "value": "20.00"}],
            }
        ]
    )[0]

    assert row.cost_per_lead_minor == 176
    assert row.lead_value_minor == 2_000


def test_the_overlapping_lead_spellings_are_not_added_here_either() -> None:
    """The same trap as the lead count, in two more arrays: one submission
    filed under two names is one submission."""
    row = read(
        [
            ROW
            | {
                "cost_per_action_type": [
                    {"action_type": "lead", "value": "1.00"},
                    {"action_type": "leadgen_grouped", "value": "1.00"},
                ]
            }
        ]
    )[0]

    assert row.cost_per_lead_minor == 100


def test_a_campaign_that_reports_no_value_reads_as_zero() -> None:
    """Most lead campaigns. A value exists only if the advertiser sends one
    back, and the revenue this product reasons about arrives elsewhere."""
    row = read([ROW])[0]

    assert row.lead_value_minor == 0
    assert row.cost_per_lead_minor == 0


# --- What the object was called on the day -------------------------------
def test_the_name_of_the_day_is_kept() -> None:
    """The mirror holds what a thing is called now and has no row at all
    for one that was deleted. This is what keeps a ninety-day report from
    listing spend against a bare id."""
    assert read([ROW])[0].object_name == "Chilonzor"
    assert (
        read([ROW | {"ad_id": "1", "ad_name": "Video A"}], level="ad")[0].object_name
        == "Video A"
    )


# --- date_stop, which is a guarantee rather than a column ----------------
def test_a_row_covering_more_than_a_day_is_refused() -> None:
    """It cannot happen while ``time_increment=1`` is sent, which is why it
    is worth checking: the day that stops being true, every row would carry
    a whole range and the table would take a quarter's spend as one
    Tuesday."""
    assert read([ROW | {"date_stop": "2026-08-31"}]) == []


def test_a_row_that_says_only_its_start_is_still_stored() -> None:
    """Absent is not disagreement."""
    row = dict(ROW)
    del row["date_stop"]

    assert len(read([row])) == 1


# --- A lead on the owner's own website -----------------------------------
# One day of an ad set optimising for a pixel lead, in the shape v26.0
# answers it: the pixel's own name for the event beside the link clicks and
# landing page views it came through.
SITE_LEAD_ROW = ROW | {
    "actions": [
        {"action_type": "link_click", "value": "72"},
        {"action_type": "landing_page_view", "value": "6"},
        {"action_type": "omni_landing_page_view", "value": "6"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"},
        {"action_type": "page_engagement", "value": "80"},
    ]
}


def test_a_pixel_lead_is_the_providers_lead_count() -> None:
    """The one count a website-lead campaign has: nothing reaches this
    product by webhook, so the screens read this column for it."""
    assert read([SITE_LEAD_ROW])[0].leads_reported == 4


def test_a_pixel_lead_beside_a_form_lead_is_not_added_to_it() -> None:
    """Where the row has no form name, ``lead`` is its whole count and the
    pixel's name is a fallback for a row without it, never added on top."""
    actions = [
        {"action_type": "lead", "value": "7"},
        {"action_type": "offsite_conversion.fb_pixel_lead", "value": "4"},
    ]

    assert lead_count(actions, goal="") == 7


# A website ad set's day as Meta answered it in v26.0: 1,175 people filled
# the site's form, and one instant-form lead was filed against it as well.
STRAY_FORM_ACTIONS = [
    {"action_type": "lead", "value": "1176"},
    {"action_type": "onsite_conversion.lead_grouped", "value": "1"},
    {"action_type": "offsite_conversion.fb_pixel_lead", "value": "1175"},
]


def test_a_website_ad_set_is_not_read_off_a_stray_form_lead() -> None:
    """Read form-first, this day said 1 lead and the month added up to a
    figure that matched neither of Ads Manager's columns. The goal decides,
    once per ad set, and ``lead`` is Ads Manager's "Leads" column."""
    assert lead_count(STRAY_FORM_ACTIONS, goal="OFFSITE_CONVERSIONS") == 1176


def test_a_row_without_a_goal_still_reads_the_instant_form_first() -> None:
    """A campaign's row says "Unknown Optimization Goal" - and an older
    answer, or a cut, may carry none at all."""
    assert lead_count(STRAY_FORM_ACTIONS, goal="Unknown Optimization Goal") == 1
    assert lead_count(STRAY_FORM_ACTIONS, goal=None) == 1


def test_the_goal_on_the_row_decides_what_the_adapter_counts() -> None:
    """The adapter reads the goal off the same row: the count, its cost and
    its value all come from the same name."""
    row = ROW | {
        "optimization_goal": "OFFSITE_CONVERSIONS",
        "actions": STRAY_FORM_ACTIONS,
        "cost_per_action_type": [
            {"action_type": "lead", "value": "0.05"},
            {"action_type": "onsite_conversion.lead_grouped", "value": "60.00"},
        ],
    }

    [read_row] = read([row])

    assert read_row.leads_reported == 1176
    assert read_row.cost_per_lead_minor == 5


# --- Profile visits --------------------------------------------------------
def test_a_profile_visit_is_read_off_meta_s_results_field() -> None:
    """Under no action type - read off live ad sets, only ``results``
    carries it, under one of two indicators."""
    rows = read(
        [
            ROW
            | {
                "results": [
                    {"indicator": "profile_visit_view", "values": [{"value": "1479"}]}
                ]
            },
            ROW
            | {
                "date_start": "2026-08-02",
                "date_stop": "2026-08-02",
                "results": [
                    {"indicator": "total_profile_visits", "values": [{"value": "7"}]}
                ],
            },
        ]
    )

    assert [row.profile_visits for row in rows] == [1479, 7]


def test_another_goal_s_result_is_not_a_profile_visit() -> None:
    rows = read(
        [ROW | {"results": [{"indicator": "actions:lead", "values": [{"value": "7"}]}]}]
    )

    assert rows[0].profile_visits == 0


def test_the_results_field_rides_on_the_one_request() -> None:
    graph, seen = recording({"data": []})

    fetch_insights(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 1),
        level="adset",
        token="t",
        client=graph,
    )

    assert len(seen) == 1
    assert "results" in unquote(str(seen[0].url))


def test_a_refused_results_field_does_not_cost_the_day() -> None:
    """Meta refusing one field must not take spend and leads down with it:
    asked once more without it."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if "results" in unquote(str(request.url)):
            return httpx.Response(
                400,
                json={"error": {"message": "Invalid parameter", "code": 100}},
            )
        return httpx.Response(200, json={"data": [ROW]})

    graph = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )

    rows = fetch_insights(
        account_id="act_1",
        since=date(2026, 8, 1),
        until=date(2026, 8, 1),
        level="adset",
        token="t",
        client=graph,
    )

    assert len(seen) == 2
    assert rows[0]["spend"] == "12.34"


# --- Ads Manager's own results column --------------------------------------
CALL_ROW: dict[str, Any] = ROW | {
    "actions": [
        {
            "action_type": "onsite_conversion.messaging_conversation_started_7d",
            "value": "9",
        },
        {"action_type": "click_to_call_native_call_placed", "value": "4"},
    ]
}


def test_a_call_ad_set_whose_viewers_also_wrote_is_counted_in_calls() -> None:
    """Meta's results column names the goal; the first match in the action
    list would have taken the conversations."""
    rows = read(
        [
            CALL_ROW
            | {
                "results": [
                    {
                        "indicator": "actions:click_to_call_native_call_placed",
                        "values": [{"value": "4"}],
                    }
                ]
            }
        ]
    )

    assert rows[0].results_reported == 4


def test_without_the_results_field_a_placed_call_is_still_found() -> None:
    row = ROW | {
        "actions": [{"action_type": "click_to_call_native_call_placed", "value": "4"}]
    }

    assert read([row])[0].results_reported == 4


def test_a_count_of_people_is_not_taken_as_a_result() -> None:
    """Reach does not add across days; the action list answers instead."""
    rows = read(
        [CALL_ROW | {"results": [{"indicator": "reach", "values": [{"value": "900"}]}]}]
    )

    assert rows[0].results_reported == 9


def test_a_link_click_ad_set_s_result_is_its_link_clicks() -> None:
    rows = read(
        [
            ROW
            | {
                "results": [
                    {"indicator": "actions:link_click", "values": [{"value": "31"}]}
                ]
            }
        ]
    )

    assert rows[0].results_reported == 31


# --- Which of the results values is the figure ------------------------------
# Meta's answer for one live ad set on 2026-10-14, as it came back: one value
# per window asked for, and the ad set's own setting labelled ``default``.
WINDOWED_RESULTS = [
    {
        "indicator": "actions:onsite_conversion.messaging_conversation_started_7d",
        "values": [
            {"value": "5", "attribution_windows": ["7d_click"]},
            {"value": "7", "attribution_windows": ["1d_view"]},
            {"value": "12", "attribution_windows": ["default"]},
        ],
    }
]


def test_the_result_is_the_default_window_not_the_first() -> None:
    """Ads Manager said twelve conversations; read as the first value, this
    product said five - every view-through result missing."""
    rows = read([ROW | {"results": WINDOWED_RESULTS}])

    assert rows[0].results_reported == 12


def test_a_result_without_window_labels_is_read_as_it_is() -> None:
    indicator = "actions:onsite_conversion.total_messaging_connection"
    results = [{"indicator": indicator, "values": [{"value": "9"}]}]

    rows = read([ROW | {"results": results}])

    assert rows[0].results_reported == 9


def test_without_a_default_value_the_actions_total_answers() -> None:
    """Every value labelled and none the ad set's own: none of them is the
    figure, and ``actions`` carries it in its plain ``value``."""
    results = [
        {
            "indicator": "actions:onsite_conversion.messaging_conversation_started_7d",
            "values": [
                {"value": "5", "attribution_windows": ["7d_click"]},
                {"value": "7", "attribution_windows": ["1d_view"]},
            ],
        }
    ]
    actions = [
        {
            "action_type": "onsite_conversion.messaging_conversation_started_7d",
            "value": "12",
            "7d_click": "5",
            "1d_view": "7",
        }
    ]

    rows = read([ROW | {"results": results, "actions": actions}])

    assert rows[0].results_reported == 12


def test_profile_visits_take_the_default_window_too() -> None:
    results = [
        {
            "indicator": "profile_visit_view",
            "values": [
                {"value": "40", "attribution_windows": ["7d_click"]},
                {"value": "55", "attribution_windows": ["default"]},
            ],
        }
    ]

    assert read([ROW | {"results": results}])[0].profile_visits == 55
