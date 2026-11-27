"""metaads/restage.py: another address, and a carousel's cards.

The silent failure here is an address left behind: it sits in the block, in
the button and in each card, and an advert that kept one of them leads to
two sites with no error anywhere.
"""

from typing import Any

import pytest
from adskit.errors import InvalidRequest
from metaads.restage import (
    Card,
    cards_of,
    changed,
    create_from_story,
    link_of,
    read_url_tags,
    restage,
)

OLD = "https://osh.uz"
NEW = "https://osh.uz/menyu"


def to_a_site() -> dict[str, Any]:
    return {
        "page_id": "111",
        "link_data": {
            "message": "Yangi menyu",
            "image_hash": "abc",
            "link": OLD,
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": OLD}},
        },
    }


def a_film_to_a_site() -> dict[str, Any]:
    return {
        "page_id": "111",
        "video_data": {
            "message": "Yangi menyu",
            "video_id": "v1",
            "image_url": "https://cdn/x.jpg",
            "call_to_action": {"type": "LEARN_MORE", "value": {"link": OLD}},
        },
    }


def a_carousel() -> dict[str, Any]:
    button = {"type": "SHOP_NOW", "value": {"link": OLD}}
    return {
        "page_id": "111",
        "link_data": {
            "message": "Uch xil tort",
            "link": OLD,
            "call_to_action": button,
            "child_attachments": [
                {
                    "name": "Asal",
                    "image_hash": "h1",
                    "link": OLD,
                    "call_to_action": button,
                },
                {"name": "Napoleon", "image_hash": "h2", "link": OLD},
                {
                    "name": "Film",
                    "video_id": "v9",
                    "picture": "https://cdn/p.jpg",
                    "link": "https://osh.uz/film",
                },
            ],
        },
    }


def test_the_address_moves_in_the_block_and_in_the_button() -> None:
    block = restage(to_a_site(), link=NEW)["link_data"]

    assert block["link"] == NEW
    assert block["call_to_action"] == {"type": "LEARN_MORE", "value": {"link": NEW}}
    assert block["message"] == "Yangi menyu" and block["image_hash"] == "abc"


def test_a_films_address_lives_in_its_button_only() -> None:
    block = restage(a_film_to_a_site(), link=NEW)["video_data"]

    assert block["call_to_action"]["value"] == {"link": NEW}
    assert "link" not in block


def test_a_form_a_chat_and_a_call_keep_their_address() -> None:
    form = to_a_site()
    form["link_data"]["call_to_action"]["value"] = {"lead_gen_form_id": "9"}
    chat = to_a_site()
    chat["link_data"]["call_to_action"]["value"] = {"app_destination": "MESSENGER"}
    call = to_a_site()
    call["link_data"]["link"] = "tel:+998901234567"
    call["link_data"]["call_to_action"]["value"] = {"link": "tel:+998901234567"}

    for story in (form, chat, call):
        assert link_of(story) == ""
        with pytest.raises(InvalidRequest) as caught:
            restage(story, link=NEW)
        assert caught.value.code == "restage_link"


def test_the_same_address_is_no_change() -> None:
    assert link_of(to_a_site()) == OLD
    assert changed(to_a_site(), link=OLD) is False
    assert changed(to_a_site(), link=NEW) is True


def test_cards_that_led_where_the_advert_led_follow_it() -> None:
    cards = restage(a_carousel(), link=NEW)["link_data"]["child_attachments"]

    assert [card["link"] for card in cards] == [NEW, NEW, "https://osh.uz/film"]
    assert cards[0]["call_to_action"]["value"]["link"] == NEW


def test_cards_are_reordered_reworded_and_one_is_taken_out() -> None:
    cards = restage(
        a_carousel(),
        cards=[Card(source=1, headline="Napoleon 20%"), Card(source=0, description="")],
    )["link_data"]["child_attachments"]

    assert [card["name"] for card in cards] == ["Napoleon 20%", "Asal"]
    assert cards[0]["image_hash"] == "h2"
    assert "description" not in cards[1]


def test_a_new_card_leads_where_the_first_leads_and_wears_its_button() -> None:
    cards = restage(
        a_carousel(),
        cards=[
            Card(source=0),
            Card(source=1),
            Card(headline="Medovik", image_hash="h7"),
        ],
    )["link_data"]["child_attachments"]

    assert cards[2] == {
        "link": OLD,
        "call_to_action": {"type": "SHOP_NOW", "value": {"link": OLD}},
        "name": "Medovik",
        "image_hash": "h7",
    }


def test_a_still_in_place_of_a_cards_film() -> None:
    cards = restage(
        a_carousel(), cards=[Card(source=0), Card(source=2, image_hash="h8")]
    )["link_data"]["child_attachments"]

    assert cards[1] == {
        "name": "Film",
        "link": "https://osh.uz/film",
        "image_hash": "h8",
    }


def test_the_cards_sent_back_as_they_are_is_no_change() -> None:
    same = [Card(source=0), Card(source=1), Card(source=2)]

    assert changed(a_carousel(), cards=same) is False
    assert changed(a_carousel(), cards=same[::-1]) is True
    assert [row["name"] for row in cards_of(a_carousel())] == [
        "Asal",
        "Napoleon",
        "Film",
    ]


@pytest.mark.parametrize(
    "cards",
    [
        [Card(source=0)],
        [Card(source=0)] * 2,
        [Card(source=0), Card(source=5)],
        [Card(source=0), Card(headline="rasmsiz")],
        [Card(source=0, image_hash="h")] + [Card(image_hash="h")] * 10,
    ],
)
def test_cards_that_cannot_be_built_are_refused(cards: list[Card]) -> None:
    with pytest.raises(InvalidRequest) as caught:
        restage(a_carousel(), cards=cards)

    assert caught.value.code == "restage_cards"


def test_an_advert_that_is_not_a_carousel_takes_no_cards() -> None:
    assert cards_of(to_a_site()) == []
    with pytest.raises(InvalidRequest):
        restage(to_a_site(), cards=[Card(source=0), Card(source=1)])


class _Graph:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict[str, Any]]] = []

    def for_token(self, _token: str) -> "_Graph":
        return self

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        assert params == {"fields": "url_tags"}
        return {"id": path, "url_tags": "utm_source=meta"}

    def post(
        self, path: str, data: dict[str, Any] | None = None, **_: Any
    ) -> dict[str, Any]:
        self.posts.append((path, data or {}))
        return {"id": "cr_new"}


def test_the_tags_are_read_and_a_dry_run_sends_nothing() -> None:
    graph = _Graph()

    assert (
        read_url_tags(creative_id="cr_1", token="t", client=graph) == "utm_source=meta"
    )  # type: ignore[arg-type]
    made = create_from_story(
        account_id="1", name="n", story=to_a_site(), token="t", url_tags="a=b"
    )
    assert made and graph.posts == []
