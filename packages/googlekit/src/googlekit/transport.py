"""The one place this package opens a socket, and how its failures read.

**Sent or not sent.** A failure before the request reached Google is
always safe to retry and is :class:`Unavailable`. Any failure after that
point - a read timeout, a connection dropped mid-answer - is
:class:`OutcomeUnknown`, because the write may have landed and only its
receipt was lost. That split is the reason this module exists rather than
each half catching ``httpx.TimeoutException`` for itself, which is where
the difference disappears.

**No retry loop.** Same rule as the other packages: the caller knows
whether a second attempt is safe, and for a write this package does not.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

import httpx

from googlekit.errors import GoogleAPIError, OutcomeUnknown, Unavailable, translate

CONNECT_TIMEOUT_SECONDS: Final = 5.0
# Long enough for a batch of rows to land. A write is the slowest call
# here and the one whose timeout costs most, since that timeout is what
# becomes an unknown outcome.
READ_TIMEOUT_SECONDS: Final = 30.0

# Failures that happen before a byte of the request reaches Google.
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
    """One request, with its failure translated into something to catch.

    The exception names the httpx class and nothing more. Its own message
    can carry the URL, and while no URL here holds a credential, a
    spreadsheet id is still one customer's address and a log is not where
    it belongs.
    """
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
    """The body as a dict. Empty is a normal answer; HTML is somebody else's.

    A body that is not JSON came from something between us and Google - a
    proxy, a load balancer's error page. Temporary unless the status says
    the request itself was refused.
    """
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
