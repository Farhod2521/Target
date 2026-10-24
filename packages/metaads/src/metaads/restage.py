"""The same advert, saying something else."""

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

_WORDS: Final[dict[str, dict[str, str]]] = {
    _LINK: {"message": "message", "headline": "name", "description": "description"},
    _VIDEO: {
        "message": "message",
        "headline": "title",
        "description": "link_description",
    },
}

_PICTURE: Final[dict[str, tuple[str, ...]]] = {
    _LINK: ("image_hash",),
    _VIDEO: ("video_id", "image_url"),
}

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
    """One story spec with new words, picture or form, and nothing else moved."""
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


def changed(story: Mapping[str, Any], **asked: Any) -> bool:
    """Whether restaging with these answers would say anything different."""
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
    """One creative from a story spec that is already built."""
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
    """Which of the two blocks this story carries, and a copy of it."""
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
    """The story as :func:`restage` would rewrite it having changed nothing."""
    return restage(story)


__all__ = ["changed", "create_from_story", "restage"]
