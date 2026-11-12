"""The app-wide budget, seen by one process and respected by all of them.

``X-App-Usage`` is one figure for the deployment. The client's own brake
lasts one read, so with several workers the one beside the worker that saw
ninety percent started the next account regardless. The stop is now kept
where every process reads it - and only a sweep's reads meet it: a write,
a launch and what a person pressed for go on.
"""

import json
from collections.abc import Iterator

import httpx
import pytest
from metaads import gate
from metaads.client import GraphClient
from metaads.errors import RateLimitApproaching


class Kept:
    """The store, as a test holds it."""

    def __init__(self) -> None:
        self.percent: float | None = None
        self.seconds = 0

    def stopped(self) -> float | None:
        return self.percent

    def stop(self, percent: float, seconds: int) -> None:
        self.percent, self.seconds = percent, seconds


class Broken:
    def stopped(self) -> float | None:
        raise RuntimeError("store away")

    def stop(self, percent: float, seconds: int) -> None:
        raise RuntimeError("store away")


@pytest.fixture
def kept() -> Iterator[Kept]:
    store = Kept()
    gate.install(store)
    yield store
    gate.install(None)


def a_client(calls: list[httpx.Request], **headers: str) -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, headers=headers, json={"data": []})

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def test_the_apps_budget_nearly_gone_is_written_for_everybody(kept: Kept) -> None:
    usage = json.dumps({"call_count": 91})

    a_client([], **{"X-App-Usage": usage}).get("me")

    assert kept.percent == 91
    assert kept.seconds == gate.STOP_SECONDS


def test_the_apps_share_of_the_insights_capacity_counts_too(kept: Kept) -> None:
    usage = json.dumps({"app_id_util_pct": 86, "acc_id_util_pct": 3})

    a_client([], **{"X-FB-Ads-Insights-Throttle": usage}).get("act_1/insights")

    assert kept.percent == 86


def test_one_accounts_own_budget_stops_nobody_else(kept: Kept) -> None:
    business = json.dumps({"act_1": [{"call_count": 95}]})
    insights = json.dumps({"app_id_util_pct": 4, "acc_id_util_pct": 97})

    a_client([], **{"X-Business-Use-Case-Usage": business}).get("me")
    a_client([], **{"X-FB-Ads-Insights-Throttle": insights}).get("me")

    assert kept.percent is None


def test_a_sweeps_read_waits_and_meta_is_not_asked(kept: Kept) -> None:
    kept.percent = 91
    calls: list[httpx.Request] = []

    with gate.background(), pytest.raises(RateLimitApproaching) as caught:
        a_client(calls).get("act_1/campaigns")

    assert caught.value.percent == 91
    assert calls == []


def test_what_a_person_asked_for_is_not_held(kept: Kept) -> None:
    kept.percent = 91
    calls: list[httpx.Request] = []

    a_client(calls).get("act_1/campaigns")

    assert len(calls) == 1


def test_a_write_is_never_held_even_from_a_sweep(kept: Kept) -> None:
    kept.percent = 91
    calls: list[httpx.Request] = []

    with gate.background():
        a_client(calls).post("act_1/campaigns", name="x")

    assert len(calls) == 1


def test_the_background_ends_with_its_block(kept: Kept) -> None:
    kept.percent = 91
    calls: list[httpx.Request] = []
    with gate.background():
        pass

    a_client(calls).get("me")

    assert len(calls) == 1


def test_a_store_that_cannot_be_reached_stops_nothing() -> None:
    gate.install(Broken())
    calls: list[httpx.Request] = []
    try:
        with gate.background():
            a_client(calls, **{"X-App-Usage": json.dumps({"call_count": 99})}).get("me")
    finally:
        gate.install(None)

    assert len(calls) == 1


def test_without_a_store_nothing_changes() -> None:
    calls: list[httpx.Request] = []

    with gate.background():
        a_client(calls).get("me")

    assert len(calls) == 1
