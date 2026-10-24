"""Which parts of an account a question actually needs."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from core.chat.stems import SECTIONS, WORDS, Section

APOSTROPHES: Final = str.maketrans(dict.fromkeys("\u2018\u2019\u02bb\u02bc", "'"))


@dataclass(frozen=True, slots=True)
class Route:
    """What this question is about, and what it is therefore not sent."""

    wants: frozenset[Section]
    omitted: tuple[Section, ...]


def route(*, question: str, previous: Iterable[str] = ()) -> Route:
    """What one question needs, given the one before it."""
    text = _fold(question)
    last = list(previous)[-1:]
    wants = _matched(text) | _matched(_fold(last[0]) if last else "")
    return Route(
        wants=frozenset(wants),
        omitted=tuple(name for name in SECTIONS if name not in wants),
    )


def _matched(text: str) -> set[Section]:
    if not text:
        return set()
    return {
        name for name, stems in WORDS.items() if any(stem in text for stem in stems)
    }


def _fold(text: str) -> str:
    """One casing, one apostrophe. Everything else is left as it arrived."""
    return text.casefold().translate(APOSTROPHES)


__all__ = ["SECTIONS", "WORDS", "Route", "Section", "route"]
