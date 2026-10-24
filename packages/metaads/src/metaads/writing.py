"""The primitives every write in this package is built out of.

Four small things that would otherwise be copied into five modules: how a
nested value is encoded for a form-encoded POST, how a created id is read
back, how a client is opened and closed, and what an id looks like when
nothing was actually created.

The last one is the reason this module is worth reading. ``dry_run`` is
checked one line above the HTTP call rather than in the service that
decided it, because that is the only place a new code path cannot get
past. A flag read by callers protects the callers that remember to read
it; a flag read here protects the ad account.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaAPIError

# Meta's own ids are decimal digits, so a value starting with this can
# never be mistaken for one - which is what lets a rollback refuse to send
# a delete for an object that only ever existed in a dry run.
DRY_RUN_PREFIX: Final = "dryrun-"

# What a create call is not allowed to answer with. An empty id means the
# write was accepted and produced nothing we can ever refer to again, which
# would be recorded as a success and then fail at the next step with no way
# back to the cause.
_NO_ID = "Meta accepted the write without returning an id"

# How much of the unexpected answer travels with the refusal. Long enough
# for a whole small object, short enough not to fill a log line - and the
# bodies this fires on are, by definition, not the big ones.
_BODY_LIMIT: Final = 500

# Keys never repeated back. A create response carries no credential today,
# and "today" is the whole reason to filter rather than to trust: this
# string is written to an audit row a person reads.
_SECRET_KEYS: Final = frozenset({"access_token", "token", "secret", "client_secret"})


def fake_id(kind: str) -> str:
    """A recognisable stand-in for an id Meta would have issued.

    Deterministic rather than random: a dry run is something a test and a
    person both read, and a value that changes every time is one neither
    can assert on.
    """
    return f"{DRY_RUN_PREFIX}{kind}"


def is_dry_run_id(value: str) -> bool:
    """Whether this id names something that was never created."""
    return value.startswith(DRY_RUN_PREFIX)


def encode(value: Any) -> Any:
    """Nested values as JSON, because Graph writes are form-encoded.

    A targeting spec, a story spec and a list of categories all go out as
    fields of an ordinary form post, and Meta reads them as JSON strings.
    Passing the dict itself produces ``"{'geo_locations': ...}"`` - Python's
    repr, with single quotes - which Meta rejects with an error that names
    the field and not the reason.
    """
    if isinstance(value, bool):
        # Before anything else, and never left to str(). A form post turns
        # Python's ``False`` into the string "False", and Meta reads that as
        # a word rather than as a boolean - which is a rejection naming a
        # field that was, as far as the caller can tell, filled in.
        return "true" if value else "false"
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False)
    return value


def id_of(payload: dict[str, Any]) -> str:
    """The id a create call answered with, or a failure saying it did not.

    The answer travels with the failure. Without it this is the one refusal
    in the package that cannot be investigated: there is no Meta error to
    read, no code and no subcode, so the body Meta *did* send is the entire
    evidence - and throwing it away turns a five-minute diagnosis into a
    dead end for a launch that has already created a form nothing can
    delete.
    """
    created = str(payload.get("id", "")).strip()
    if not created:
        raise MetaAPIError(f"{_NO_ID}: {redacted(payload)}")
    return created


def redacted(payload: dict[str, Any]) -> str:
    """One line of what came back, with anything secret-shaped removed."""
    safe = {
        key: ("***" if key.lower() in _SECRET_KEYS else value)
        for key, value in payload.items()
    }
    body = json.dumps(safe, ensure_ascii=False, default=str)
    if len(body) <= _BODY_LIMIT:
        return body
    return f"{body[:_BODY_LIMIT]}... ({len(body)} chars)"


@contextmanager
def graph_client(client: GraphClient | None, token: str) -> Iterator[GraphClient]:
    """One client for one call, closing only what this opened.

    Every write takes an optional client for the same reason every read
    does: a sequence of eight calls that opens eight connections spends
    most of its time in TLS handshakes.

    A borrowed client is rebound to ``token`` rather than trusted to carry
    it. The lead form is created with the page's token and everything else
    with the account's, and a shared connection whose own token quietly won
    would send the wrong one - which Meta reports as a missing permission.
    """
    if client is not None:
        yield client.for_token(token)
        return

    graph = GraphClient(token=token)
    try:
        yield graph
    finally:
        graph.close()


def post_object(
    *,
    path: str,
    data: dict[str, Any],
    token: str,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """One write, with empty fields left out rather than sent empty.

    Meta treats an absent field and an empty one differently on about half
    the endpoints here: an empty ``end_time`` is a validation error where a
    missing one means "runs until stopped". Dropping empties centrally is
    what keeps every caller from having to build its payload conditionally.

    An empty **list** is kept, and that is not an oversight.
    ``special_ad_categories: []`` is how a campaign says none of them apply,
    and Meta reads the field's absence as an error rather than as a no.
    """
    body = {
        key: encode(value) for key, value in data.items() if value not in (None, "", {})
    }
    with graph_client(client, token) as graph:
        return graph.post(path, **body)


def delete_payload(
    *,
    path: str,
    data: dict[str, Any],
    token: str,
    client: GraphClient | None = None,
) -> dict[str, Any]:
    """A delete that carries a body, encoded exactly as a write is.

    :func:`post_object`'s twin, and it exists rather than being folded into
    it because the verb is not a detail: an access log where a removal of
    somebody's personal data appears as a POST is an access log that cannot
    answer the one question an erasure audit asks.

    Same encoding rules, for the same reason - the body is a nested
    document Meta reads as JSON out of a form field, and Python's repr of a
    dict is rejected with an error naming the field rather than the cause.
    """
    body = {
        key: encode(value) for key, value in data.items() if value not in (None, "", {})
    }
    with graph_client(client, token) as graph:
        return graph.delete_body(path, **body)
