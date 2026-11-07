"""TZ 2.5: a chat advert's greeting, read and rewritten in place.

The greeting is ``page_welcome_message`` inside the story block: a JSON
object passed as a string (see :func:`metaads.stories.welcome_message`).
What Ads Manager writes there is far more than this product does - a
re-engagement line, an automatic follow-up, the same text again for the
image and video layouts. Rewriting it from scratch would drop all of that,
so only three things are written over what came back: the greeting's text,
the quick questions, and the answer sent to each.

``template_id`` is taken out when anything changes. It names a saved
template in Ads Manager, and a greeting that says something else is no
longer that template.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from adskit.errors import InvalidRequest

from metaads.specs import MAX_QUESTION_CHARS, MAX_WELCOME_QUESTIONS
from metaads.stories import greeting

FIELD: Final = "page_welcome_message"
_QUESTIONS: Final = "ice_breakers"
_AUTOFILL: Final = "autofill_message"
# The layouts that carry the greeting's text a second time.
_LAYOUTS: Final = ("text_format", "image_format", "video_format")
_TEMPLATE: Final = "template_id"


@dataclass(frozen=True, slots=True)
class Question:
    """One quick question, and the answer sent when it is tapped (may be empty)."""

    title: str
    response: str = ""


@dataclass(frozen=True, slots=True)
class Welcome:
    text: str
    questions: tuple[Question, ...] = ()


def _parsed(raw: Any) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            found = json.loads(raw)
        except ValueError:
            return {}
        return found if isinstance(found, dict) else {}
    return {}


def read(block: Mapping[str, Any]) -> Welcome:
    """The greeting this block opens a chat with; empty when Meta writes its own."""
    message = (_parsed(block.get(FIELD)).get("text_format") or {}).get("message") or {}
    questions = tuple(
        Question(
            title=str(row.get("title") or ""),
            response=str(row.get("response") or ""),
        )
        for row in message.get(_QUESTIONS) or ()
        if isinstance(row, Mapping) and row.get("title")
    )
    return Welcome(text=str(message.get("text") or ""), questions=questions)


def checked(welcome: Welcome) -> Welcome:
    """Refuse what Meta would refuse, before a creative is made."""
    if len(welcome.questions) > MAX_WELCOME_QUESTIONS:
        raise InvalidRequest(
            f"at most {MAX_WELCOME_QUESTIONS} quick questions", code="welcome"
        )
    for row in welcome.questions:
        if not row.title.strip():
            raise InvalidRequest("a quick question cannot be blank", code="welcome")
        if len(row.title) > MAX_QUESTION_CHARS:
            raise InvalidRequest(
                f"a quick question is at most {MAX_QUESTION_CHARS} characters",
                code="welcome",
            )
    if welcome.questions and not welcome.text.strip():
        raise InvalidRequest("quick questions need a greeting", code="welcome")
    return welcome


def put(block: dict[str, Any], welcome: Welcome) -> None:
    """The greeting written into an already copied block."""
    checked(welcome)
    if not welcome.text.strip():
        block.pop(FIELD, None)
        return
    found = _parsed(block.get(FIELD))
    if not found:
        found = json.loads(greeting(text=welcome.text))
    found.pop(_TEMPLATE, None)
    for layout in _LAYOUTS:
        shape = found.get(layout)
        if isinstance(shape, dict) and isinstance(shape.get("message"), dict):
            shape["message"]["text"] = welcome.text
    text_format = found.setdefault("text_format", {})
    message = text_format.setdefault("message", {})
    message["text"] = welcome.text
    if welcome.questions:
        text_format["customer_action_type"] = _QUESTIONS
        message[_QUESTIONS] = [_question(row) for row in welcome.questions]
        message.setdefault("quick_replies", [])
        message.pop(_AUTOFILL, None)
    else:
        message.pop(_QUESTIONS, None)
        if text_format.get("customer_action_type") == _QUESTIONS:
            text_format["customer_action_type"] = _AUTOFILL
    block[FIELD] = json.dumps(found, ensure_ascii=False)


def _question(row: Question) -> dict[str, str]:
    asked = {"title": row.title}
    if row.response.strip():
        asked["response"] = row.response
    return asked


def from_rows(text: str, rows: Sequence[Mapping[str, Any]]) -> Welcome:
    """A greeting from the API's plain values."""
    return Welcome(
        text=text,
        questions=tuple(
            Question(
                title=str(row.get("title") or ""),
                response=str(row.get("response") or ""),
            )
            for row in rows
        ),
    )


__all__ = [
    "FIELD",
    "Question",
    "Welcome",
    "checked",
    "from_rows",
    "put",
    "read",
]
