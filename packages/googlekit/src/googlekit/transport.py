"""The one place this package opens a socket, and how its failures read."""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

import httpx

from googlekit.errors import GoogleAPIError, OutcomeUnknown, Unavailable, translate

CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 30.0

_NOT_SENT: Final = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def new_client() -> httpx.Client:
    """A client with this package's timeouts, for callers that lend none."""
    return httpx.Client(
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_SECONDS,
            read=READ_TIMEOUT_SECONDS,
            write=READ_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        )
    )


@contextmanager
def session(http: httpx.Client | None) -> Iterator[httpx.Client]:
    """The caller's client if one was lent, otherwise ours, closed after."""
    if http is not None:
        yield http
        return
    owned = new_client()
    try:
        yield owned
    finally:
        owned.close()


def call(
    http: httpx.Client,
    method: str,
    url: str,
    *,
    token: str = "",
    json: Mapping[str, Any] | None = None,
    form: Mapping[str, str] | None = None,
    params: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One request, with its failure translated into something to catch."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        response = http.request(
            method, url, json=json, data=form, params=params, headers=headers
        )
    except _NOT_SENT as exc:
        raise Unavailable(f"could not reach Google: {type(exc).__name__}") from exc
    except httpx.TransportError as exc:
        raise OutcomeUnknown(f"Google did not answer: {type(exc).__name__}") from exc

    body = _decode(response)
    if response.status_code >= 400:
        raise translate(status=response.status_code, payload=body)
    return body


def _decode(response: httpx.Response) -> dict[str, Any]:
    """The body as a dict. Empty is a normal answer; HTML is somebody else's."""
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        message = (
            f"Google answered with something other than JSON ({response.status_code})"
        )
        if 400 <= response.status_code < 500:
            raise GoogleAPIError(message) from None
        raise Unavailable(message) from None
    return payload if isinstance(payload, dict) else {}


__all__ = [
    "CONNECT_TIMEOUT_SECONDS",
    "READ_TIMEOUT_SECONDS",
    "call",
    "new_client",
    "session",
]
