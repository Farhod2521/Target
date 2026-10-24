"""Reading an Instagram account's posts, and reaching the files behind them.

Two halves of one route and neither is a Graph call in the usual sense. The
first is: ``/{ig-user-id}/media`` is an ordinary edge, but it answers with a
vocabulary nothing else in this package uses - the file is ``media_url`` and
there is no hash anywhere. The second is not a Graph call at all: the file
lives on a CDN, and ``/act_<id>/adimages`` accepts no URL, so the bytes have
to come through our own network before they can be uploaded.

Nothing here reaches a network. What is under test is which path is asked
for, which fields ride on it, and what the probe makes of an answer.
"""

import httpx
import pytest
from adskit.errors import InvalidRequest, TemporaryFailure
from adskit.refs import ExternalRef
from metaads import assets as assets_module
from metaads import cdn, creatives, discovery
from metaads.assets import MAX_IMAGE_BYTES, MetaAssets
from metaads.errors import PagesExhausted

from tests.packages.test_metaads_client import client_returning

ACCOUNT = ExternalRef(provider="meta", level="account", id="act_1")

MEDIA = {
    "id": "17895695668004550",
    "caption": "Yangi menyu",
    "media_type": "IMAGE",
    "media_product_type": "FEED",
    "media_url": "https://scontent.cdninstagram.com/v/t51/1.jpg?_nc_sig=abc",
    "permalink": "https://www.instagram.com/p/abc/",
    "timestamp": "2026-08-30T09:00:00+0000",
}


# --- The list ------------------------------------------------------------
def test_the_media_edge_hangs_off_the_instagram_id_not_the_page() -> None:
    """The page is how the account was found; it is not what answers.

    Asking ``/{page-id}/media`` returns nothing recognisable, and the
    mistake is easy because every other page-shaped read in this package
    takes the page id.
    """
    captured: list[httpx.Request] = []
    graph = client_returning(
        httpx.Response(200, json={"data": [MEDIA]}), capture=captured
    )

    discovery.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)

    assert "/ig-1/media" in str(captured[0].url)


def test_the_list_asks_for_the_file_itself() -> None:
    """``media_url`` is the field the whole route rests on: an image has to
    reach ``/act_<id>/adimages`` as bytes, and that edge takes no URL."""
    captured: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"data": []}), capture=captured)

    discovery.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)

    assert "media_url" in str(captured[0].url)
    assert "media_product_type" in str(captured[0].url)


def test_whether_a_post_can_be_advertised_rides_on_the_list() -> None:
    """Arithmetic, not preference. Read per post instead, a sweep over an
    account with a hundred of them makes a hundred extra calls to find out
    which ones a picker may offer."""
    assert "boost_eligibility_info" in discovery.IG_MEDIA_FIELDS


def test_the_carousel_slides_are_only_asked_for_one_post_at_a_time() -> None:
    """The parent already answers with a frame Meta chose, so the children
    are worth a call only when somebody is looking at that one post."""
    for field in ("children", "is_shared_to_feed", "username"):
        assert field not in discovery.IG_MEDIA_FIELDS
        assert field in discovery.IG_MEDIA_DETAIL_FIELDS


def test_a_narrower_field_list_can_be_asked_for() -> None:
    """How a ``#100`` gets bisected: the console passes what it wants."""
    captured: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json={"data": []}), capture=captured)

    discovery.list_instagram_media(
        ig_user_id="ig-1", token="t", fields="id", client=graph
    )

    assert "fields=id&" in f"{captured[0].url}&"
    assert "media_url" not in str(captured[0].url)


def test_the_list_follows_paging() -> None:
    """An account with a few hundred posts answers over several pages, and
    a picker built from the first one would be missing most of them."""
    graph = client_returning(
        httpx.Response(
            200,
            json={
                "data": [MEDIA],
                "paging": {"next": "https://graph.facebook.com/v26.0/next"},
            },
        ),
        httpx.Response(200, json={"data": [{**MEDIA, "id": "2"}]}),
    )

    rows = discovery.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)

    assert [row["id"] for row in rows] == ["17895695668004550", "2"]


def test_the_recent_read_is_one_request_however_long_the_account() -> None:
    """It answers "what was posted just now", and the edge is newest first.
    Following the cursor would make it the full read again."""
    captured: list[httpx.Request] = []
    graph = client_returning(
        httpx.Response(
            200,
            json={
                "data": [MEDIA],
                "paging": {"next": "https://graph.facebook.com/v26.0/next"},
            },
        ),
        capture=captured,
    )

    rows = discovery.list_recent_instagram_media(
        ig_user_id="ig-1", token="t", client=graph
    )

    assert [row["id"] for row in rows] == [MEDIA["id"]]
    assert len(captured) == 1
    assert "/ig-1/media" in str(captured[0].url)
    assert "media_url" in str(captured[0].url)


def test_the_recent_read_drops_on_the_full_reads_rules() -> None:
    """A withheld file is as unusable on the newest page as anywhere else."""
    graph = client_returning(
        httpx.Response(
            200, json={"data": [MEDIA, {**MEDIA, "id": "2", "media_url": ""}]}
        )
    )

    got = creatives.list_recent_instagram_media(
        ig_user_id="ig-1", token="t", client=graph
    )

    assert [item.external_id for item in got] == [MEDIA["id"]]


def test_a_profile_past_the_client_default_is_read_whole() -> None:
    """Thirty pages is past the client's default of twenty-five, and a
    read that stopped there would store nothing at all."""
    more = httpx.Response(
        200,
        json={
            "data": [MEDIA],
            "paging": {"next": "https://graph.facebook.com/v26.0/next"},
        },
    )
    last = httpx.Response(200, json={"data": [MEDIA]})
    graph = client_returning(*([more] * 29), last)

    rows = discovery.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)

    assert len(rows) == 30


def test_the_instagram_ceiling_still_stops_a_looping_cursor() -> None:
    looping = httpx.Response(
        200,
        json={
            "data": [MEDIA],
            "paging": {"next": "https://graph.facebook.com/v26.0/next"},
        },
    )
    graph = client_returning(looping)

    with pytest.raises(PagesExhausted) as caught:
        discovery.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)

    assert caught.value.pages == discovery.IG_MEDIA_PAGES


# --- One post ------------------------------------------------------------
def test_one_post_is_asked_for_its_slides() -> None:
    captured: list[httpx.Request] = []
    graph = client_returning(httpx.Response(200, json=MEDIA), capture=captured)

    row = discovery.read_instagram_media(media_id="17895", token="t", client=graph)

    assert "children" in str(captured[0].url)
    assert row["id"] == MEDIA["id"]


def test_a_reel_with_licensed_audio_says_so_in_meta_s_own_words() -> None:
    """The shape a live account answered with, pinned because nothing
    documents it. The file downloads perfectly well - it is the finished ad
    that gets rejected - so a picker reading only ``media_url`` would offer
    a video that cannot run."""
    graph = client_returning(
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        **MEDIA,
                        "media_type": "VIDEO",
                        "media_product_type": "REELS",
                        "boost_eligibility_info": {
                            "eligible_to_boost": False,
                            "boost_ineligible_reason": (
                                "Remove or choose different audio."
                            ),
                        },
                    }
                ]
            },
        )
    )

    rows = discovery.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)

    assert rows[0]["boost_eligibility_info"]["eligible_to_boost"] is False
    assert rows[0]["media_url"]


# --- Reaching the file ---------------------------------------------------
def probe_against(response: httpx.Response) -> cdn.MediaProbe:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: response))
    try:
        return cdn.probe_media(url=MEDIA["media_url"], client=client)
    finally:
        client.close()


def test_the_probe_reads_the_headers_and_not_the_body() -> None:
    probe = probe_against(
        httpx.Response(
            200,
            headers={"content-type": "image/jpeg", "content-length": "184320"},
            content=b"x" * 10,
        )
    )

    assert probe.reachable
    assert probe.status == 200
    assert probe.content_type == "image/jpeg"
    assert probe.content_length == 184_320


def test_a_refusal_is_reachable_and_is_the_answer() -> None:
    """A signed URL that has expired answers 403, and telling that apart
    from "our network cannot get there" is the whole point of the call."""
    probe = probe_against(httpx.Response(403))

    assert probe.reachable
    assert probe.status == 403


def test_a_transport_failure_is_reported_rather_than_raised() -> None:
    """The caller is a console printing what happened, and "connection
    refused" is exactly what it was opened to read."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    try:
        probe = cdn.probe_media(url=MEDIA["media_url"], client=client)
    finally:
        client.close()

    assert not probe.reachable
    assert probe.status == 0
    assert "nope" in probe.detail


def test_a_missing_length_is_unknown_and_not_empty() -> None:
    """A chunked response carries no length. A ceiling that read zero as
    empty would let exactly the files it exists to stop straight through."""
    probe = probe_against(httpx.Response(200, headers={"content-type": "video/mp4"}))

    assert probe.content_length == 0


def test_the_probe_does_not_echo_the_signed_url() -> None:
    """The console already answers with the raw row, ``media_url`` included.
    Repeating a signed link in a second place is a habit worth not forming."""
    probe = probe_against(httpx.Response(200))

    assert probe.host == "scontent.cdninstagram.com"
    assert "_nc_sig" not in probe.model_dump_json()


# --- Fetching the file ---------------------------------------------------
def fetching(response: httpx.Response) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda _: response))


def test_the_file_arrives_as_bytes() -> None:
    client = fetching(httpx.Response(200, content=b"jpeg-bytes"))
    try:
        data = cdn.download_media(url=MEDIA["media_url"], max_bytes=1000, client=client)
    finally:
        client.close()

    assert data == b"jpeg-bytes"


def test_a_declared_length_over_the_ceiling_is_refused_before_reading() -> None:
    """The cheap check. A reel announces its size in a header, and there is
    no reason to pull tens of megabytes through a worker to find out."""
    client = fetching(
        httpx.Response(200, headers={"content-length": "999"}, content=b"x" * 999)
    )
    try:
        with pytest.raises(cdn.MediaTooLargeError):
            cdn.download_media(url=MEDIA["media_url"], max_bytes=100, client=client)
    finally:
        client.close()


def test_a_chunked_response_is_still_stopped_at_the_ceiling() -> None:
    """The check that matters. A response with no ``Content-Length`` reads
    as unknown, and a reader trusting the header alone would let through
    exactly the file the ceiling exists to stop."""

    def stream(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=iter([b"x" * 60, b"x" * 60]))

    client = httpx.Client(transport=httpx.MockTransport(stream))
    try:
        with pytest.raises(cdn.MediaTooLargeError):
            cdn.download_media(url=MEDIA["media_url"], max_bytes=100, client=client)
    finally:
        client.close()


def test_an_expired_signature_is_not_worth_retrying() -> None:
    """A 403 is a URL that aged out. The fix is a fresh address, which is
    why ``media_url`` is read again immediately before the fetch."""
    client = fetching(httpx.Response(403))
    try:
        with pytest.raises(cdn.MediaUnavailableError):
            cdn.download_media(url=MEDIA["media_url"], max_bytes=1000, client=client)
    finally:
        client.close()


def test_a_cdn_outage_is_worth_retrying() -> None:
    client = fetching(httpx.Response(503))
    try:
        with pytest.raises(cdn.MetaTemporaryError):
            cdn.download_media(url=MEDIA["media_url"], max_bytes=1000, client=client)
    finally:
        client.close()


def test_a_transport_failure_while_downloading_is_temporary() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = httpx.Client(transport=httpx.MockTransport(refuse))
    try:
        with pytest.raises(cdn.MetaTemporaryError):
            cdn.download_media(url=MEDIA["media_url"], max_bytes=1000, client=client)
    finally:
        client.close()


# --- Importing into the ad account ---------------------------------------
def test_importing_a_picture_fetches_it_and_then_uploads_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        assets_module, "download_media", lambda **kw: seen.update(kw) or b"bytes"
    )
    monkeypatch.setattr(
        assets_module, "upload_image", lambda **kw: seen.update(kw) or "hash-1"
    )

    got = MetaAssets().import_image(
        account=ACCOUNT, media_url="https://cdn/1.jpg", token="t", dry_run=False
    )

    assert got == "hash-1"
    assert seen["url"] == "https://cdn/1.jpg"
    assert seen["max_bytes"] == MAX_IMAGE_BYTES
    assert seen["data"] == b"bytes"


def test_a_rehearsal_does_not_touch_the_cdn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fetching a file only to hand it to an upload that will not happen
    would be the one call a dry run made for real - against somebody
    else's bandwidth."""
    monkeypatch.setattr(
        assets_module,
        "download_media",
        lambda **kw: pytest.fail("a rehearsal fetched the file"),
    )

    got = MetaAssets().import_image(
        account=ACCOUNT, media_url="https://cdn/1.jpg", token="t", dry_run=True
    )

    assert got


def test_a_download_failure_reaches_the_caller_in_the_domain_s_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reason the fetch sits inside ``session``. Raised outside it,
    ``MediaTooLargeError`` - this package's word - would land in a service,
    which is what the whole error hierarchy exists to prevent."""

    def refuse(**kwargs: object) -> bytes:
        raise cdn.MediaTooLargeError("too big")

    monkeypatch.setattr(assets_module, "download_media", refuse)

    with pytest.raises(InvalidRequest):
        MetaAssets().import_image(
            account=ACCOUNT, media_url="https://cdn/1.jpg", token="t", dry_run=False
        )


def test_a_cdn_outage_reaches_the_caller_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(**kwargs: object) -> bytes:
        raise cdn.MetaTemporaryError("cdn is down")

    monkeypatch.setattr(assets_module, "download_media", refuse)

    with pytest.raises(TemporaryFailure) as caught:
        MetaAssets().import_image(
            account=ACCOUNT, media_url="https://cdn/1.jpg", token="t", dry_run=False
        )

    assert caught.value.retryable


def test_importing_a_reel_hands_meta_the_url_instead_of_the_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing of the video passes through this process, which is the whole
    reason the video half is shorter than the image half."""
    seen: dict[str, object] = {}
    monkeypatch.setattr(
        assets_module, "upload_video_from_url", lambda **kw: seen.update(kw) or "vid-1"
    )
    monkeypatch.setattr(
        assets_module,
        "download_media",
        lambda **kw: pytest.fail("a reel was pulled through the worker"),
    )

    got = MetaAssets().import_video(
        account=ACCOUNT, media_url="https://cdn/1.mp4", token="t", dry_run=False
    )

    assert got == "vid-1"
    assert seen["file_url"] == "https://cdn/1.mp4"


# --- Reading it as something an ad could be made of -----------------------
def parsed(*rows: dict[str, object]) -> list[object]:
    graph = client_returning(httpx.Response(200, json={"data": list(rows)}))
    return list(
        creatives.list_instagram_media(ig_user_id="ig-1", token="t", client=graph)
    )


def test_a_carousel_is_read_as_a_picture() -> None:
    """Meta answers the album with one frame it chose itself, so the ad is
    a single image and nobody here picked which slide."""
    got = parsed({**MEDIA, "media_type": "CAROUSEL_ALBUM"})

    assert got[0].kind == creatives.IG_IMAGE
    assert got[0].thumbnail_url == MEDIA["media_url"]


def test_a_reel_is_read_as_a_video_and_keeps_its_own_still() -> None:
    got = parsed(
        {
            **MEDIA,
            "media_type": "VIDEO",
            "media_product_type": "REELS",
            "thumbnail_url": "https://cdn/still.jpg",
        }
    )

    assert got[0].kind == creatives.IG_VIDEO
    assert got[0].thumbnail_url == "https://cdn/still.jpg"


def test_a_post_meta_withheld_the_file_for_is_dropped() -> None:
    """Licensed music or a copyright flag. Not rare - three of the first
    fifty on the account this was written against - and there is nothing to
    fall back on, so a row with no file is a thumbnail nothing can upload."""
    assert parsed({k: v for k, v in MEDIA.items() if k != "media_url"}) == []


def test_media_that_was_only_ever_an_ad_is_dropped() -> None:
    assert parsed({**MEDIA, "media_product_type": "AD"}) == []


def test_an_ineligible_post_is_kept_with_its_reason() -> None:
    """Dropped here, somebody hunts for a video they can see on their own
    profile. Kept, the screen can grey it and say why."""
    got = parsed(
        {
            **MEDIA,
            "boost_eligibility_info": {
                "eligible_to_boost": False,
                "boost_ineligible_reason": "Remove or choose different audio.",
            },
        }
    )

    assert got[0].is_eligible is False
    assert got[0].ineligible_reason == "Remove or choose different audio."


def test_a_verdict_meta_did_not_send_is_unknown_and_not_a_refusal() -> None:
    """A field an API version stopped answering would otherwise empty the
    whole picker."""
    got = parsed(MEDIA)

    assert got[0].is_eligible is None
    assert got[0].ineligible_reason == ""


def test_the_caption_becomes_the_name_it_is_recognised_by() -> None:
    got = parsed(MEDIA)

    assert got[0].name == "Yangi menyu"
    assert got[0].external_id == MEDIA["id"]
    assert got[0].permalink_url == MEDIA["permalink"]
