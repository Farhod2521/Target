"""Reading what a website's own tag has been sending.

No network: the provider's answer is served through a mock transport. What
is pinned here is the shape of that answer - figures arrive in slices of
time, each holding its own list of event names - and the fact that a
caller only ever wants the sum of those slices.
"""

from typing import Any

import httpx
from metaads.accounts import EVENT_AGGREGATION, pixel_events
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
