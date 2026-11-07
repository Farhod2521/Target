"""Reading what a website's own tag has been sending.

No network: the provider's answer is served through a mock transport. What
is pinned here is the shape of that answer - figures arrive in slices of
time, each holding its own list of event names - and the fact that a
caller only ever wants the sum of those slices.
"""

from typing import Any

import httpx
from metaads.accounts import (
    EVENT_AGGREGATION,
    custom_conversion_count,
    custom_conversions,
    pixel_events,
    stats_since,
)
from metaads.client import GraphClient

PIXEL = "777"


def answering(payload: dict[str, Any]) -> tuple[GraphClient, list[httpx.Request]]:
    """A client that answers every read with one payload, and keeps the asks."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=payload)

    client = GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    return client, seen


def test_the_events_are_summed_across_the_slices_meta_answers_in() -> None:
    """Meta answers per bucket of time. The question is not "when"."""
    client, _ = answering(
        {
            "data": [
                {
                    "aggregation": "event",
                    "data": [
                        {"value": "Lead", "count": 3},
                        {"value": "PageView", "count": 90},
                    ],
                },
                {
                    "aggregation": "event",
                    "data": [{"value": "Lead", "count": 4}],
                },
            ]
        }
    )

    found = pixel_events(pixel_id=PIXEL, token="t", client=client)

    assert [(row.event, row.count) for row in found] == [
        ("PageView", 90),
        ("Lead", 7),
    ]


def test_the_busiest_event_comes_first() -> None:
    client, _ = answering(
        {
            "data": [
                {
                    "data": [
                        {"value": "Contact", "count": 2},
                        {"value": "Schedule", "count": 11},
                    ]
                }
            ]
        }
    )

    found = pixel_events(pixel_id=PIXEL, token="t", client=client)

    assert [row.event for row in found] == ["Schedule", "Contact"]


def test_a_count_that_arrived_as_text_is_still_a_count() -> None:
    """Meta answers in strings here and in numbers elsewhere on the same row."""
    client, _ = answering({"data": [{"data": [{"value": "Purchase", "count": "5"}]}]})

    assert pixel_events(pixel_id=PIXEL, token="t", client=client)[0].count == 5


def test_nothing_readable_is_no_events_rather_than_a_failure() -> None:
    client, _ = answering({"data": [{"data": [{"count": 4}, "nonsense", {}]}]})

    assert pixel_events(pixel_id=PIXEL, token="t", client=client) == []


def test_the_events_are_asked_for_by_name_rather_than_by_url() -> None:
    """Grouped by event; grouping by anything else answers another question."""
    client, seen = answering({"data": []})

    pixel_events(pixel_id=PIXEL, token="t", client=client)

    assert f"{PIXEL}/stats" in str(seen[0].url)
    assert f"aggregation={EVENT_AGGREGATION}" in str(seen[0].url)


def test_the_seven_day_window_is_asked_for_not_left_to_meta() -> None:
    """TZ 3: left out, Meta answers a shorter window than the screens say."""
    client, seen = answering({"data": []})

    pixel_events(pixel_id=PIXEL, token="t", client=client)

    since = int(seen[0].url.params["start_time"])
    assert abs(since - stats_since()) < 60
    assert stats_since(now=8 * 86_400) == 86_400


def test_custom_conversions_carry_the_pixel_they_count_on() -> None:
    client, seen = answering(
        {
            "data": [
                {
                    "id": "55",
                    "name": "Rahmat",
                    "custom_event_type": "LEAD",
                    "pixel": {"id": "777"},
                    "is_archived": False,
                },
                {"id": "56", "name": "Eski", "is_archived": True},
            ]
        }
    )

    found = custom_conversions(account_id="act_1", token="t", client=client)

    assert seen[0].url.path.endswith("/act_1/customconversions")
    assert [(row.id, row.pixel_id, row.is_usable) for row in found] == [
        ("55", "777", True),
        ("56", "", False),
    ]


def test_a_custom_conversions_fires_are_added_up() -> None:
    client, seen = answering(
        {"data": [{"count": 3, "timestamp": "x"}, {"data": [{"count": 4}]}]}
    )

    assert custom_conversion_count(conversion_id="55", token="t", client=client) == 7
    assert seen[0].url.params["aggregation"] == "count"
