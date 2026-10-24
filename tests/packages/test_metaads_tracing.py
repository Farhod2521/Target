"""The optional watcher, and the two promises that make it safe to add.

It must not change what the package does when nobody is watching, and it
must not hand out the token. Both are asserted here rather than trusted,
because the failure mode of the second is a credential in a file somebody
later attaches to a support ticket.
"""

from typing import Any

import httpx
import pytest
from metaads import tracing
from metaads.client import GraphClient
from metaads.errors import MetaAPIError


def collecting() -> tuple[list[dict[str, Any]], Any]:
    seen: list[dict[str, Any]] = []

    def watcher(**call: Any) -> None:
        seen.append(call)

    return seen, watcher


def client_returning(response: httpx.Response) -> GraphClient:
    return GraphClient(
        token="EAAG-a-real-looking-token",
        client=httpx.Client(transport=httpx.MockTransport(lambda _r: response)),
    )


def test_nobody_watching_costs_nothing() -> None:
    """The default. No watcher is set, and the call behaves exactly as it
    does in a build that never had this module."""
    assert tracing.current() is None

    graph = client_returning(httpx.Response(200, json={"id": "9"}))

    assert graph.get("9") == {"id": "9"}


def test_a_watcher_sees_both_directions() -> None:
    seen, watcher = collecting()
    graph = client_returning(httpx.Response(200, json={"id": "9"}))

    with tracing.watching(watcher):
        graph.post("act_1/ads", name="Reklama")

    assert len(seen) == 1
    assert seen[0]["method"] == "POST"
    assert seen[0]["body"]["name"] == "Reklama"
    assert seen[0]["response"] == {"id": "9"}
    assert seen[0]["status"] == 200


def test_the_token_never_reaches_the_watcher() -> None:
    """The whole reason the package redacts rather than the caller: it is
    the package that put the parameter there."""
    seen, watcher = collecting()
    graph = client_returning(httpx.Response(200, json={"id": "9"}))

    with tracing.watching(watcher):
        graph.get("me")

    assert seen[0]["query"]["access_token"] == tracing.MASK
    assert "EAAG-a-real-looking-token" not in str(seen)


def test_a_paging_cursor_is_stripped_of_its_query() -> None:
    """A cursor is absolute and carries the token inside it, so the URL
    itself is a secret."""
    seen, watcher = collecting()
    graph = GraphClient(
        token="EAAG-secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(200, json={"data": []})
            )
        ),
    )

    with tracing.watching(watcher):
        graph._request(
            "GET", "https://graph.facebook.com/v26.0/x?access_token=EAAG-secret"
        )

    assert seen[0]["url"] == "https://graph.facebook.com/v26.0/x"
    assert "EAAG-secret" not in str(seen)


def test_a_refusal_is_watched_as_closely_as_a_success() -> None:
    """The call worth reading is almost never the one that worked."""
    seen, watcher = collecting()
    graph = client_returning(
        httpx.Response(400, json={"error": {"message": "no", "code": 100}})
    )

    with tracing.watching(watcher), pytest.raises(MetaAPIError):
        graph.post("act_1/ads", name="x")

    assert seen[0]["status"] == 400
    assert seen[0]["response"]["error"]["code"] == 100


def test_a_watcher_that_breaks_does_not_break_the_call() -> None:
    """A tracer that fails the thing it observes turns a diagnostic into an
    outage, and the launches worth tracing are already fragile."""

    def exploding(**_call: Any) -> None:
        raise RuntimeError("tracer is broken")

    graph = client_returning(httpx.Response(200, json={"id": "9"}))

    with tracing.watching(exploding):
        assert graph.get("9") == {"id": "9"}


def test_watching_ends_when_the_block_does() -> None:
    seen, watcher = collecting()
    graph = client_returning(httpx.Response(200, json={"id": "9"}))

    with tracing.watching(watcher):
        graph.get("9")
    graph.get("9")

    assert len(seen) == 1


def test_secrets_are_masked_by_key_and_not_by_shape() -> None:
    """A token is recognisable by the field it sits in. A matcher hunting
    for a prefix fails the first time Meta changes the format."""
    scrubbed = tracing.scrubbed(
        {"access_token": "anything", "page_token": "x", "name": "Kafe"}
    )

    assert scrubbed == {
        "access_token": tracing.MASK,
        "page_token": tracing.MASK,
        "name": "Kafe",
    }
