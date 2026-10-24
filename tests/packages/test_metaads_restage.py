"""metaads/restage.py: the same advert, saying something else.

Meta does not allow a creative to be edited, so every one of these is about
building a second one from the first without losing what nobody touched.
The failure this file is mostly written against is the silent one: Meta
accepts an unknown key inside a story block rather than refusing it, so a
headline written under the wrong name produces an advert with no headline
and no error anywhere.
"""

from typing import Any

import pytest
from adskit.errors import InvalidRequest
from metaads.restage import changed, restage


def a_still() -> dict[str, Any]:
    """A creative built from a picture, as Meta hands it back."""
    return {
        "page_id": "111",
        "instagram_user_id": "222",
        "link_data": {
            "message": "Yangi menyu",
            "name": "Bugun ochiq",
            "description": "Yetkazib berish bepul",
            "image_hash": "abc123",
            "link": "https://osh.uz",
            "call_to_action": {
                "type": "SIGN_UP",
                "value": {"lead_gen_form_id": "form-9"},
            },
        },
    }


def a_moving() -> dict[str, Any]:
    """The other block, where all three words have different names."""
    return {
        "page_id": "111",
        "video_data": {
            "video_id": "vid-1",
            "message": "Yangi menyu",
            "title": "Bugun ochiq",
            "link_description": "Yetkazib berish bepul",
            "image_url": "https://cdn/thumb.jpg",
            "call_to_action": {"type": "LEARN_MORE"},
        },
    }


# --- The words -----------------------------------------------------------
def test_a_new_headline_lands_under_metas_name_for_it() -> None:
    """``name`` inside ``link_data``, which is the field most likely to be
    got wrong by anything written from memory - and getting it wrong is not
    a refusal, it is an advert with an empty headline."""
    after = restage(a_still(), headline="Ertaga ham ochiq")

    assert after["link_data"]["name"] == "Ertaga ham ochiq"


def test_the_same_headline_lands_under_a_different_name_on_a_video() -> None:
    after = restage(a_moving(), headline="Ertaga ham ochiq")

    assert after["video_data"]["title"] == "Ertaga ham ochiq"
    assert "name" not in after["video_data"]


def test_what_was_not_asked_about_is_left_exactly_as_it_was() -> None:
    """The whole reason this works from the provider's block rather than
    from our columns. The button, the form buried inside it and the
    Instagram account are all things no screen here shows and all things an
    advert stops working without."""
    after = restage(a_still(), message="Boshqa gap")

    assert after["link_data"]["call_to_action"] == {
        "type": "SIGN_UP",
        "value": {"lead_gen_form_id": "form-9"},
    }
    assert after["link_data"]["link"] == "https://osh.uz"
    assert after["instagram_user_id"] == "222"
    assert after["link_data"]["name"] == "Bugun ochiq"


def test_an_empty_answer_takes_the_line_out() -> None:
    """Different from not being asked, and both are needed: a form that
    sends every field on every save must be able to leave a headline alone,
    and somebody must be able to remove a description."""
    after = restage(a_still(), description="")

    assert "description" not in after["link_data"]


def test_not_being_asked_is_not_an_empty_answer() -> None:
    after = restage(a_still(), message="Boshqa gap")

    assert after["link_data"]["description"] == "Yetkazib berish bepul"


# --- The picture ---------------------------------------------------------
def test_a_new_picture_replaces_the_hash_and_nothing_else() -> None:
    after = restage(a_still(), image_hash="def456")

    assert after["link_data"]["image_hash"] == "def456"
    assert after["link_data"]["message"] == "Yangi menyu"


def test_swapping_a_picture_for_a_video_moves_the_words_with_it() -> None:
    """The one operation the naming table exists for. A block that kept
    ``name`` beside its new ``title`` would be accepted by Meta and rendered
    as an advert with two headlines."""
    after = restage(a_still(), video_id="vid-2", thumbnail_url="https://cdn/two.jpg")

    assert "link_data" not in after
    assert after["video_data"]["title"] == "Bugun ochiq"
    assert after["video_data"]["link_description"] == "Yetkazib berish bepul"
    assert after["video_data"]["video_id"] == "vid-2"
    assert after["video_data"]["image_url"] == "https://cdn/two.jpg"
    assert "image_hash" not in after["video_data"]


def test_swapping_a_video_for_a_picture_carries_the_button_across() -> None:
    """Both directions, because the button is what makes an advert do
    anything at all and it is named identically in the two blocks - which
    is exactly why it is easy to drop when the block is rebuilt."""
    after = restage(a_moving(), image_hash="abc123")

    assert "video_data" not in after
    assert after["link_data"]["name"] == "Bugun ochiq"
    assert after["link_data"]["call_to_action"] == {"type": "LEARN_MORE"}
    assert "video_id" not in after["link_data"]
    assert "image_url" not in after["link_data"]


def test_the_original_story_is_never_edited() -> None:
    """It is the mirror row, and the only record of what the advert used to
    say. Meta does not keep deleted creatives."""
    story = a_still()

    restage(story, headline="Boshqa", image_hash="def456")

    assert story["link_data"]["name"] == "Bugun ochiq"
    assert story["link_data"]["image_hash"] == "abc123"


# --- Nothing to work from ------------------------------------------------
def test_a_promoted_post_cannot_be_restaged() -> None:
    """Its words live on the post. Meta names such a creative with
    ``object_story_id`` and gives it no spec at all, so there is nothing
    here to copy and a guessed block would replace an advert with an empty
    one."""
    with pytest.raises(InvalidRequest):
        restage({"page_id": "111"}, headline="Boshqa")


def test_a_creative_we_have_not_mirrored_cannot_be_restaged() -> None:
    with pytest.raises(InvalidRequest):
        restage({}, headline="Boshqa")


# --- Whether it says anything different ----------------------------------
def test_saving_the_same_words_changes_nothing() -> None:
    """An unchanged save is not a wasted call - a creative cannot be
    edited, so it is a second advert on the account saying exactly what the
    first one says, with the spend split between them."""
    story = a_still()

    assert not changed(story, headline="Bugun ochiq", message="Yangi menyu")


def test_one_different_word_is_a_change() -> None:
    assert changed(a_still(), headline="Ertaga ochiq")


def test_a_blank_field_meta_returned_is_not_a_change() -> None:
    """Meta hands back an empty description on creatives that never had
    one. Comparing against the raw block would call every such advert
    changed the moment anybody opened the form."""
    story = a_still()
    story["link_data"]["description"] = ""

    assert not changed(story, message="Yangi menyu")


# --- The form --------------------------------------------------------------
def test_a_new_form_goes_behind_the_same_button() -> None:
    """Only the form id moves: the button's kind and the rest stay."""
    after = restage(a_still(), lead_form_id="form-10")

    assert after["link_data"]["call_to_action"] == {
        "type": "SIGN_UP",
        "value": {"lead_gen_form_id": "form-10"},
    }
    assert after["link_data"]["name"] == "Bugun ochiq"
    assert after["link_data"]["image_hash"] == "abc123"


def test_the_story_handed_in_is_not_changed() -> None:
    story = a_still()

    restage(story, lead_form_id="form-10")

    assert story["link_data"]["call_to_action"]["value"]["lead_gen_form_id"] == (
        "form-9"
    )


def test_an_advert_with_no_form_is_not_given_one() -> None:
    """A link advert given a form is another kind of advert."""
    with pytest.raises(InvalidRequest):
        restage(a_moving(), lead_form_id="form-10")


def test_a_new_form_is_a_change() -> None:
    assert changed(a_still(), lead_form_id="form-10")
    assert not changed(a_still(), lead_form_id="form-9")
