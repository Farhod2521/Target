"""Reading a preview, and the two things Meta's markup does not say.

The payloads here are the exact shape Meta's own reference publishes,
including the HTML-escaped ampersand - which is the whole reason this file
exists. A parse that looks right and drops the signing token fails in
somebody else's browser, where nothing this project owns can see it.
"""

import httpx
import pytest
from adskit import ExternalRef
from adskit.errors import NotFound
from metaads.adapter import MetaCampaigns
from metaads.client import GraphClient
from metaads.errors import MetaAPIError
from metaads.previews import frame_of, get_preview

# Meta's own documented answer, ampersand and all. The address is
# truncated; the escaping is not.
BODY = (
    '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php'
    "?d=AQKuwYcWpyFgVKLORPWQi52_uTud4v8PpMoDtyBfntL65i0iFtgki"
    '&amp;t=AQJws9t-TtIGrKoFtCM" width="274" height="213" '
    'scrolling="yes" style="border: none;"></iframe>'
)

PAYLOAD = {"data": [{"body": BODY}]}


def graph_returning(payload: dict, capture: list[httpx.Request] | None = None):
    """A GraphClient answering every request with one recorded body."""

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(200, json=payload)

    return GraphClient(
        token="t", client=httpx.Client(transport=httpx.MockTransport(handler))
    )


# --- The trap Meta does not document -------------------------------------
def test_the_escaped_ampersand_is_undone_so_the_token_survives() -> None:
    """``&amp;t=`` leaves the signing token inside the previous value.

    Meta then refuses the frame with "The parameter t is required", in the
    visitor's browser, where no log here can see it. This is the single
    assertion this module exists for.
    """
    frame = frame_of(BODY)

    assert "&amp;" not in frame.src
    assert frame.src.endswith("&t=AQJws9t-TtIGrKoFtCM")


def test_the_size_meta_suggests_is_kept() -> None:
    """Not to render at, but because an aspect ratio cannot be guessed."""
    frame = frame_of(BODY)

    assert (frame.width, frame.height) == (274, 213)


def test_a_frame_without_a_size_is_not_a_failure() -> None:
    """Nought means "Meta did not say", which is a shape a caller handles."""
    frame = frame_of(
        '<iframe src="https://www.facebook.com/ads/api/preview_iframe.php?d=x">'
        "</iframe>"
    )

    assert (frame.width, frame.height) == (0, 0)


# --- Where the address is allowed to point -------------------------------
@pytest.mark.parametrize(
    "src",
    [
        "https://evil.example.com/ads/api/preview_iframe.php?d=x",
        "http://www.facebook.com/ads/api/preview_iframe.php?d=x",
        "https://www.facebook.com/somewhere/else?d=x",
        "javascript:alert(1)",
        "//www.facebook.com/ads/api/preview_iframe.php?d=x",
        "https://evil-facebook.com/ads/api/preview_iframe.php?d=x",
        "https://business.facebook.com.attacker.net/ads/api/preview_iframe.php",
    ],
)
def test_an_address_that_is_not_metas_preview_host_is_refused(src: str) -> None:
    """This value goes into an iframe. The host check is the whole guard.

    ``javascript:`` and the scheme-relative form are in the list on
    purpose: both parse with an empty or borrowed netloc, so a check
    written as "not somebody else's domain" would let them through.
    """
    with pytest.raises(MetaAPIError):
        frame_of(f'<iframe src="{src}"></iframe>')


def test_the_business_host_is_accepted_because_meta_actually_sends_it() -> None:
    """The half of the allowlist that cost a feature.

    Meta's own reference shows ``www.facebook.com``. A live account
    answered every preview with ``business.facebook.com`` instead, and
    with one host in the set the parse refused all of them - silently,
    because the caller logs a refusal and carries on. Pinned here so the
    second host cannot be tidied away as a duplicate of the first.
    """
    frame = frame_of(
        '<iframe src="https://business.facebook.com/ads/api/preview_iframe.php'
        '?d=AQL&amp;t=AQE" width="320" height="600"></iframe>'
    )

    assert frame.src == (
        "https://business.facebook.com/ads/api/preview_iframe.php?d=AQL&t=AQE"
    )


def test_markup_with_no_address_is_refused() -> None:
    """An empty src rendered into an iframe is a blank box with no reason."""
    with pytest.raises(MetaAPIError):
        frame_of("<iframe></iframe>")


def test_an_empty_answer_is_refused_rather_than_returned_blank() -> None:
    """Meta answers ``{"data": []}`` for a pairing it does not support."""
    with pytest.raises(MetaAPIError):
        get_preview(
            object_id="3401",
            ad_format="INSTAGRAM_STORY",
            token="t",
            client=graph_returning({"data": []}),
        )


# --- What goes out -------------------------------------------------------
def test_the_surface_is_asked_for_by_name() -> None:
    """``ad_format`` is required; Meta answers nothing without it."""
    seen: list[httpx.Request] = []

    get_preview(
        object_id="3401",
        ad_format="MOBILE_FEED_STANDARD",
        token="t",
        client=graph_returning(PAYLOAD, seen),
    )

    url = str(seen[0].url)
    assert "/3401/previews" in url
    assert "ad_format=MOBILE_FEED_STANDARD" in url


def test_a_creative_id_uses_the_same_edge() -> None:
    """The caller passes whichever id it holds; Meta decides which it was."""
    seen: list[httpx.Request] = []

    get_preview(
        object_id="9901",
        ad_format="MOBILE_FEED_STANDARD",
        token="t",
        client=graph_returning(PAYLOAD, seen),
    )

    assert "/9901/previews" in str(seen[0].url)


# --- The boundary --------------------------------------------------------
def test_the_adapter_answers_in_the_domains_own_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DTO with the ref it was asked about, not Meta's markup."""
    monkeypatch.setattr(
        "metaads.adapter.GraphClient",
        lambda **_: graph_returning(PAYLOAD),
    )
    ref = ExternalRef(provider="meta", level="ad", id="3401")

    preview = MetaCampaigns().get_preview(
        ref=ref, ad_format="MOBILE_FEED_STANDARD", token="t"
    )

    assert preview.ref == ref
    assert preview.ad_format == "MOBILE_FEED_STANDARD"
    assert preview.src.startswith("https://www.facebook.com/")


def test_metas_refusal_reaches_the_domain_as_the_domains_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing above the adapter should have to know a Meta error class."""
    monkeypatch.setattr(
        "metaads.adapter.GraphClient",
        lambda **_: graph_returning({"data": []}),
    )

    with pytest.raises(NotFound):
        MetaCampaigns().get_preview(
            ref=ExternalRef(provider="meta", level="ad", id="3401"),
            ad_format="INSTAGRAM_STORY",
            token="t",
        )
