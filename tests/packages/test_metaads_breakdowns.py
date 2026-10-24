"""Asking Meta who the money reached, and reading the answer.

The breakdown call is the summary call asked a second question, and almost
everything that can go wrong with it is silent.

**It is a separate request.** Asked for a breakdown, Meta answers the slices
and stops answering the total - so a parser that expected both would find
the total missing and a caller that skipped the second call would find the
slices missing. There is no shape here that says which happened.

**The parts must come back in the order they were asked for.** ``age`` then
``gender`` produces ``("25-34", "female")``; the other way round produces a
value that is still a string, still stores, and never matches the row it was
meant to replace.

**Whatever Meta filed the row under is kept.** A campaign aimed at eighteen
to sixty-five still reports a ``65+`` cell and an ``unknown`` gender, and
both are spend that happened. A parser that dropped them would make the
segments fall short of their own total for a reason nothing could explain.

Nothing here reaches a network: every client is an ``httpx.MockTransport``.
"""

import json
from datetime import date
from typing import Any
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from adskit import ExternalRef
from adskit.errors import InvalidRequest
from metaads.adapter import MetaMetrics
from metaads.breakdowns import BREAKDOWN_FIELDS, fetch_breakdown
from metaads.client import GraphClient
from metaads.insights import ATTRIBUTION_WINDOWS

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")
DAY = date(2026, 8, 1)

CELL: dict[str, Any] = {
    "date_start": "2026-08-01",
    "date_stop": "2026-08-01",
    "account_currency": "USD",
    "campaign_id": "120210",
    "adset_id": "120211",
    "age": "25-34",
    "gender": "female",
    "spend": "12.34",
    "impressions": "4200",
    "reach": "3100",
    "clicks": "180",
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


def query_of(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(request.url)).query)


def one_cell(**changes: Any) -> dict[str, Any]:
    return {**CELL, **changes}


def read(rows: list[dict], *, level: str = "adset", kind: str = "age_gender") -> list:
    """One adapter read against a mocked transport."""
    with patch("metaads.adapter.GraphClient", return_value=answering({"data": rows})):
        return MetaMetrics().fetch_breakdown(
            account=ACCOUNT,
            since=DAY,
            until=DAY,
            level=level,
            kind=kind,
            token="t",
        )


# --- What the request asks for -------------------------------------------
class TestTheRequest:
    def test_the_cut_travels_as_metas_own_breakdown_parameter(self) -> None:
        client, seen = recording({"data": []})

        fetch_breakdown(
            account_id="act_1",
            since=DAY,
            until=DAY,
            level="adset",
            breakdowns=("age", "gender"),
            token="t",
            client=client,
        )

        assert query_of(seen[0])["breakdowns"] == ["age,gender"]

    def test_a_day_is_still_a_day(self) -> None:
        """``time_increment=1``. Without it the whole range is one row and a
        quarter's spend is filed as a single Tuesday."""
        client, seen = recording({"data": []})

        fetch_breakdown(
            account_id="act_1",
            since=DAY,
            until=DAY,
            level="adset",
            breakdowns=("age", "gender"),
            token="t",
            client=client,
        )

        assert query_of(seen[0])["time_increment"] == ["1"]

    def test_the_attribution_window_is_the_summarys_own(self) -> None:
        """The one thing that would make a segment's leads incomparable with
        the total they are measured against, and it would never look wrong."""
        client, seen = recording({"data": []})

        fetch_breakdown(
            account_id="act_1",
            since=DAY,
            until=DAY,
            level="adset",
            breakdowns=("age", "gender"),
            token="t",
            client=client,
        )

        sent = query_of(seen[0])["action_attribution_windows"][0]
        assert json.loads(sent) == list(ATTRIBUTION_WINDOWS)

    def test_it_asks_for_counts_and_not_for_ratios(self) -> None:
        """Every ratio is arithmetic on a count that is already here, and a
        stored ratio is the figure somebody averages across days."""
        asked = set(BREAKDOWN_FIELDS.split(","))

        assert {"spend", "impressions", "reach", "clicks", "actions"} <= asked
        assert asked.isdisjoint({"ctr", "cpm", "cpc", "frequency"})

    def test_it_does_not_re_ask_for_what_the_summary_row_already_has(self) -> None:
        """Names, rankings and video belong to the object's own row. Asking
        for them per slice multiplies them by twenty-one for nothing."""
        asked = set(BREAKDOWN_FIELDS.split(","))

        assert asked.isdisjoint(
            {
                "adset_name",
                "campaign_name",
                "quality_ranking",
                "video_play_actions",
                "cost_per_action_type",
            }
        )

    def test_the_currency_is_never_left_out(self) -> None:
        """Spend arrives in whole currency and only the account says which."""
        assert "account_currency" in BREAKDOWN_FIELDS


# --- What comes back ------------------------------------------------------
class TestTheAnswer:
    def test_the_slice_comes_back_in_the_order_it_was_asked_for(self) -> None:
        """Age then gender. Reversed, the value still stores and never again
        matches the row it was meant to replace."""
        row = read([one_cell()])[0]

        assert row.segment_parts == ("25-34", "female")

    def test_spend_is_converted_and_the_counts_are_integers(self) -> None:
        """Whole currency in, minor units out. The budget on the same object
        is already minor units and the two are indistinguishable in a
        payload."""
        row = read([one_cell()])[0]

        assert row.spend_minor == 1234
        assert row.currency == "USD"
        assert (row.impressions, row.reach, row.clicks) == (4200, 3100, 180)

    def test_the_lead_count_is_dug_out_of_the_actions_array(self) -> None:
        """There is no lead field here either."""
        assert read([one_cell()])[0].leads_reported == 7

    def test_a_region_row_finds_the_instant_form_under_its_own_name(self) -> None:
        """What Meta answers on the region cut: the off-Meta conversions
        are withheld, ``lead`` goes with them, and the instant form is
        filed under ``onsite_conversion.lead_grouped`` alone. Read as
        nought, every province spent money and produced nothing."""
        region_cell = {
            key: value for key, value in CELL.items() if key not in {"age", "gender"}
        }
        region_cell["region"] = "Tashkent"
        region_cell["actions"] = [
            {"action_type": "link_click", "value": "40"},
            {"action_type": "onsite_conversion.lead_grouped", "value": "5"},
        ]

        assert read([region_cell], kind="region")[0].leads_reported == 5

    def test_a_website_ad_set_s_cell_is_counted_like_its_summary_row(self) -> None:
        """The goal travels on every cut, so a stray form lead filed against
        a website ad set does not stand in for the site's own count here
        either."""
        cell = one_cell() | {
            "optimization_goal": "OFFSITE_CONVERSIONS",
            "actions": [
                {"action_type": "lead", "value": "51"},
                {"action_type": "onsite_conversion.lead_grouped", "value": "1"},
                {"action_type": "offsite_conversion.fb_pixel_lead", "value": "50"},
            ],
        }

        assert read([cell])[0].leads_reported == 51

    def test_the_row_knows_which_object_and_which_day_it_is(self) -> None:
        row = read([one_cell()])[0]

        assert row.ref.id == "120211"
        assert row.ref.level == "adset"
        assert row.day == DAY
        assert row.campaign_external_id == "120210"

    def test_the_cut_is_carried_on_the_row(self) -> None:
        """The writer files rows by cut, and a batch is one cut by
        construction - but the row is what says which."""
        assert read([one_cell()])[0].kind == "age_gender"

    def test_a_row_covering_more_than_a_day_is_refused(self) -> None:
        """The same guard the summary read uses. It cannot happen while
        ``time_increment=1`` is sent, which is exactly why it is checked."""
        assert read([one_cell(date_stop="2026-08-31")]) == []


# --- The slices nobody targeted -------------------------------------------
class TestTheAwkwardCells:
    def test_an_unknown_gender_is_kept_as_the_provider_said_it(self) -> None:
        """Meta's own word for a person it could not classify. Normal, and
        the cell the shortfall between segments and total goes into."""
        row = read([one_cell(gender="unknown")])[0]

        assert row.segment_parts == ("25-34", "unknown")

    def test_the_open_ended_age_bucket_is_kept(self) -> None:
        """An ad set aimed at eighteen to sixty-five still reports ``65+``:
        the bucket has no upper edge. Spend that happened, not an error."""
        row = read([one_cell(age="65+")])[0]

        assert row.segment_parts == ("65+", "female")

    def test_a_bucket_outside_the_targeting_is_still_stored(self) -> None:
        """Nothing here validates a slice against what was targeted. A cell
        this parser dropped would be spend that vanished from its own
        total, which is worse than a cell nobody expected."""
        row = read([one_cell(age="13-17")])[0]

        assert row.segment_parts == ("13-17", "female")

    def test_a_missing_half_arrives_as_an_empty_string(self) -> None:
        """And becomes ``unknown`` where the parts are joined - which is in
        the domain, not here. This package must not know the separator."""
        cell = one_cell()
        del cell["gender"]

        assert read([cell])[0].segment_parts == ("25-34", "")


# --- What is refused ------------------------------------------------------
class TestRefusals:
    def test_a_cut_this_provider_does_not_offer_fails_by_name(self) -> None:
        """A device cut is a real thing to want and is not wired here. It
        says so by name rather than quietly fetching something else.

        The refusal is about the map having no entry, not about which cut
        is missing this week: a cut that gets wired up swaps the name here
        rather than deleting the test.
        """
        with pytest.raises(InvalidRequest, match="device"):
            read([one_cell()], kind="device")

    def test_a_level_with_no_insights_fails_by_name(self) -> None:
        with pytest.raises(InvalidRequest, match="form"):
            read([one_cell()], level="form")


# --- Where the ad appeared ------------------------------------------------
PLACEMENT: dict[str, Any] = {
    "date_start": "2026-08-01",
    "date_stop": "2026-08-01",
    "account_currency": "USD",
    "campaign_id": "120210",
    "adset_id": "120211",
    "publisher_platform": "instagram",
    "platform_position": "story",
    "spend": "12.34",
    "impressions": "4200",
    "reach": "1400",
    "clicks": "180",
    "actions": [{"action_type": "lead", "value": "7"}],
}


def placement(**changes: Any) -> dict[str, Any]:
    return {**PLACEMENT, **changes}


def cut_up(rows: list[dict]) -> list:
    return read(rows, kind="platform_position")


class TestThePlacementCut:
    def test_the_position_never_travels_without_its_platform(self) -> None:
        """Meta refuses the position alone, and it would be the wrong
        question anyway: ``story`` is a placement on two platforms and
        ``feed`` is one on three."""
        client, seen = recording({"data": []})

        fetch_breakdown(
            account_id="act_1",
            since=DAY,
            until=DAY,
            level="adset",
            breakdowns=("publisher_platform", "platform_position"),
            token="t",
            client=client,
        )

        assert query_of(seen[0])["breakdowns"] == [
            "publisher_platform,platform_position"
        ]

    def test_the_platform_comes_first_and_the_position_second(self) -> None:
        """Reversed, the value still stores and never again matches the row
        it was meant to replace."""
        row = cut_up([placement()])[0]

        assert row.segment_parts == ("instagram", "story")
        assert row.kind == "platform_position"

    def test_the_figures_are_read_the_same_way_as_the_age_cut(self) -> None:
        """One parser, two cuts. The slice is the only thing that differs."""
        row = cut_up([placement()])[0]

        assert row.spend_minor == 1234
        assert (row.impressions, row.reach, row.clicks) == (4200, 1400, 180)
        assert row.leads_reported == 7

    def test_metas_own_spelling_is_kept_and_not_the_targetings(self) -> None:
        """The trap this cut carries and the age cut does not. An ad set is
        targeted with ``instagram_positions: [stream]`` and its figures come
        back under ``feed``; Audience Network is targeted as ``classic`` and
        reports as ``an_classic``. Nothing here translates, so a rule written
        against the targeting words will match nothing - which is a thing to
        find out from this test rather than from a rule that never fires."""
        rows = cut_up(
            [
                placement(publisher_platform="instagram", platform_position="feed"),
                placement(
                    publisher_platform="audience_network",
                    platform_position="an_classic",
                ),
            ]
        )

        assert [row.segment_parts for row in rows] == [
            ("instagram", "feed"),
            ("audience_network", "an_classic"),
        ]

    def test_a_placement_outside_the_targeting_is_still_stored(self) -> None:
        """An ad set aimed at four positions can report a fifth: delivery
        moves into adjacent inventory. Dropping it would hide exactly the
        spend somebody would want to know about."""
        row = cut_up([placement(platform_position="facebook_reels_overlay")])[0]

        assert row.segment_parts == ("instagram", "facebook_reels_overlay")

    def test_an_unattributed_position_is_kept_as_the_provider_said_it(self) -> None:
        row = cut_up([placement(platform_position="unknown")])[0]

        assert row.segment_parts == ("instagram", "unknown")

    def test_a_missing_position_arrives_as_an_empty_string(self) -> None:
        """And becomes ``unknown`` where the parts are joined - in the
        domain, not here."""
        cell = placement()
        del cell["platform_position"]

        assert cut_up([cell])[0].segment_parts == ("instagram", "")

    def test_the_longest_pair_meta_sends_still_fits_the_column(self) -> None:
        """Sixty-four characters, and this is what the widest real value
        costs: the longest platform, the separator and the longest position."""
        row = cut_up(
            [
                placement(
                    publisher_platform="audience_network",
                    platform_position="facebook_reels_overlay",
                )
            ]
        )[0]

        assert len("|".join(row.segment_parts)) < 64
