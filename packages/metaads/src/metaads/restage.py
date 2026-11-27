"""The same advert, saying something else.

Meta does not allow a creative to be edited. Not the words, not the
picture, not the button - the object is immutable from the moment it is
created, and every screen that appears to change one is building another.
So "change what this advert says" is not an update anywhere in this
package; it is a second creative made from the first, and a second ad
pointing at it.

**Built from the provider's own block rather than from our columns.** The
mirror keeps a creative's words, its picture and its button in named
columns, and rebuilding from those would send back only what this product
happens to model - dropping the welcome message, the app destination, the
lead form buried four levels inside the button, and anything Meta adds
next year. What is kept instead is ``object_story_spec`` exactly as it
came, with the two or three fields somebody actually changed written over
the top of it.

The awkward part is the same one :mod:`metaads.stories` documents: the
three words have different names in the two blocks, and Meta accepts an
unknown key inside a block rather than refusing it. Writing a headline
under the wrong name produces an advert with an empty headline and no
error anywhere. The table is therefore data here, not prose, and switching
a picture from a still to a video moves the words from one set of names to
the other.
"""

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from adskit.errors import InvalidRequest

from metaads import welcome as greeting
from metaads.client import GraphClient
from metaads.enhancements import post_creative
from metaads.welcome import Welcome
from metaads.writing import fake_id, graph_client

_CREATIVE: Final = "creative"

_LINK: Final = "link_data"
_VIDEO: Final = "video_data"
_BLOCKS: Final = (_LINK, _VIDEO)

# What each of the three words is called inside each block - the table in
# :mod:`metaads.stories`'s docstring, as data. Two readers of one shape is
# one too many, and this is the reader that has to *move* a word from one
# spelling to the other when the picture changes kind.
_WORDS: Final[dict[str, dict[str, str]]] = {
    _LINK: {"message": "message", "headline": "name", "description": "description"},
    _VIDEO: {
        "message": "message",
        "headline": "title",
        "description": "link_description",
    },
}

# What names the picture in each block. A still is one key; a video is two,
# because Meta refuses a video creative that carries no thumbnail even
# though the video plainly has frames of its own.
_PICTURE: Final[dict[str, tuple[str, ...]]] = {
    _LINK: ("image_hash",),
    _VIDEO: ("video_id", "image_url"),
}

# Every key this module writes, under either spelling. Cleared out of the
# block before the new values go in, so a creative that was a video and is
# now a still does not keep ``title`` beside its new ``name`` - which Meta
# would accept, and render as an advert with two headlines.
_REWRITTEN: Final[frozenset[str]] = frozenset(
    name for table in _WORDS.values() for name in table.values()
) | frozenset(name for names in _PICTURE.values() for name in names)


_CARDS: Final = "child_attachments"
MIN_CARDS: Final = 2
MAX_CARDS: Final = 10
_URL_TAGS: Final = "url_tags"


@dataclass(frozen=True, slots=True)
class Card:
    """One card of a carousel as it is asked to be.

    ``source`` is the place the card holds now, counted from nought; ``None``
    is a card that is not there yet. A word left ``None`` stays as the card
    has it. A new card has no picture of its own, so it must be given one.
    """

    source: int | None = None
    headline: str | None = None
    description: str | None = None
    image_hash: str = ""


def restage(
    story: Mapping[str, Any],
    *,
    message: str | None = None,
    headline: str | None = None,
    description: str | None = None,
    image_hash: str = "",
    video_id: str = "",
    thumbnail_url: str = "",
    lead_form_id: str = "",
    button: str = "",
    welcome: Welcome | None = None,
    link: str = "",
    cards: Sequence[Card] | None = None,
) -> dict[str, Any]:
    """One story spec with new words, picture, form or button, and nothing else moved.

    ``None`` is "not asked about" and an empty string is "take that line
    out". The two have to be different: a form that sends every field on
    every save would otherwise wipe a headline nobody touched, and one that
    could not send an empty value could never remove a description.

    Everything the caller did not name is carried over as it was - the
    link, the button and whatever is nested inside it, the welcome message,
    the Instagram account the advert runs as. That is the whole reason this
    takes the provider's block instead of our own columns.

    ``lead_form_id`` puts another instant form behind the button. Only on
    an advert that already opens one: giving a link advert a form changes
    what kind of advert it is, which is a new campaign's question, so that
    is refused rather than quietly built.

    ``button`` changes the button's word (TZ 2.3) and keeps its ``value``:
    the link, the form or the chat it opens stays the same.

    ``welcome`` rewrites a chat advert's greeting, its quick questions and
    their answers (TZ 2.5); see :mod:`metaads.welcome`.

    ``link`` sends the person somewhere else. Only on an advert that leads
    to a site: a form, a chat and a call each carry an address that is not
    the owner's to change, and writing over it breaks the advert without an
    error from anyone.

    ``cards`` is a carousel's cards in the order wanted: kept, moved, taken
    out, reworded, given another picture, or new. Only on a creative that
    is a carousel already.

    Raises :class:`~adskit.errors.InvalidRequest` when there is no block to
    work from. Two creatives answer that way and both are real: one that
    promotes a post somebody published - its words live on the post, and
    Meta names it ``object_story_id`` with no spec at all - and one this
    product has not mirrored yet. Neither can be restaged, and guessing a
    block for them would replace an advert with an empty one.
    """
    kind, block = _block_of(story)

    words = _words_in(block, kind=kind)
    for name, asked in (
        ("message", message),
        ("headline", headline),
        ("description", description),
    ):
        if asked is not None:
            words[name] = asked

    picture = _picture_in(block, kind=kind)
    if video_id:
        kind, picture = _VIDEO, {"video_id": video_id, "image_url": thumbnail_url}
    elif image_hash:
        kind, picture = _LINK, {"image_hash": image_hash}

    rebuilt = {key: value for key, value in block.items() if key not in _REWRITTEN}
    for name, value in words.items():
        if value:
            rebuilt[_WORDS[kind][name]] = value
    rebuilt.update({key: value for key, value in picture.items() if value})
    if lead_form_id:
        _put_form(rebuilt, lead_form_id)
    if button:
        _put_button(rebuilt, button)
    if welcome is not None:
        greeting.put(rebuilt, welcome)
    if cards is not None:
        _put_cards(rebuilt, cards)
    if link:
        _put_link(rebuilt, link)

    revised = {key: value for key, value in dict(story).items() if key not in _BLOCKS}
    revised[kind] = rebuilt
    return revised


def _put_form(block: dict[str, Any], lead_form_id: str) -> None:
    """The form behind the button replaced, inside an already copied block."""
    button = block.get("call_to_action")
    if not isinstance(button, dict):
        button = {}
    value = button.get("value")
    if not isinstance(value, dict) or not value.get("lead_gen_form_id"):
        raise InvalidRequest(
            "this advert does not open an instant form", code="restage_form"
        )
    block["call_to_action"] = {
        **button,
        "value": {**value, "lead_gen_form_id": lead_form_id},
    }


def _put_button(block: dict[str, Any], button: str) -> None:
    """Another word on the button; where it leads stays as it was."""
    current = block.get("call_to_action")
    if not isinstance(current, dict) or not current.get("type"):
        raise InvalidRequest("this advert carries no button", code="restage_button")
    block["call_to_action"] = {**current, "type": button}


def _put_link(block: dict[str, Any], link: str) -> None:
    """Another address, everywhere the block names the one it had.

    The address sits in up to three places - the block, the button and each
    card - and Meta opens whichever the placement reads. One left behind is
    an advert that leads to two sites.
    """
    held = link_of_block(block)
    if not held:
        raise InvalidRequest("this advert does not lead to a site", code="restage_link")
    if block.get("link"):
        block["link"] = link
    moved = _button_to(block.get("call_to_action"), link=link)
    if moved is not None:
        block["call_to_action"] = moved
    rows = block.get(_CARDS)
    if isinstance(rows, list):
        block[_CARDS] = [_card_with_link(row, held=held, link=link) for row in rows]


def _card_with_link(row: Any, *, held: str, link: str) -> Any:
    """A card that led where the advert led follows it; one with its own address keeps it."""
    if not isinstance(row, dict):
        return row
    moved = dict(row)
    if moved.get("link") == held:
        moved["link"] = link
    button = _button_to(moved.get("call_to_action"), link=link, only=held)
    if button is not None:
        moved["call_to_action"] = button
    return moved


def _button_to(button: Any, *, link: str, only: str = "") -> dict[str, Any] | None:
    """The button leading to ``link``; None when it names no address to move.

    ``only`` moves it just when it led there: a card with an address of its
    own is not following the advert's.
    """
    value = button.get("value") if isinstance(button, dict) else None
    if not isinstance(value, dict) or not value.get("link"):
        return None
    if only and value["link"] != only:
        return None
    return {**button, "value": {**value, "link": link}}


def link_of_block(block: Mapping[str, Any]) -> str:
    """The site this block leads to; empty when it opens a form, a chat or a call."""
    button = block.get("call_to_action")
    value = button.get("value") if isinstance(button, Mapping) else None
    value = value if isinstance(value, Mapping) else {}
    if value.get("lead_gen_form_id") or value.get("app_destination"):
        return ""
    found = str(value.get("link") or block.get("link") or "")
    return found if found.startswith(("http://", "https://")) else ""


def link_of(story: Any) -> str:
    """The site an advert leads to, ``""`` when it leads to none."""
    try:
        _kind, block = _block_of(story)
    except InvalidRequest:
        return ""
    return link_of_block(block)


def _put_cards(block: dict[str, Any], cards: Sequence[Card]) -> None:
    """The carousel's cards, rebuilt from the ones it has in the order asked."""
    held = block.get(_CARDS)
    if not isinstance(held, list) or not held:
        raise InvalidRequest("this advert is not a carousel", code="restage_cards")
    if not MIN_CARDS <= len(cards) <= MAX_CARDS:
        raise InvalidRequest(
            f"a carousel has {MIN_CARDS}-{MAX_CARDS} cards", code="restage_cards"
        )
    kept = [card.source for card in cards if card.source is not None]
    if len(kept) != len(set(kept)) or any(not 0 <= at < len(held) for at in kept):
        raise InvalidRequest("a card was named that is not there", code="restage_cards")
    block[_CARDS] = [_card(held, card) for card in cards]


def _card(held: list[Any], card: Card) -> dict[str, Any]:
    if card.source is None:
        if not card.image_hash:
            raise InvalidRequest("a new card needs a picture", code="restage_cards")
        # A new card leads where the first one leads and wears its button.
        first = held[0] if isinstance(held[0], dict) else {}
        made: dict[str, Any] = {
            key: copy.deepcopy(first[key])
            for key in ("link", "call_to_action")
            if first.get(key)
        }
    else:
        row = held[card.source]
        made = copy.deepcopy(dict(row)) if isinstance(row, dict) else {}
    for key, asked in (("name", card.headline), ("description", card.description)):
        if asked is None:
            continue
        if asked:
            made[key] = asked
        else:
            made.pop(key, None)
    if card.image_hash:
        # A still in place of whatever the card showed, a video included.
        for key in ("video_id", "picture", "image_url"):
            made.pop(key, None)
        made["image_hash"] = card.image_hash
    return made


def cards_of(story: Any) -> list[dict[str, Any]]:
    """A carousel's cards as Meta holds them; none for any other advert."""
    try:
        _kind, block = _block_of(story)
    except InvalidRequest:
        return []
    rows = block.get(_CARDS)
    return (
        [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    )


def restageable(story: Any) -> bool:
    """Whether this stored story has a block new words could go into."""
    try:
        _block_of(story)
    except InvalidRequest:
        return False
    return True


def button_of(story: Any) -> dict[str, Any]:
    """The story's button as Meta holds it, ``{}`` when it has none."""
    try:
        _kind, block = _block_of(story)
    except InvalidRequest:
        return {}
    found = block.get("call_to_action")
    return found if isinstance(found, dict) else {}


def welcome_of(story: Any) -> Welcome | None:
    """A chat advert's greeting; ``None`` for an advert that opens no chat."""
    if not (button_of(story).get("value") or {}).get("app_destination"):
        return None
    _kind, block = _block_of(story)
    return greeting.read(block)


def changed(story: Mapping[str, Any], **asked: Any) -> bool:
    """Whether restaging with these answers would say anything different.

    The check that keeps a press nobody meant from costing an advert. A
    creative cannot be edited, so an unchanged save is not a wasted call -
    it is a second advert on the account saying exactly what the first one
    says, and a spend split between them.
    """
    return restage(story, **asked) != _normalised(story)


def create_from_story(
    *,
    account_id: str,
    name: str,
    story: Mapping[str, Any],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
    url_tags: str = "",
) -> str:
    """One creative from a story spec that is already built.

    ``url_tags`` is not part of the story: Meta keeps the tracking tags on
    the creative beside it. A creative made from another without them
    reports its visits to nobody's analytics, and says so nowhere.

    The sibling of :func:`metaads.stories.create_creative`, and the same
    call underneath. That one assembles the block from a flat spec this
    product wrote; this one is handed a block that came back from Meta and
    was edited in place, so there is nothing left to assemble.
    """
    if dry_run:
        return fake_id(_CREATIVE)

    return post_creative(
        account_id=account_id,
        data={"name": name, "object_story_spec": dict(story)}
        | ({_URL_TAGS: url_tags} if url_tags else {}),
        token=token,
        client=client,
    )


def read_url_tags(
    *, creative_id: str, token: str, client: GraphClient | None = None
) -> str:
    """The tracking tags a creative carries right now; ``""`` for none."""
    with graph_client(client, token) as graph:
        row = graph.get(creative_id, fields=_URL_TAGS)
    return str(row.get(_URL_TAGS) or "")


def _block_of(story: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    """Which of the two blocks this story carries, and a copy of it.

    Copied deeply on the way out. The button is a nested object and the
    caller's ``story`` is a mirror row somebody may still be reading - a
    restage that edited it in place would change what the screen says the
    advert used to be, which is the one record of that there is.
    """
    if not isinstance(story, Mapping) or not story:
        raise InvalidRequest("there is no stored creative to change", code="restage")

    for kind in _BLOCKS:
        block = story.get(kind)
        if isinstance(block, Mapping) and block:
            return kind, copy.deepcopy(dict(block))

    raise InvalidRequest(
        "this creative carries no story spec to change", code="restage"
    )


def _words_in(block: Mapping[str, Any], *, kind: str) -> dict[str, str]:
    """The three words, under our names rather than under Meta's two sets."""
    return {
        name: str(block.get(spelling) or "") for name, spelling in _WORDS[kind].items()
    }


def _picture_in(block: Mapping[str, Any], *, kind: str) -> dict[str, str]:
    """Whatever names the picture in this block, kept as it is."""
    return {key: str(block.get(key) or "") for key in _PICTURE[kind]}


def _normalised(story: Mapping[str, Any]) -> dict[str, Any]:
    """The story as :func:`restage` would rewrite it having changed nothing.

    Compared against rather than the raw block, because the rewrite drops
    keys that were empty and reorders nothing else. Without this, a
    creative Meta returned with ``"description": ""`` would look changed to
    anybody who left the description alone.
    """
    return restage(story)


__all__ = [
    "MAX_CARDS",
    "MIN_CARDS",
    "Card",
    "button_of",
    "cards_of",
    "changed",
    "create_from_story",
    "link_of",
    "read_url_tags",
    "restage",
    "welcome_of",
]
