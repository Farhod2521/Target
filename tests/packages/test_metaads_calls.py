"""The creative whose button dials, and the creative with no button.

Two more shapes in the one key that has now grown three times.
``call_to_action.value`` carries a form id, a messaging surface, a
``tel:`` URI, or a link - four values, one slot - and the ad runs whichever
of them is in there. That is what makes this the most dangerous field in
the package and the reason each shape is pinned rather than described.

The fifth case is the absence of the block. ``NO_BUTTON`` is Meta's own
enum value, and it is **not** the same as leaving ``call_to_action`` out:
an omitted call to action is one Meta supplies, and what it supplies is a
link. So the block is removed on purpose, by a value that says so.

Nothing here reaches a network.
"""

import json
from typing import Any

import pytest
from metaads.specs import CTA_NO_BUTTON, TEL_SCHEME, CreativeSpec
from metaads.stories import story_spec

SITE = "https://osh.uz"
NUMBER = "+998901234567"


def a_spec(**extra: Any) -> CreativeSpec:
    words: dict[str, Any] = {
        "name": "c",
        "page_id": "99",
        "message": "Salom",
        "link_url": SITE,
        "image_hash": "abc",
    }
    return CreativeSpec(**(words | extra))


def link_data(spec: CreativeSpec) -> dict[str, Any]:
    return story_spec(spec)["link_data"]


# --- The number lives in the button --------------------------------------
def test_a_call_button_carries_a_tel_uri_and_not_a_link() -> None:
    """The failure this turns on, and the third time the same one has
    appeared. Without it, a creative with no form id and no messaging
    surface gets ``{"link": ...}`` - so a calls goal builds an ad that
    opens a web page under a "Call now" button, runs, and reports
    clicks."""
    action = link_data(a_spec(call_to_action="CALL_NOW", phone_number=NUMBER))[
        "call_to_action"
    ]

    assert action == {"type": "CALL_NOW", "value": {"link": f"{TEL_SCHEME}{NUMBER}"}}


def test_the_creative_s_own_link_is_left_alone_by_the_number() -> None:
    """Meta's own example keeps the business page in ``link_data.link``
    while the number sits in the button. On this ad the outer link is the
    formality it is on a lead ad: nobody follows it, the tap dials."""
    block = link_data(a_spec(call_to_action="CALL_NOW", phone_number=NUMBER))

    assert block["link"] == SITE


def test_a_video_call_ad_gets_the_same_button() -> None:
    """The two blocks name the headline and the picture differently and
    the button identically. A shape that only worked on image ads would be
    found by whoever uploaded the first video."""
    story = story_spec(
        a_spec(
            call_to_action="CALL_NOW",
            phone_number=NUMBER,
            image_hash="",
            video_id="v1",
            thumbnail_url="https://cdn/t.jpg",
        )
    )

    assert story["video_data"]["call_to_action"]["value"] == {
        "link": f"{TEL_SCHEME}{NUMBER}"
    }


def test_one_key_still_holds_exactly_one_value() -> None:
    """Four things can be in there and only one may be. Sending two is how
    an ad opens a website instead of the thing it was built for."""
    for extra in (
        {"phone_number": NUMBER},
        {"app_destination": "MESSENGER"},
        {"lead_form_id": "777"},
        {},
    ):
        value = link_data(a_spec(**extra))["call_to_action"]["value"]
        assert len(value) == 1, extra


def test_the_order_of_specificity_holds_for_the_number_too() -> None:
    """A spec carrying both a form and a number is one nobody should have
    built. The form wins because it is the half that cost a call nothing
    can take back."""
    action = link_data(a_spec(lead_form_id="777", phone_number=NUMBER))[
        "call_to_action"
    ]

    assert action["value"] == {"lead_gen_form_id": "777"}


def test_a_number_on_a_spec_that_names_a_surface_loses_to_the_surface() -> None:
    """Both are more specific than a link and they cannot both be true.
    Fixed here so that the order is a decision rather than an accident of
    how the branches were typed."""
    action = link_data(a_spec(app_destination="MESSENGER", phone_number=NUMBER))[
        "call_to_action"
    ]

    assert action["value"] == {"app_destination": "MESSENGER"}


def test_an_ordinary_ad_still_carries_a_link() -> None:
    """The branch every other kind of ad falls into."""
    assert link_data(a_spec())["call_to_action"]["value"] == {"link": SITE}


# --- What the spec refuses to be built with ------------------------------
def test_a_number_that_is_not_e164_is_refused_at_construction() -> None:
    """The last object before the ad, so a refusal here costs nothing and
    a number Meta cannot dial costs a campaign that delivers in silence."""
    for bad in ("998901234567", "+998 90 123 45 67", "+", "salom", "+99890abc"):
        with pytest.raises(ValueError, match=r"E\.164"):
            a_spec(phone_number=bad)


def test_an_empty_number_is_ordinary_and_not_refused() -> None:
    """Most ads have none. What refuses a call ad without one is the gate
    two layers up, which knows what kind of ad this is."""
    assert a_spec().phone_number == ""


def test_a_number_meta_can_dial_is_accepted_as_it_stands() -> None:
    assert a_spec(phone_number=NUMBER).phone_number == NUMBER


# --- No button at all ----------------------------------------------------
def test_no_button_removes_the_block_rather_than_emptying_it() -> None:
    """The distinction the whole case turns on. An absent ``call_to_action``
    is one Meta fills in, and what it fills in is a link - so an awareness
    ad bought on impressions would carry a tap to whatever address the
    creative happened to hold."""
    block = link_data(a_spec(call_to_action=CTA_NO_BUTTON))

    assert "call_to_action" not in block


def test_no_button_still_leaves_the_link_meta_demands() -> None:
    """Meta wants a link on every creative whether or not anything shows
    it. Removing the button is not removing the address."""
    block = link_data(a_spec(call_to_action=CTA_NO_BUTTON))

    assert block["link"] == SITE


def test_no_button_wins_over_everything_that_could_have_gone_in_it() -> None:
    """Checked first, and deliberately. A spec that says "no button" and
    also names a form is contradictory, and the safe reading of it is the
    one that shows nobody a button to a thing they were not promised."""
    block = link_data(
        a_spec(
            call_to_action=CTA_NO_BUTTON,
            lead_form_id="777",
            phone_number=NUMBER,
        )
    )

    assert "call_to_action" not in block


def test_a_video_awareness_ad_loses_its_button_too() -> None:
    story = story_spec(
        a_spec(
            call_to_action=CTA_NO_BUTTON,
            image_hash="",
            video_id="v1",
            thumbnail_url="https://cdn/t.jpg",
        )
    )

    assert "call_to_action" not in story["video_data"]


def test_a_call_ad_carries_no_welcome_message() -> None:
    """The greeting belongs to a thread and a call ad opens none. Nothing
    forbids the combination in this package - the catalogue does - so what
    is pinned here is only that the two fields do not interfere."""
    block = link_data(a_spec(call_to_action="CALL_NOW", phone_number=NUMBER))

    assert "page_welcome_message" not in block


def test_the_tel_scheme_is_named_once_and_used_once() -> None:
    """Named rather than written inline, like the welcome message's four
    constants: turning a number into a URI is this package's knowledge, and
    a caller passing ``tel:`` itself would be a caller that had to know."""
    action = link_data(a_spec(call_to_action="CALL_NOW", phone_number=NUMBER))[
        "call_to_action"
    ]

    assert action["value"]["link"].startswith(TEL_SCHEME)
    assert json.dumps(action)  # the whole block is still plain JSON
