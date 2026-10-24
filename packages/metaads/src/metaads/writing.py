"""The primitives every write in this package is built out of."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaAPIError

DRY_RUN_PREFIX: Final = "dryrun-"

_NO_ID = "Meta accepted the write without returning an id"

_BODY_LIMIT: Final = 500

_SECRET_KEYS: Final = frozenset({"access_token", "token", "secret", "client_secret"})


def fake_id(kind: str) -> str:
    """A recognisable stand-in for an id Meta would have issued."""
    return f"{DRY_RUN_PREFIX}{kind}"


def is_dry_run_id(value: str) -> bool:
    """Whether this id names something that was never created."""
    return value.startswith(DRY_RUN_PREFIX)


def encode(value: Any) -> Any:
    """Nested values as JSON, because Graph writes are form-encoded."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, dict | list | tuple):
        return json.dumps(value, ensure_ascii=False)
    return value


def id_of(payload: dict[str, Any]) -> str:
    """The id a create call answered with, or a failure saying it did not."""
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
    """One client for one call, closing only what this opened."""
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
    """One write, with empty fields left out rather than sent empty."""
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
    """A delete that carries a body, encoded exactly as a write is."""
    body = {
        key: encode(value) for key, value in data.items() if value not in (None, "", {})
    }
    with graph_client(client, token) as graph:
        return graph.delete_body(path, **body)
