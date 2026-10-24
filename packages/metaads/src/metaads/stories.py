"""The creative: an object story spec, which is what Meta calls an advert.

Its own module because the shape is the awkward part of the whole write
side. A creative is not a flat object - it is a page id wrapped around one
of two differently-named blocks, and Meta gives the same three fields
different names in each:

======================  ==================  ===================
what it is              image (link_data)   video (video_data)
======================  ==================  ===================
the headline            ``name``            ``title``
the line under it       ``description``     ``link_description``
the picture             ``image_hash``      ``image_url``
======================  ==================  ===================

Code written from memory gets that table wrong, and the failure is not a
rejection: Meta accepts a creative with an unexpected key inside the block
and produces an ad with an empty headline.

The ``link`` is not decoration and is not ours to invent. Meta wants one on
every creative, never follows it on a lead ad - the tap opens the form -
and still refuses the creative when it points back at a page. So the
destination arrives on the spec, which is where it is checked.

Three more kinds of ad live in the same two blocks and differ only in what
the button carries. A messaging ad hands the person to Messenger, Instagram
Direct or WhatsApp instead of following a link, and what is already written
in that thread when they get there is a field beside the picture. A call ad
carries a ``tel:`` URI in the very key the others put an address in. And an
awareness ad carries no button at all - which is a value Meta has a word
for, not an omission, because an omitted call to action is one Meta fills
in with a link.

All of them are below, and none of them is a second story spec.
"""

import json
from typing import Any, Final

from metaads.client import GraphClient
from metaads.specs import CTA_NO_BUTTON, TEL_SCHEME, CarouselCard, CreativeSpec
from metaads.writing import fake_id, id_of, post_object

_CREATIVE: Final = "creative"

# What Meta calls the Instagram account inside an object story spec, at
# this version. It was ``instagram_actor_id`` until v22.0 and that spelling
# was retired for every version on 2025-09-09 - the v26.0 reference lists
# only this one. Named here because the failure is silent: an unknown key
# inside a nested spec is dropped rather than refused, so the creative is
# built, the ad runs, and it runs as the page instead of the account.
_INSTAGRAM_KEY: Final = "instagram_user_id"

# The shape Meta reads a welcome message in. Four constants that mean
# nothing on their own and are refused if any of them is wrong - which is
# the same trap as the headline table above, and the reason they are named
# here rather than written inline at the one place they are used.
_WELCOME_TYPE: Final = "VISUAL_EDITOR"
_WELCOME_VERSION: Final = 2
_WELCOME_SCREEN: Final = "welcome_message"
_WELCOME_MEDIA: Final = "text"
# Which of the welcome screen's shapes this is. Meta has several -
# icebreakers the customer taps, a flow, a call prompt - and this is the
# plain one: the business says something, and the customer's own box opens
# with a sentence already in it.
_WELCOME_ACTION: Final = "autofill_message"
# The other shape: questions under the greeting that the customer taps
# instead of typing. Meta's example sends an empty ``quick_replies`` beside
# them, and so does this.
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
    # Beside the story rather than inside it. Meta reads the tag string off
    # the creative itself and appends it to whatever address the story
    # carries, so a copy nested in the story would be ignored in silence.
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
    """The nested object Meta wants, from the flat one we hold.

    Exported rather than private because it is worth asserting on: the
    table in this module's docstring is the kind of thing that stays true
    only while a test says so.
    """
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
    """Several pictures in one advert: ``link_data`` with a card per picture.

    The words, the button and the address are the advert's and sit once,
    beside the cards. Each card repeats the address because Meta requires
    it there too ("``link``: Required"), and carries the headline and the
    line under it so every card reads the same.

    **The order is kept.** ``multi_share_optimized`` is Meta's licence to
    reorder the cards by performance and defaults to on; a carousel that
    was an Instagram post is a sequence its owner put together, so it is
    turned off - and so is the end card Meta appends by default.
    """
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
    """A video ad, with a thumbnail Meta insists on.

    ``image_url`` is not optional here even though the video already has
    frames: without it Meta refuses the creative, and the URL has to come
    from the caller because the thumbnail only exists once the upload has
    finished processing.

    ``link_description`` only beside a button. It is the line under the
    button's link, and Meta refuses a video that carries one without a
    call to action (``100/1815614``) - which is every video on a goal
    that has no button.
    """
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
    """The button, and the one thing behind it.

    Five kinds of ad, one key, and exactly one value in it. A lead ad's
    button carries the form id; a messaging ad's carries the surface the
    conversation opens on; a call ad's carries a ``tel:`` URI; everything
    else carries a link. Sending two is how an ad ends up opening a website
    instead of the thing it was built for - and that failure is silent,
    because the ad runs.

    The fifth kind has no button. ``NO_BUTTON`` is Meta's own word for it
    and the block disappears entirely, which is **not** the same as leaving
    the block out and hoping: an absent call to action is one Meta supplies,
    and what it supplies is a link. An awareness ad bought on impressions
    would then carry a button to whatever address the creative happened to
    be filled with.

    The order is the order of specificity and not a preference. A lead ad
    that also names a messaging surface is a spec nobody should have built,
    and the form is the half of it that cost a call nothing can take back.

    The last branch is the dangerous one and it is dangerous by being the
    reasonable one. Every ad whose button was not explicitly given
    something else falls into it and gets a link - which is right for a
    traffic ad and silently wrong for a call or a messaging preset that
    reaches it by accident.
    """
    if spec.call_to_action == CTA_NO_BUTTON:
        return {}

    action: dict[str, Any] = {"type": spec.call_to_action}
    if spec.lead_form_id:
        action["value"] = {"lead_gen_form_id": spec.lead_form_id}
    elif spec.app_destination:
        action["value"] = {"app_destination": spec.app_destination}
    elif spec.phone_number:
        # The number, as a URI, in the key an ordinary ad puts an address
        # in. The creative's own ``link`` stays what it was - Meta's own
        # example leaves the business's page there - because on this ad it
        # is the same formality it is on a lead ad: nobody follows it, the
        # tap dials.
        action["value"] = {"link": f"{TEL_SCHEME}{spec.phone_number}"}
    else:
        action["value"] = {"link": spec.link_url}
    return action


def welcome_message(spec: CreativeSpec) -> str:
    """What is in the thread before the customer has said anything.

    Exported for the same reason ``story_spec`` is: the nesting below is
    four levels of Meta's own vocabulary, every level of it required, and
    the kind of thing that stays right only while a test says so.

    **A JSON string, not an object.** Meta types this field as a string
    and describes it as "a JSON object passed as a string", while the
    click-to-Messenger guide's own example nests it as an object. The
    field reference is what is followed here, because it is the half of
    the documentation that is about the type.

    Empty when there is no greeting to send, and that is a working ad
    rather than a blank one: with the field absent Meta writes its own
    greeting. Which is also why the greeting alone decides - a spec
    carrying only the autofill line would open a thread with words in the
    customer's mouth and none in the business's.
    """
    return greeting(
        text=spec.welcome_text,
        autofill=spec.autofill_text,
        questions=spec.welcome_questions,
    )


def greeting(*, text: str, autofill: str = "", questions: tuple[str, ...] = ()) -> str:
    """The greeting itself, for whichever creative carries it.

    Its own function because two shapes send the same JSON in two places:
    a new post nests it in ``link_data`` or ``video_data``, and a post
    promoted where it stands sends it as a field of the creative itself -
    see :mod:`metaads.boosts`.
    """
    if not text:
        return ""

    # Questions replace the pre-typed line rather than joining it: the
    # welcome screen takes one ``customer_action_type``, and a customer
    # offered both would see a box already filled under buttons that fill
    # it again. Each goes as a title alone - the answer is the business's
    # to type in the thread, not a canned reply.
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
    """Absent rather than blank.

    An empty ``description`` inside a story spec is not the same as no
    description: Meta renders the first as a blank line under the headline
    on some placements and omits the row entirely for the second.
    """
    return {key: value for key, value in block.items() if value not in (None, "", {})}
