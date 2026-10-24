"""The creative that opens a conversation instead of following a link.

Three kinds of ad share one story spec and differ in one key: what the
button's ``value`` carries. A lead ad carries a form id, a messaging ad
carries the surface the thread opens on, and everything else carries a
link. Getting that wrong does not produce a broken ad - it produces a
**working website ad** sold to somebody who was promised a conversation,
reporting clicks all the way, with nothing on any screen to say so. That
silence is the whole reason this file exists.

Beside it sits ``page_welcome_message``: what is already written in the
thread when the customer arrives. Four levels of Meta's own vocabulary,
every level required, and the same kind of table as the headline names -
right only while a test says so.

Nothing here reaches a network.
"""

import json
from typing import Any

import pytest
from metaads.accounts import PAGE_FIELDS
from metaads.boosts import BoostSpec, boost_payload
from metaads.dto import PageDTO
from metaads.specs import APP_DESTINATIONS, CreativeSpec
from metaads.stories import story_spec, welcome_message

SITE = "https://osh.uz"
GREETING = "Osh Markazi — salom! Menyu bo'yicha shu yerda yozing."
AUTOFILL = "Salom! Ushbu taklif haqida ma'lumot bering."


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


# --- One key, one value in it --------------------------------------------
def test_a_messaging_button_carries_a_surface_and_not_a_link() -> None:
    """The failure this whole rule turns on. Without it, every creative
    without a form id gets ``{"link": ...}`` - so a messages goal builds an
    ad that opens a web page, runs, and reports clicks for it."""
    action = link_data(
        a_spec(call_to_action="MESSAGE_PAGE", app_destination="MESSENGER")
    )["call_to_action"]

    assert action == {"type": "MESSAGE_PAGE", "value": {"app_destination": "MESSENGER"}}


def test_an_ordinary_button_still_carries_the_link() -> None:
    """The other half, so a regression cannot hide as a passing chat
    test."""
    action = link_data(a_spec(call_to_action="LEARN_MORE"))["call_to_action"]

    assert action == {"type": "LEARN_MORE", "value": {"link": SITE}}


def test_a_lead_button_still_carries_the_form() -> None:
    action = link_data(a_spec(lead_form_id="777"))["call_to_action"]

    assert action == {"type": "SIGN_UP", "value": {"lead_gen_form_id": "777"}}


def test_the_form_wins_over_a_surface_that_should_not_be_there() -> None:
    """A spec carrying both is one nobody should have built. The order is
    specificity, and the form is the half that already cost a call nothing
    can take back."""
    action = link_data(a_spec(lead_form_id="777", app_destination="MESSENGER"))[
        "call_to_action"
    ]

    assert action["value"] == {"lead_gen_form_id": "777"}


def test_only_one_value_is_ever_sent() -> None:
    """Sending two is how an ad ends up opening a website instead of the
    thing it was built for."""
    for extra in ({"app_destination": "MESSENGER"}, {"lead_form_id": "777"}, {}):
        value = link_data(a_spec(**extra))["call_to_action"]["value"]
        assert len(value) == 1


# --- The surfaces Meta has ------------------------------------------------
def test_the_three_surfaces_are_meta_s_own() -> None:
    assert {"MESSENGER", "INSTAGRAM_DIRECT", "WHATSAPP"} == APP_DESTINATIONS


@pytest.mark.parametrize("surface", sorted(APP_DESTINATIONS))
def test_each_surface_is_accepted(surface: str) -> None:
    assert a_spec(app_destination=surface).app_destination == surface


def test_a_surface_meta_does_not_have_is_refused_at_construction() -> None:
    """Before the first call rather than five calls in, where a campaign
    and an ad set already exist."""
    with pytest.raises(ValueError, match="messaging destination"):
        a_spec(app_destination="TELEGRAM")


# --- What is in the thread before anybody arrives -------------------------
def test_the_welcome_message_is_a_json_string() -> None:
    """Meta types the field as a string - "a JSON object passed as a
    string" - while the click-to-Messenger guide's own example nests it as
    an object. The reference is followed, because it is the half of the
    documentation that is about the type."""
    block = link_data(
        a_spec(
            app_destination="MESSENGER", welcome_text=GREETING, autofill_text=AUTOFILL
        )
    )
    sent = block["page_welcome_message"]

    assert isinstance(sent, str)
    assert json.loads(sent)["type"] == "VISUAL_EDITOR"


def test_every_level_meta_requires_is_there() -> None:
    """Four constants that mean nothing on their own, and Meta refuses the
    creative if any of them is wrong."""
    payload = json.loads(
        welcome_message(a_spec(welcome_text=GREETING, autofill_text=AUTOFILL))
    )

    assert payload["version"] == 2
    assert payload["landing_screen_type"] == "welcome_message"
    assert payload["media_type"] == "text"
    assert payload["text_format"]["customer_action_type"] == "autofill_message"
    assert payload["text_format"]["message"]["text"] == GREETING
    assert payload["text_format"]["message"]["autofill_message"] == {
        "content": AUTOFILL
    }


def test_uzbek_survives_the_encoding() -> None:
    """``ensure_ascii`` off. An apostrophe-heavy language turned into
    escape sequences is still valid JSON and unreadable in every log and
    every trace this product writes."""
    assert "o'" in welcome_message(a_spec(welcome_text="Bo'sh o'rin bor"))


def test_no_greeting_means_no_field_at_all() -> None:
    """A working ad rather than a blank one: with the field absent Meta
    writes its own greeting, and an empty string sent instead would be a
    greeting that says nothing."""
    block = link_data(a_spec(app_destination="MESSENGER"))

    assert "page_welcome_message" not in block


def test_the_greeting_alone_decides() -> None:
    """A spec carrying only the customer's own line would open a thread
    with words in their mouth and none in the business's."""
    assert welcome_message(a_spec(autofill_text=AUTOFILL)) == ""


def test_a_video_chat_ad_carries_the_same_two_things() -> None:
    """Both blocks, because the ad being a video changes the picture and
    nothing about where the tap goes."""
    block = story_spec(
        a_spec(
            video_id="v1",
            thumbnail_url="https://cdn/x.jpg",
            app_destination="MESSENGER",
            call_to_action="MESSAGE_PAGE",
            welcome_text=GREETING,
        )
    )["video_data"]

    assert block["call_to_action"]["value"] == {"app_destination": "MESSENGER"}
    assert json.loads(block["page_welcome_message"])["text_format"]["message"]["text"]


def test_an_ordinary_creative_gains_nothing() -> None:
    assert "page_welcome_message" not in link_data(a_spec())
    assert a_spec().app_destination == ""


# --- The Instagram account a thread opens into ----------------------------
def test_an_instagram_creative_carries_the_account_it_opens_into() -> None:
    """Meta refuses the creative without it. A Facebook page cannot receive
    an Instagram message on somebody's behalf, so there is nothing to
    substitute and nothing to fall back to."""
    story = story_spec(
        a_spec(
            call_to_action="INSTAGRAM_MESSAGE",
            app_destination="INSTAGRAM_DIRECT",
            instagram_user_id="ig-1",
        )
    )

    assert story["instagram_user_id"] == "ig-1"
    assert story["link_data"]["call_to_action"]["value"] == {
        "app_destination": "INSTAGRAM_DIRECT"
    }


def test_the_account_is_named_under_the_word_this_version_reads() -> None:
    """The spelling Meta retired, and the one it reads now.

    Meta called the field ``instagram_actor_id`` until v22.0 and retired
    that spelling for every API version on 2025-09-09; the v26.0 object
    story spec does not list it at all. The failure is silent - an unknown key inside a
    nested spec is dropped rather than refused - so the creative builds,
    the ad runs, and it runs as the page.
    """
    story = story_spec(a_spec(instagram_user_id="ig-1"))

    assert "instagram_actor_id" not in story


def test_no_account_leaves_the_key_out_altogether() -> None:
    """Most advertisers here have a page and nothing else, and an empty
    string is not the same as an absent field."""
    assert "instagram_user_id" not in story_spec(a_spec())


def test_a_page_read_answers_with_the_instagram_account_when_there_is_one() -> None:
    """Flattened where it is read rather than carried nested: the id is the
    whole of what an ad creative needs, and a caller holding a DTO for one
    field writes ``page.instagram_business_account.id`` with a ``None`` in
    the middle of it."""
    page = PageDTO.model_validate(
        {
            "id": "99",
            "name": "Osh Markazi",
            "instagram_business_account": {"id": "ig-1", "username": "oshmarkazi"},
        }
    )

    assert page.instagram_id == "ig-1"
    assert page.instagram_username == "oshmarkazi"


def test_a_page_without_one_answers_empty_rather_than_raising() -> None:
    """The ordinary case. An Instagram account is connected to a page by
    hand, and plenty of businesses have one of the two."""
    page = PageDTO.model_validate({"id": "99", "name": "Osh Markazi"})

    assert page.instagram_id == ""
    assert page.instagram_username == ""


def test_the_page_read_asks_for_it() -> None:
    """One list, one call. Asking per page afterwards is both slower and a
    second chance for the user token to have expired in between."""
    assert "instagram_business_account{id,username}" in PAGE_FIELDS


# --- A post promoted where it stands -------------------------------------
def a_boost(**overrides: str) -> BoostSpec:
    fields = {
        "page_id": "99",
        "instagram_user_id": "ig-1",
        "media_id": "18097965637788300",
        "call_to_action": "MESSAGE_PAGE",
        "app_destination": "MESSENGER",
        "link_url": "https://example.uz/",
    }
    return BoostSpec(**(fields | overrides))


def test_a_promoted_post_carries_the_greeting_on_the_creative() -> None:
    """The post route has no ``link_data``: the greeting is a field of the
    creative itself, the shape a live account kept on both channels."""
    payload = boost_payload(a_boost(welcome_text=GREETING, autofill_text=AUTOFILL))

    assert "object_story_spec" not in payload
    assert payload["page_welcome_message"] == welcome_message(
        a_spec(welcome_text=GREETING, autofill_text=AUTOFILL)
    )


def test_a_promoted_post_with_no_greeting_sends_no_field() -> None:
    assert "page_welcome_message" not in boost_payload(a_boost())


def test_a_promoted_post_sends_no_lone_autofill() -> None:
    assert "page_welcome_message" not in boost_payload(a_boost(autofill_text=AUTOFILL))


# --- Questions the customer taps ------------------------------------------
QUESTIONS = ("Menyuni ko'rsam bo'ladimi?", "Yetkazib berish bormi?")


def test_questions_replace_the_pretyped_line() -> None:
    """Meta's welcome screen holds one ``customer_action_type``. A customer
    offered both would see a box already filled under buttons that fill it
    again."""
    sent = json.loads(
        welcome_message(
            a_spec(
                welcome_text=GREETING,
                autofill_text=AUTOFILL,
                welcome_questions=QUESTIONS,
            )
        )
    )

    assert sent["text_format"] == {
        "customer_action_type": "ice_breakers",
        "message": {
            "text": GREETING,
            "ice_breakers": [{"title": question} for question in QUESTIONS],
            "quick_replies": [],
        },
    }


def test_no_questions_keeps_the_pretyped_line() -> None:
    sent = json.loads(
        welcome_message(a_spec(welcome_text=GREETING, autofill_text=AUTOFILL))
    )

    assert sent["text_format"]["customer_action_type"] == "autofill_message"
    assert "ice_breakers" not in sent["text_format"]["message"]


def test_questions_without_a_greeting_send_nothing() -> None:
    """Meta draws the questions under the greeting; with none, its own
    default stands, as it did before questions existed."""
    assert welcome_message(a_spec(welcome_questions=QUESTIONS)) == ""


def test_a_promoted_post_carries_the_questions_too() -> None:
    payload = boost_payload(a_boost(welcome_text=GREETING, welcome_questions=QUESTIONS))

    assert payload["page_welcome_message"] == welcome_message(
        a_spec(welcome_text=GREETING, welcome_questions=QUESTIONS)
    )
    assert "ice_breakers" in payload["page_welcome_message"]


@pytest.mark.parametrize(
    "questions",
    [("x" * 81,), ("   ",), ("a", "b", "c", "d", "e")],
    ids=["too-long", "blank", "too-many"],
)
def test_a_question_meta_would_refuse_is_refused_here(
    questions: tuple[str, ...],
) -> None:
    """Refused before anything is created: the campaign and ad set exist
    by the time the creative is sent."""
    with pytest.raises(ValueError):
        a_spec(welcome_questions=questions)
    with pytest.raises(ValueError):
        a_boost(welcome_questions=questions)
