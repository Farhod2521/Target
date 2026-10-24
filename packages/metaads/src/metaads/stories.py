"""The creative: an object story spec, which is what Meta calls an advert."""

import json
from typing import Any, Final

from metaads.client import GraphClient
from metaads.specs import CTA_NO_BUTTON, TEL_SCHEME, CarouselCard, CreativeSpec
from metaads.writing import fake_id, id_of, post_object

_CREATIVE: Final = "creative"

_INSTAGRAM_KEY: Final = "instagram_user_id"

_WELCOME_TYPE: Final = "VISUAL_EDITOR"
_WELCOME_VERSION: Final = 2
_WELCOME_SCREEN: Final = "welcome_message"
_WELCOME_MEDIA: Final = "text"
_WELCOME_ACTION: Final = "autofill_message"
_QUESTIONS_ACTION: Final = "ice_breakers"


def create_creative(
    *,
    account_id: str,
    spec: CreativeSpec,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """One creative, built as an image ad or a video ad by what it carries."""
    if dry_run:
        return fake_id(_CREATIVE)

    data: dict[str, Any] = {
        "name": spec.name,
        "object_story_spec": story_spec(spec),
    }
    if spec.url_tags:
        data["url_tags"] = spec.url_tags

    payload = post_object(
        path=f"{account_id}/adcreatives",
        data=data,
        token=token,
        client=client,
    )
    return id_of(payload)


def story_spec(spec: CreativeSpec) -> dict[str, Any]:
    """The nested object Meta wants, from the flat one we hold."""
    story: dict[str, Any] = {"page_id": spec.page_id}
    if spec.instagram_user_id:
        story[_INSTAGRAM_KEY] = spec.instagram_user_id

    if spec.cards:
        story["link_data"] = _carousel_data(spec)
    elif spec.video_id:
        story["video_data"] = _video_data(spec)
    else:
        story["link_data"] = _link_data(spec)

    return story


def _carousel_data(spec: CreativeSpec) -> dict[str, Any]:
    """Several pictures in one advert: ``link_data`` with a card per picture."""
    return _without_empties(
        {
            "message": spec.message,
            "link": spec.link_url,
            "child_attachments": [_card(spec, card) for card in spec.cards],
            "multi_share_optimized": False,
            "multi_share_end_card": False,
            "call_to_action": _call_to_action(spec),
            "page_welcome_message": welcome_message(spec),
        }
    )


def _card(spec: CreativeSpec, card: CarouselCard) -> dict[str, Any]:
    """One card. A video card names its still as ``picture``."""
    return _without_empties(
        {
            "link": spec.link_url,
            "name": spec.headline,
            "description": spec.description,
            "image_hash": card.image_hash,
            "video_id": card.video_id,
            "picture": card.thumbnail_url if card.video_id else "",
        }
    )


def _link_data(spec: CreativeSpec) -> dict[str, Any]:
    """An image ad. ``name`` is the headline - Meta's word, not a mistake."""
    return _without_empties(
        {
            "message": spec.message,
            "name": spec.headline,
            "description": spec.description,
            "image_hash": spec.image_hash,
            "link": spec.link_url,
            "call_to_action": _call_to_action(spec),
            "page_welcome_message": welcome_message(spec),
        }
    )


def _video_data(spec: CreativeSpec) -> dict[str, Any]:
    """A video ad, with a thumbnail Meta insists on."""
    action = _call_to_action(spec)
    return _without_empties(
        {
            "video_id": spec.video_id,
            "message": spec.message,
            "title": spec.headline,
            "link_description": spec.description if action else "",
            "image_url": spec.thumbnail_url,
            "call_to_action": action,
            "page_welcome_message": welcome_message(spec),
        }
    )


def _call_to_action(spec: CreativeSpec) -> dict[str, Any]:
    """The button, and the one thing behind it."""
    if spec.call_to_action == CTA_NO_BUTTON:
        return {}

    action: dict[str, Any] = {"type": spec.call_to_action}
    if spec.lead_form_id:
        action["value"] = {"lead_gen_form_id": spec.lead_form_id}
    elif spec.app_destination:
        action["value"] = {"app_destination": spec.app_destination}
    elif spec.phone_number:
        action["value"] = {"link": f"{TEL_SCHEME}{spec.phone_number}"}
    else:
        action["value"] = {"link": spec.link_url}
    return action


def welcome_message(spec: CreativeSpec) -> str:
    """What is in the thread before the customer has said anything."""
    return greeting(
        text=spec.welcome_text,
        autofill=spec.autofill_text,
        questions=spec.welcome_questions,
    )


def greeting(*, text: str, autofill: str = "", questions: tuple[str, ...] = ()) -> str:
    """The greeting itself, for whichever creative carries it."""
    if not text:
        return ""

    message: dict[str, Any] = {"text": text}
    action = _WELCOME_ACTION
    if questions:
        action = _QUESTIONS_ACTION
        message["ice_breakers"] = [{"title": question} for question in questions]
        message["quick_replies"] = []
    elif autofill:
        message["autofill_message"] = {"content": autofill}

    return json.dumps(
        {
            "type": _WELCOME_TYPE,
            "version": _WELCOME_VERSION,
            "landing_screen_type": _WELCOME_SCREEN,
            "media_type": _WELCOME_MEDIA,
            "text_format": {
                "customer_action_type": action,
                "message": message,
            },
        },
        ensure_ascii=False,
    )


def _without_empties(block: dict[str, Any]) -> dict[str, Any]:
    """Absent rather than blank."""
    return {key: value for key, value in block.items() if value not in (None, "", {})}
