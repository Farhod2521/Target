"""A carousel advert, and a promoted post read back.

Two shapes the Instagram-post route needed. A carousel post that cannot be
promoted where it stands is rebuilt as **one** carousel advert - Meta's
``child_attachments``, 2 to 10 cards - rather than one advert per slide.
And a promoted post is read back after it is made, because a creative
Meta accepted is not proof it kept the post.

Nothing here reaches a network.
"""

from contextlib import nullcontext
from typing import Any

import httpx
import pytest
from adskit.refs import ExternalRef
from metaads.assets import MetaAssets
from metaads.boosts import BoostSpec, boost_payload, story_counts, story_of_ad
from metaads.client import GraphClient
from metaads.launcher import MetaLauncher
from metaads.specs import CTA_SIGN_UP, CarouselCard, CreativeSpec
from metaads.stories import story_spec
from pydantic import ValidationError

SITE = "https://osh.uz"


def carousel(**extra: Any) -> CreativeSpec:
    fields: dict[str, Any] = {
        "name": "c",
        "page_id": "99",
        "message": "Uch xil taom",
        "link_url": SITE,
        "call_to_action": CTA_SIGN_UP,
        "lead_form_id": "777",
        "cards": (
            CarouselCard(image_hash="h1"),
            CarouselCard(video_id="v2", thumbnail_url="https://cdn.test/v2.jpg"),
            CarouselCard(image_hash="h3"),
        ),
    }
    fields.update(extra)
    return CreativeSpec(**fields)


# --- The shape -----------------------------------------------------------
def test_a_carousel_is_one_link_data_block_with_a_card_per_slide() -> None:
    """Snapshot of what Meta is sent. The words and the button once, the
    cards in the post's own order, and the reordering and end card off."""
    assert story_spec(carousel()) == {
        "page_id": "99",
        "link_data": {
            "message": "Uch xil taom",
            "link": SITE,
            "child_attachments": [
                {"link": SITE, "image_hash": "h1"},
                {
                    "link": SITE,
                    "video_id": "v2",
                    "picture": "https://cdn.test/v2.jpg",
                },
                {"link": SITE, "image_hash": "h3"},
            ],
            "multi_share_optimized": False,
            "multi_share_end_card": False,
            "call_to_action": {
                "type": CTA_SIGN_UP,
                "value": {"lead_gen_form_id": "777"},
            },
        },
    }


def test_the_headline_rides_on_every_card() -> None:
    cards = story_spec(carousel(headline="Bugun"))["link_data"]["child_attachments"]

    assert [card["name"] for card in cards] == ["Bugun", "Bugun", "Bugun"]


def test_a_carousel_never_becomes_a_video_block() -> None:
    """A video slide is a card, not the advert's video."""
    spec = story_spec(carousel())

    assert "video_data" not in spec


# --- Meta's bounds, refused before the call ------------------------------
@pytest.mark.parametrize("count", [1, 11])
def test_a_carousel_outside_two_to_ten_cards_is_refused(count: int) -> None:
    with pytest.raises(ValidationError):
        carousel(cards=tuple(CarouselCard(image_hash=f"h{i}") for i in range(count)))


def test_a_carousel_carries_no_picture_of_its_own() -> None:
    with pytest.raises(ValidationError):
        carousel(image_hash="stray")


def test_an_ordinary_advert_is_unchanged() -> None:
    """No cards, no ``child_attachments`` - the single-picture shape."""
    spec = story_spec(carousel(cards=(), image_hash="h1"))

    assert "child_attachments" not in spec["link_data"]
    assert spec["link_data"]["image_hash"] == "h1"


# --- The promoted post, unchanged by any of this -------------------------
def test_a_promoted_post_payload_names_the_post_and_nothing_else() -> None:
    """Snapshot of the boost route. No words, no picture, no story spec -
    sending a story spec beside the media id is how Meta silently builds a
    new post instead."""
    payload = boost_payload(
        BoostSpec(
            page_id="99",
            instagram_user_id="1784",
            media_id="1810",
            name="c",
            call_to_action=CTA_SIGN_UP,
            lead_form_id="777",
            link_url=SITE,
        )
    )

    assert payload == {
        "object_id": "99",
        "instagram_user_id": "1784",
        "source_instagram_media_id": "1810",
        "name": "c",
        "call_to_action": {
            "type": CTA_SIGN_UP,
            "value": {"link": SITE, "lead_gen_form_id": "777"},
        },
    }


# --- Reading the post and the creative -----------------------------------
def answering(payload: dict[str, Any]) -> GraphClient:
    return GraphClient(
        token="t",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=payload))
        ),
    )


def test_a_carousels_slides_are_read_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = answering(
        {
            "media_type": "CAROUSEL_ALBUM",
            "children": {
                "data": [
                    {"id": "1", "media_type": "IMAGE", "media_url": "https://a"},
                    {"id": "2", "media_type": "VIDEO", "media_url": "https://b"},
                ]
            },
        }
    )
    monkeypatch.setattr("metaads.assets.session", lambda _t: nullcontext(graph))

    slides = MetaAssets().instagram_slides(media_id="1810", token="t")

    assert [(s.media_id, s.is_video) for s in slides] == [("1", False), ("2", True)]


def test_a_single_picture_has_no_slides(monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty is how the caller tells a post that is not a carousel."""
    graph = answering({"media_type": "IMAGE", "media_url": "https://a"})
    monkeypatch.setattr("metaads.assets.session", lambda _t: nullcontext(graph))

    assert MetaAssets().instagram_slides(media_id="1810", token="t") == []


def test_the_read_back_names_the_post_the_creative_advertises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = answering(
        {"source_instagram_media_id": "1810", "effective_instagram_media_id": "1810"}
    )
    monkeypatch.setattr("metaads.launcher.session", lambda _t: nullcontext(graph))

    found = MetaLauncher().promoted_media(
        creative=ExternalRef(provider="meta", level="creative", id="5"), token="t"
    )

    assert found == ("1810", "1810")


def test_a_creative_that_kept_no_post_answers_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = answering({"id": "5"})
    monkeypatch.setattr("metaads.launcher.session", lambda _t: nullcontext(graph))

    found = MetaLauncher().promoted_media(
        creative=ExternalRef(provider="meta", level="creative", id="5"), token="t"
    )

    assert found == ()


# --- The page post a promoted Instagram post also has --------------------
def test_an_adverts_page_post_is_found() -> None:
    graph = answering({"creative": {"effective_object_story_id": "99_123"}})

    assert story_of_ad(ad_id="5", token="t", client=graph) == "99_123"


def test_a_page_posts_counts_are_totals() -> None:
    graph = answering(
        {
            "reactions": {"data": [], "summary": {"total_count": 14}},
            "comments": {"data": [], "summary": {"total_count": 3}},
            "shares": {"count": 2},
        }
    )

    assert story_counts(story_id="99_123", token="t", client=graph) == {
        "reactions": 14,
        "comments": 3,
        "shares": 2,
    }
