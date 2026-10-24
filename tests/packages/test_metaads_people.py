"""Asking Meta how many people an object reached over a whole range.

Reach and the ad recall estimate count people. Asked per day, Meta counts
somebody who saw the ad on five days five times; asked for the range, it
counts them once - which is the number Ads Manager prints. So the request
must carry the ranges and must not carry ``time_increment``.

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
from metaads.client import GraphClient
from metaads.insights import fetch_people_counts

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")
WEEK = (date(2026, 10, 2), date(2026, 10, 8))
BEFORE = (date(2026, 9, 25), date(2026, 10, 1))

ROW: dict[str, Any] = {
    "date_start": "2026-10-02",
    "date_stop": "2026-10-08",
    "campaign_id": "120210",
    "adset_id": "120211",
    "ad_id": "120212",
    "reach": "26625",
    "estimated_ad_recallers": "4100",
}


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


def read(rows: list[dict], *, level: str = "ad") -> list:
    client, _ = recording({"data": rows})
    with patch("metaads.adapter.GraphClient", return_value=client):
        return MetaMetrics().fetch_people(
            account=ACCOUNT, ranges=[WEEK, BEFORE], level=level, token="t"
        )


class TestTheRequest:
    def test_every_range_travels_in_one_request(self) -> None:
        client, seen = recording({"data": []})

        fetch_people_counts(
            account_id="act_1",
            ranges=[WEEK, BEFORE],
            level="campaign",
            token="t",
            client=client,
        )

        assert len(seen) == 1
        assert json.loads(query_of(seen[0])["time_ranges"][0]) == [
            {"since": "2026-10-02", "until": "2026-10-08"},
            {"since": "2026-09-25", "until": "2026-10-01"},
        ]

    def test_the_range_is_not_split_into_days(self) -> None:
        """With ``time_increment`` Meta counts each day's people again."""
        client, seen = recording({"data": []})

        fetch_people_counts(
            account_id="act_1", ranges=[WEEK], level="ad", token="t", client=client
        )

        query = query_of(seen[0])
        assert "time_increment" not in query
        assert "time_range" not in query
        assert query["level"] == ["ad"]
        assert "estimated_ad_recallers" in query["fields"][0].split(",")
        assert "reach" in query["fields"][0].split(",")


class TestTheAnswer:
    def test_a_row_is_one_object_over_one_range(self) -> None:
        (row,) = read([ROW])

        assert row.ref == ExternalRef(provider="meta", level="ad", id="120212")
        assert (row.since, row.until) == WEEK
        assert row.reach == 26_625
        assert row.recallers == 4_100
        assert row.campaign_external_id == "120210"

    def test_the_level_decides_which_id_is_the_objects_own(self) -> None:
        (row,) = read([ROW], level="campaign")

        assert row.ref.id == "120210"

    def test_a_row_that_does_not_say_its_range_is_dropped(self) -> None:
        assert read([{**ROW, "date_stop": ""}]) == []

    def test_a_level_meta_has_no_figures_for_is_refused(self) -> None:
        with pytest.raises(InvalidRequest):
            MetaMetrics().fetch_people(
                account=ACCOUNT, ranges=[WEEK], level="form", token="t"
            )

    def test_no_ranges_asks_nothing(self) -> None:
        with patch("metaads.adapter.GraphClient") as opened:
            assert (
                MetaMetrics().fetch_people(
                    account=ACCOUNT, ranges=[], level="ad", token="t"
                )
                == []
            )
        opened.assert_not_called()
