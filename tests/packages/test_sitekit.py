"""sitekit: whether a page opens, what it carries, and where it will not go.

No network. An ``httpx.MockTransport`` answers every request and a fake
resolver answers every name lookup, so nothing here reaches DNS either.
"""

import ssl
from collections.abc import Callable, Sequence

import httpx
import pytest
from sitekit import (
    MAX_BODY_BYTES,
    MAX_REDIRECTS,
    HostNotFoundError,
    HostUnresolvableError,
    Resolver,
    SiteProbe,
    probe,
)

PUBLIC = "93.184.216.34"
PIXEL = "2113979052803229"
PIXEL_PAGE = f"""<html><head><script>
!function(f,b,e,v,n,t,s){{}}(window,document,'script',
'https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '{PIXEL}');
fbq('track', 'PageView');
</script>
<noscript><img height="1" width="1" style="display:none"
src="https://www.facebook.com/tr?id={PIXEL}&amp;ev=PageView&amp;noscript=1"/></noscript>
</head><body></body></html>"""

type Handler = Callable[[httpx.Request], httpx.Response]


def public(host: str, port: int) -> Sequence[str]:
    return [PUBLIC]


def resolving_to(*addresses: str) -> Resolver:
    def resolve(host: str, port: int) -> Sequence[str]:
        return list(addresses)

    return resolve


def page(
    body: str = "<html></html>", *, status: int = 200, kind: str = "text/html"
) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body, headers={"content-type": kind})

    return handler


def look(
    url: str, handler: Handler, *, resolve: Resolver = public
) -> tuple[SiteProbe, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    http = httpx.Client(transport=httpx.MockTransport(recording))
    return probe(url, http=http, resolve=resolve), seen


def failing(error: Exception, *, cause: BaseException | None = None) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        if cause is not None:
            error.__cause__ = cause
        raise error

    return handler


# --- A page that opens ----------------------------------------------------
def test_a_page_that_opens_names_its_pixel_once() -> None:
    """The base code carries the id twice - the script and the image - and
    it is one pixel."""
    found, _seen = look("https://step12.uz/", page(PIXEL_PAGE))

    assert found.outcome == "ok"
    assert found.status_code == 200
    assert found.meta_pixel_ids == (PIXEL,)
    assert not found.is_down


def test_a_tag_manager_is_reported_beside_an_empty_pixel_list() -> None:
    """A pixel loaded through the tag manager is not in the HTML, so the
    empty list next to it means "cannot tell"."""
    body = '<script src="https://www.googletagmanager.com/gtm.js?id=GTM-X"></script>'

    found, _seen = look("https://shop.uz/", page(body))

    assert found.meta_pixel_ids == ()
    assert found.has_tag_manager


def test_only_the_head_of_a_large_page_is_read() -> None:
    body = "x" * MAX_BODY_BYTES + PIXEL_PAGE

    found, _seen = look("https://shop.uz/", page(body))

    assert found.outcome == "ok"
    assert found.meta_pixel_ids == ()


def test_a_file_that_is_not_a_page_is_not_searched_for_tags() -> None:
    found, _seen = look(
        "https://shop.uz/menu.pdf", page(PIXEL_PAGE, kind="application/pdf")
    )

    assert found.outcome == "ok"
    assert found.meta_pixel_ids == ()


def test_the_request_says_what_it_is() -> None:
    _found, seen = look("https://shop.uz/", page())

    assert "TargetologAI" in seen[0].headers["user-agent"]


# --- Redirects ------------------------------------------------------------
def test_a_redirect_is_followed_to_the_page_it_names() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(301, headers={"location": "/gel"})
        return page(PIXEL_PAGE)(request)

    found, seen = look("https://killerplus.tilda.ws/", handler)

    assert found.outcome == "ok"
    assert found.final_url == "https://killerplus.tilda.ws/gel"
    assert len(seen) == 2


def test_a_redirect_into_the_private_network_is_not_followed() -> None:
    """A public page pointing at an internal one is the reason redirects
    are followed here rather than by the client."""
    handler = failing(AssertionError("unused"))

    def redirecting(request: httpx.Request) -> httpx.Response:
        if request.url.host == "shop.uz":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
        return handler(request)

    found, seen = look("https://shop.uz/", redirecting)

    assert found.outcome == "blocked"
    assert len(seen) == 1


def test_an_endless_redirect_stops() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "/again"})

    found, seen = look("https://shop.uz/", handler)

    assert found.outcome == "too_many_redirects"
    assert len(seen) == MAX_REDIRECTS + 1
    assert not found.is_down


# --- Addresses never dialled ----------------------------------------------
@pytest.mark.parametrize(
    "url",
    [
        "ftp://shop.uz/",
        "http://shop.uz:5432/",
        "http://127.0.0.1/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "not a web address",
    ],
)
def test_an_address_outside_the_public_web_is_refused_unasked(url: str) -> None:
    found, seen = look(url, page())

    assert found.outcome == "blocked"
    assert seen == []


def test_a_name_resolving_to_a_private_address_is_refused_unasked() -> None:
    found, seen = look(
        "https://intranet.shop.uz/", page(), resolve=resolving_to("10.1.2.3")
    )

    assert found.outcome == "blocked"
    assert seen == []


def test_one_private_address_among_public_ones_is_enough_to_refuse() -> None:
    found, seen = look(
        "https://shop.uz/", page(), resolve=resolving_to(PUBLIC, "192.168.1.10")
    )

    assert found.outcome == "blocked"
    assert seen == []


# --- Pages that do not open -----------------------------------------------
def test_a_name_that_does_not_exist_is_down() -> None:
    def missing(host: str, port: int) -> Sequence[str]:
        raise HostNotFoundError(host)

    found, seen = look("https://killerplus.uz/", page(), resolve=missing)

    assert found.outcome == "no_such_host"
    assert found.is_down
    assert seen == []


def test_a_lookup_that_failed_this_time_is_not_down() -> None:
    def flaky(host: str, port: int) -> Sequence[str]:
        raise HostUnresolvableError(host)

    found, _seen = look("https://shop.uz/", page(), resolve=flaky)

    assert found.outcome == "unreachable"
    assert not found.is_down


@pytest.mark.parametrize("status", [404, 410])
def test_a_page_the_site_says_is_gone_is_down(status: int) -> None:
    found, _seen = look("https://shop.uz/old", page(status=status))

    assert found.outcome == "not_found"
    assert found.status_code == status
    assert found.is_down


@pytest.mark.parametrize("status", [403, 429, 500, 503])
def test_a_refusal_a_person_might_get_past_is_not_down(status: int) -> None:
    """Bot protection answers a script with these and opens for a person."""
    found, _seen = look("https://shop.uz/", page(status=status))

    assert found.outcome == "http_error"
    assert not found.is_down


def test_a_refused_connection_is_down() -> None:
    handler = failing(httpx.ConnectError("refused"), cause=ConnectionRefusedError())

    found, _seen = look("https://shop.uz/", handler)

    assert found.outcome == "refused"
    assert found.is_down


def test_a_certificate_problem_is_not_down() -> None:
    """It can be a missing intermediate on this server's side."""
    handler = failing(
        httpx.ConnectError("bad certificate"),
        cause=ssl.SSLCertVerificationError("unable to get local issuer"),
    )

    found, _seen = look("https://shop.uz/", handler)

    assert found.outcome == "tls_error"
    assert not found.is_down


def test_a_slow_page_is_not_down() -> None:
    found, _seen = look("https://shop.uz/", failing(httpx.ReadTimeout("slow")))

    assert found.outcome == "timeout"
    assert not found.is_down


def test_any_other_transport_failure_is_unreachable() -> None:
    found, _seen = look("https://shop.uz/", failing(httpx.RemoteProtocolError("eh")))

    assert found.outcome == "unreachable"
    assert not found.is_down
