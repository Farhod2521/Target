"""The assistant's prompt in two parts: what is always sent, and what a
question brings with it.

``assistant/vN.md`` is one file so one version names everything. The text
above the first ``<!-- section: name -->`` mark is the base: it never
changes between questions, so it is the part the provider caches. Each
marked section is sent only when the question needs it, in front of the
Context - after the cached part, where it costs its own words and nothing
more.
"""

import re
from dataclasses import dataclass
from typing import Final

MARK: Final = re.compile(r"^<!--\s*section:\s*(\w+)\s*-->\s*$", re.MULTILINE)

LANGUAGE_NAMES: Final[dict[str, str]] = {
    "uz": "Uzbek, in the Latin script",
    "ru": "Russian",
    "en": "English",
}
DEFAULT_LANGUAGE: Final = "uz"

# A section goes with the Context when one of these headings is in it.
BY_HEADING: Final[dict[str, tuple[str, ...]]] = {
    "groups": ("## Ad groups", "### The ad group it is about"),
    "adverts": ("## Adverts",),
    "forms": ("## Lead forms", "## Website pages"),
    "before": ("days before that",),
    "suggestion": (
        "## The suggestion this question is about",
        "## What the agent proposed recently",
    ),
    "item": ("## The item this question is about",),
}
# ... or when the person's words, now or just before, carry one of these.
BY_WORD: Final[dict[str, tuple[str, ...]]] = {
    "video": ("video", "ssenariy", "reels", "rolik", "сценар", "ролик", "видео"),
    "ads_manager": ("ads manager", "adsmanager", "ads menejer", "адс менеджер"),
}
VISITOR: Final = "visitor"


@dataclass(frozen=True, slots=True)
class Prompt:
    """One version of the prompt, split where it is marked."""

    base: str
    sections: dict[str, str]

    def tail(self, names: tuple[str, ...], *, context: str) -> str:
        """The chosen sections, then the Context - the uncached part."""
        parts = [self.sections[name] for name in names if name in self.sections]
        parts.append(f"## Context\n\n{context}" if context else "## Context\n\n(empty)")
        return "\n\n".join(parts)


def split(template: str) -> Prompt:
    """The base and its named sections, each without the mark."""
    pieces = MARK.split(template)
    sections = {
        pieces[index]: pieces[index + 1].strip() for index in range(1, len(pieces), 2)
    }
    return Prompt(base=pieces[0].rstrip(), sections=sections)


def language_name(code: str) -> str:
    """The language as the model is told it: a name, never a code."""
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES[DEFAULT_LANGUAGE])


def sections_for(
    *, context: str, question: str, said: tuple[str, ...] = (), visitor: bool = False
) -> tuple[str, ...]:
    """Which sections this question brings, in the order the file has them."""
    if visitor:
        return (VISITOR,)
    words = " ".join((question, *said[-2:])).casefold()
    chosen = [
        name
        for name, headings in BY_HEADING.items()
        if any(heading in context for heading in headings)
    ]
    chosen += [
        name for name, stems in BY_WORD.items() if any(stem in words for stem in stems)
    ]
    return tuple(chosen)


__all__ = [
    "BY_HEADING",
    "BY_WORD",
    "LANGUAGE_NAMES",
    "VISITOR",
    "Prompt",
    "language_name",
    "sections_for",
    "split",
]
