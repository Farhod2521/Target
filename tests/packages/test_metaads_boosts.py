"""The other creative shape: a post that already exists.

Two flat fields where the whole of :mod:`metaads.stories` has a nested
block, and the pair are alternatives rather than variations. What is pinned
here is the difference, because the two are alike enough to be written into
each other by accident and Meta reports that accident by running the wrong
ad rather than by refusing anything.

The button is pinned hardest, because both of its rules were learned from
a live account rather than read. A lead form works on this route, which the
documentation does not say; and it only works with a ``link`` beside it,
which the documentation does not say either - and the same refusal came
back for a messaging button, so the link belongs to the route rather than
to lead ads.

Nothing here reaches a network.
"""

from typing import Any

import pytest
from metaads.boosts import BoostSpec, boost_payload
from metaads.specs import CTA_NO_BUTTON, CTA_SIGN_UP
from pydantic import ValidationError

FORM = "1234567890"
POST = "17999888777"
SITE = "https://osh.uz/"


def a_spec(**extra: Any) -> BoostSpec:
    fields: dict[str, Any] = {
        "page_id": "99",
        "instagram_user_id": "77",
        "media_id": POST,
    }
    return BoostSpec(**(fields | extra))


def with_form(**extra: Any) -> BoostSpec:
    """The shape the product sends: a form, and the link Meta insists on."""
    return a_spec(call_to_action=CTA_SIGN_UP, lead_form_id=FORM, link_url=SITE, **extra)


# --- Which post, and whose ------------------------------------------------
def test_the_page_travels_as_object_id_and_not_as_page_id() -> None:
    """The one rename between the two shapes. ``page_id`` is what a story
    spec calls it, this route calls it ``object_id``, and a payload
    carrying the story spec's word names no page at all."""
    payload = boost_payload(a_spec())

    assert payload["object_id"] == "99"
    assert "page_id" not in payload


def test_the_profile_is_named_beside_the_page() -> None:
    """Both, always. The page is what buys the ad and the profile is what
    it runs as, and Meta's own guide sends the two together."""
    payload = boost_payload(a_spec())

    assert payload["instagram_user_id"] == "77"
    assert payload["source_instagram_media_id"] == POST


def test_no_story_spec_is_ever_built_here() -> None:
    """The silent failure this module exists to avoid. Meta accepts a
    creative carrying both a story spec and a source media id, and what it
    advertises is the story spec - a new, empty post beside the chosen
    one."""
    payload = boost_payload(with_form())

    assert "object_story_spec" not in payload


def test_the_destination_never_travels_as_object_url() -> None:
    """The obvious first guess, and Meta refuses the creative for it:
    ``100/1487929`` - ``object_url`` and ``source_instagram_media_id`` are
    two promoted objects, and a creative may name one."""
    assert "object_url" not in boost_payload(with_form())


# --- The button -----------------------------------------------------------
def test_the_form_and_the_link_ride_together_in_the_button() -> None:
    """The answer the probe came back with, as an object.

    Two things in one slot, which is the opposite of the rule
    ``metaads.stories`` lives under - there, a link beside a form id is how
    an ad silently opens a website instead of the form."""
    payload = boost_payload(with_form())

    assert payload["call_to_action"] == {
        "type": CTA_SIGN_UP,
        "value": {"link": SITE, "lead_gen_form_id": FORM},
    }


def test_a_button_without_a_link_is_refused_before_meta_sees_it() -> None:
    """``100/2061015``, blaming ``link``. Refused at construction because
    this object is built after the campaign, the ad set and the form
    already exist - and the form is what a rollback cannot remove."""
    with pytest.raises(ValidationError):
        a_spec(call_to_action=CTA_SIGN_UP, lead_form_id=FORM)


def test_the_link_is_required_for_a_conversation_too() -> None:
    """The refusal that proved the rule is the route's rather than the lead
    form's: a messaging button with no link came back with the same code."""
    with pytest.raises(ValidationError):
        a_spec(call_to_action="MESSAGE_PAGE", app_destination="MESSENGER")


def test_a_conversation_and_a_form_stay_exclusive() -> None:
    """The link is shared; the destination is not. A spec naming both is
    one nobody should have built, and the form is the half that cost a
    call which cannot be taken back."""
    value = boost_payload(with_form(app_destination="MESSENGER"))["call_to_action"][
        "value"
    ]

    assert value == {"link": SITE, "lead_gen_form_id": FORM}


def test_no_button_is_asked_for_and_none_is_sent() -> None:
    """A post promoted as it stands. Unlike a story spec, there is nothing
    for Meta to fall back to here - the creative carries no link at all -
    so the absent block is the ad rather than a hole in it."""
    assert "call_to_action" not in boost_payload(a_spec())
    assert "call_to_action" not in boost_payload(a_spec(call_to_action=CTA_NO_BUTTON))
