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
from collections.abc import Mapping
from typing import Any, Final

from adskit.errors import InvalidRequest

from metaads.client import GraphClient
from metaads.writing import fake_id, id_of, post_object

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
) -> dict[str, Any]:
    """One story spec with new words, picture or form, and nothing else moved.

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


def restageable(story: Any) -> bool:
    """Whether this stored story has a block new words could go into."""
    try:
        _block_of(story)
    except InvalidRequest:
        return False
    return True


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
) -> str:
    """One creative from a story spec that is already built.

    The sibling of :func:`metaads.stories.create_creative`, and the same
    call underneath. That one assembles the block from a flat spec this
    product wrote; this one is handed a block that came back from Meta and
    was edited in place, so there is nothing left to assemble.
    """
    if dry_run:
        return fake_id(_CREATIVE)

    payload = post_object(
        path=f"{account_id}/adcreatives",
        data={"name": name, "object_story_spec": dict(story)},
        token=token,
        client=client,
    )
    return id_of(payload)


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


__all__ = ["changed", "create_from_story", "restage"]
