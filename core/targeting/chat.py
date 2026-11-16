"""The first line of a conversation the ad is about to open."""

from collections.abc import Iterable
from typing import Final

from core.targeting.contracts import BusinessProfile
from core.targeting.exceptions import TargetingError
from core.targeting.presets import Preset
from core.targeting.render import render

MAX_GREETING_CHARS: Final = 300
MAX_AUTOFILL_CHARS: Final = 300
MAX_CHAT_QUESTIONS: Final = 4
MAX_QUESTION_CHARS: Final = 80
# The answer sent by itself when a question is tapped. Meta documents no
# ceiling for it; the greeting's own is used.
MAX_ANSWER_CHARS: Final = 300


def clean_questions(raw: Iterable[object]) -> tuple[str, ...]:
    """The owner's questions as they will be sent: trimmed, blank and
    repeated ones dropped, in the order written."""
    seen: set[str] = set()
    kept: list[str] = []
    for item in raw:
        question = " ".join(str(item).split())
        key = question.casefold()
        if question and key not in seen:
            seen.add(key)
            kept.append(question)
    return tuple(kept)


def clean_answered(
    questions: Iterable[object], answers: Iterable[object]
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The questions as :func:`clean_questions` keeps them, and beside each
    the answer written for it (``""`` when none): the two stay in step
    whichever rows are dropped."""
    written = [str(item).strip() for item in answers]
    seen: set[str] = set()
    kept: list[str] = []
    replies: list[str] = []
    for index, item in enumerate(questions):
        question = " ".join(str(item).split())
        key = question.casefold()
        if question and key not in seen:
            seen.add(key)
            kept.append(question)
            replies.append(written[index] if index < len(written) else "")
    return tuple(kept), tuple(replies)


def suggested_greeting(*, preset: Preset, business: BusinessProfile) -> str:
    """The catalogue's greeting with this business's own name in it."""
    if not preset.opens_chat or not preset.welcome_message:
        return ""
    try:
        greeting = render(
            preset.welcome_message,
            sources={"business": business},
            defaults=preset.defaults,
        )
    except TargetingError:
        return ""
    return str(greeting)[:MAX_GREETING_CHARS]
