"""One look at a web page: does it open, and what does it carry."""

import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Final

import httpx

from sitekit.guard import (
    AddressBlockedError,
    HostNotFoundError,
    HostUnresolvableError,
    Resolver,
    check_address,
    system_resolver,
)
from sitekit.models import Outcome, SiteProbe
from sitekit.tags import has_tag_manager, meta_pixel_ids

CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 10.0
MAX_REDIRECTS: Final = 5
MAX_BODY_BYTES: Final = 512_000
USER_AGENT: Final = "Mozilla/5.0 (compatible; TargetologAI-SiteCheck/0.1)"

_GONE: Final = frozenset({404, 410})
_REDIRECTS: Final = frozenset({301, 302, 303, 307, 308})
_CHAIN_DEPTH: Final = 10


def probe(
    url: str,
    *,
    http: httpx.Client | None = None,
    resolve: Resolver | None = None,
    user_agent: str = USER_AGENT,
) -> SiteProbe:
    """Open ``url`` once, following redirects, and say what happened."""
    lookup = resolve or system_resolver
    with _session(http) as client:
        return _follow(client, url=url, resolve=lookup, user_agent=user_agent)


def _follow(
    client: httpx.Client, *, url: str, resolve: Resolver, user_agent: str
) -> SiteProbe:
    try:
        current = httpx.URL(url)
    except httpx.InvalidURL:
        return SiteProbe(url=url, outcome="blocked")

    headers = {"User-Agent": user_agent, "Accept": "text/html,*/*;q=0.5"}
    for _hop in range(MAX_REDIRECTS + 1):
        try:
            check_address(current, resolve=resolve)
        except AddressBlockedError:
            return _probe(url, current, "blocked")
        except HostNotFoundError:
            return _probe(url, current, "no_such_host")
        except HostUnresolvableError:
            return _probe(url, current, "unreachable")

        try:
            with client.stream("GET", current, headers=headers) as response:
                location = response.headers.get("location")
                if response.status_code in _REDIRECTS and location:
                    current = current.join(location)
                    continue
                return _answered(url=url, final=current, response=response)
        except httpx.TimeoutException:
            return _probe(url, current, "timeout")
        except httpx.ConnectError as exc:
            return _probe(url, current, _refusal(exc))
        except httpx.HTTPError:
            return _probe(url, current, "unreachable")

    return _probe(url, current, "too_many_redirects")


def _answered(*, url: str, final: httpx.URL, response: httpx.Response) -> SiteProbe:
    status = response.status_code
    outcome: Outcome = "ok"
    if status in _GONE:
        outcome = "not_found"
    elif status >= 400:
        outcome = "http_error"

    html = _head_of(response) if outcome == "ok" and _is_html(response) else ""
    return SiteProbe(
        url=url,
        final_url=str(final),
        outcome=outcome,
        status_code=status,
        meta_pixel_ids=meta_pixel_ids(html),
        has_tag_manager=has_tag_manager(html),
    )


def _head_of(response: httpx.Response) -> str:
    """The first ``MAX_BODY_BYTES`` of the page, as text."""
    chunks: list[bytes] = []
    size = 0
    try:
        for chunk in response.iter_bytes():
            chunks.append(chunk)
            size += len(chunk)
            if size >= MAX_BODY_BYTES:
                break
    except httpx.HTTPError:
        pass
    raw = b"".join(chunks)[:MAX_BODY_BYTES]
    try:
        return raw.decode(response.encoding or "utf-8", errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


def _is_html(response: httpx.Response) -> bool:
    kind = response.headers.get("content-type", "")
    return not kind or "html" in kind.lower()


def _refusal(exc: httpx.ConnectError) -> Outcome:
    """Which kind of failed connection this was, from the socket's own error."""
    current: BaseException | None = exc
    for _depth in range(_CHAIN_DEPTH):
        if current is None:
            break
        if isinstance(current, ssl.SSLError):
            return "tls_error"
        if isinstance(current, ConnectionRefusedError):
            return "refused"
        current = current.__cause__ or current.__context__
    return "unreachable"


def _probe(url: str, final: httpx.URL, outcome: Outcome) -> SiteProbe:
    return SiteProbe(url=url, final_url=str(final), outcome=outcome)


@contextmanager
def _session(http: httpx.Client | None) -> Iterator[httpx.Client]:
    """The caller's client if one was lent, otherwise ours, closed after."""
    if http is not None:
        yield http
        return
    owned = httpx.Client(
        timeout=httpx.Timeout(
            connect=CONNECT_TIMEOUT_SECONDS,
            read=READ_TIMEOUT_SECONDS,
            write=READ_TIMEOUT_SECONDS,
            pool=CONNECT_TIMEOUT_SECONDS,
        ),
        follow_redirects=False,
        trust_env=False,
    )
    try:
        yield owned
    finally:
        owned.close()
