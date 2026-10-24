"""Telling Meta how a lead turned out.

The one call in this package that sends Meta something it did not send us
first, and the whole reason a cost per *qualified* lead can act on anything:
a platform optimises towards the event it is told about, and left alone the
only event it can see is a form being submitted.

No network anywhere. What is pinned here is the shape - which is the part
that fails silently, because Meta answers 200 to a batch it does not count.
"""

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest
from adskit import ExternalRef, LeadEventDTO, MinorUnits
from metaads.client import GraphClient
from metaads.conversions import (
    ACTION_SOURCE,
    MAX_EVENTS_PER_CALL,
    STAGE_EVENTS,
    report_leads,
)
from pydantic import ValidationError

WHEN = datetime(2026, 8, 29, 9, 30, tzinfo=UTC)


def lead(number: str = "77") -> ExternalRef:
    return ExternalRef(provider="meta", level="lead", id=number)


def a_verdict(stage: str = "qualified", **extra: Any) -> LeadEventDTO:
    fields: dict[str, Any] = {
        "lead": lead(),
        "stage": stage,
        "occurred_at": WHEN,
        "event_id": f"meta:77:{stage}",
    }
    return LeadEventDTO(**(fields | extra))


def recording(
    received: int = 1,
) -> tuple[GraphClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"events_received": received, "fbtrace_id": "AbC"}
        )

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    ), seen


def exploding() -> GraphClient:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"a dry run reached the network: {request.url}")

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def payload(request: httpx.Request) -> list[dict[str, Any]]:
    body = {key: value[0] for key, value in parse_qs(request.content.decode()).items()}
    return list(json.loads(body["data"]))


# --- Nothing is sent unless it was asked for -----------------------------
def test_a_dry_run_never_reaches_the_network() -> None:
    """The same safety property every other write in this package has, and
    it matters here for a different reason: what this call changes is not an
    object but what a platform optimises somebody's spending towards."""
    receipt = report_leads(
        dataset_id="900", events=[a_verdict()], token="t", client=exploding()
    )

    assert receipt.events_received == 0


def test_an_empty_batch_sends_nothing_and_does_not_raise() -> None:
    """The ordinary result of a sweep that found nothing to do. A caller
    made to branch on it would branch on it in four places."""
    receipt = report_leads(
        dataset_id="900", events=[], token="t", client=exploding(), dry_run=False
    )

    assert receipt.events_received == 0


# --- What Meta is told about the person ----------------------------------
def test_the_lead_is_named_by_metas_own_id_and_nothing_else() -> None:
    """No name, no telephone number, not even a hash of one. The provider
    introduced this person and is only being told how it went."""
    graph, seen = recording()

    report_leads(
        dataset_id="900", events=[a_verdict()], token="t", client=graph, dry_run=False
    )

    event = payload(seen[0])[0]
    assert event["user_data"] == {"lead_id": "77"}


def test_the_event_says_a_system_decided_this() -> None:
    """Not a browser source: nobody did anything. Meta reads a website event
    as one it can ask a click id for, and there is none."""
    graph, seen = recording()

    report_leads(
        dataset_id="900", events=[a_verdict()], token="t", client=graph, dry_run=False
    )

    assert payload(seen[0])[0]["action_source"] == ACTION_SOURCE


def test_each_verdict_goes_out_under_its_own_name() -> None:
    """These strings are a contract with a custom conversion Meta holds.
    Changing one without changing that does not fail - the events keep
    arriving under a name nothing is counting."""
    graph, seen = recording()

    report_leads(
        dataset_id="900",
        events=[a_verdict("qualified"), a_verdict("unqualified")],
        token="t",
        client=graph,
        dry_run=False,
    )

    names = [row["event_name"] for row in payload(seen[0])]
    assert names == [STAGE_EVENTS["qualified"], STAGE_EVENTS["unqualified"]]


def test_the_time_is_when_the_judgement_was_made() -> None:
    """Whole seconds since the epoch, which is the only format this edge
    takes - and the moment somebody answered the telephone, not the moment
    the lead arrived."""
    graph, seen = recording()

    report_leads(
        dataset_id="900", events=[a_verdict()], token="t", client=graph, dry_run=False
    )

    assert payload(seen[0])[0]["event_time"] == int(WHEN.timestamp())


# --- Money, on the one stage that has any --------------------------------
def test_a_sale_carries_its_amount_in_whole_currency() -> None:
    """The one division in the package. Meta reads ``value`` in major units
    here while reading a budget in minor ones two modules away, which is why
    neither is converted anywhere but at the boundary that knows which it is
    looking at."""
    graph, seen = recording()

    report_leads(
        dataset_id="900",
        events=[
            a_verdict("converted", value_minor=MinorUnits(123_456), currency="usd")
        ],
        token="t",
        client=graph,
        dry_run=False,
    )

    assert payload(seen[0])[0]["custom_data"] == {"value": "1234.56", "currency": "USD"}


def test_a_verdict_that_is_not_a_sale_carries_no_amount() -> None:
    """Refused at construction. A provider accepts an amount on any event it
    is offered one with, and the result is an optimiser told that every
    answered telephone was worth nothing."""
    with pytest.raises(ValidationError):
        a_verdict("qualified", value_minor=MinorUnits(1), currency="USD")


def test_an_amount_without_a_currency_is_not_an_amount() -> None:
    with pytest.raises(ValidationError):
        a_verdict("converted", value_minor=MinorUnits(1))


def test_an_event_without_an_idempotency_key_is_refused() -> None:
    """The sweep retries anything unacknowledged. Without a key, a worker
    restart double-counts an account's own reporting."""
    with pytest.raises(ValidationError):
        LeadEventDTO(lead=lead(), stage="qualified", occurred_at=WHEN, event_id="  ")


# --- What comes back -----------------------------------------------------
def test_the_count_is_metas_and_not_the_length_of_the_batch() -> None:
    """They differ whenever a lead has aged past the dataset's window, with
    a 200 and no error - and a caller that trusted its own list would mark
    those reported and never send them again."""
    graph, _ = recording(received=1)

    receipt = report_leads(
        dataset_id="900",
        events=[a_verdict("qualified"), a_verdict("unqualified")],
        token="t",
        client=graph,
        dry_run=False,
    )

    assert receipt.events_received == 1


def test_a_long_list_is_split_here_rather_than_by_the_caller() -> None:
    """A caller splitting it would be a caller that had learned Meta's
    batching rules - the same argument a customer list makes."""
    graph, seen = recording()
    many = [
        a_verdict(event_id=f"meta:{index}:qualified", lead=lead(str(index)))
        for index in range(MAX_EVENTS_PER_CALL + 5)
    ]

    receipt = report_leads(
        dataset_id="900", events=many, token="t", client=graph, dry_run=False
    )

    assert len(seen) == 2
    assert len(payload(seen[0])) == MAX_EVENTS_PER_CALL
    assert len(payload(seen[1])) == 5
    # Summed across the requests rather than read off the last one.
    assert receipt.events_received == 2
