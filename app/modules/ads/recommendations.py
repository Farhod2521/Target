"""Which of Meta's ``recommendations`` the AI may hear.

TZ 7.4: the provider's advice is never shown to the owner and never acted
on. Only its technical side - a pixel or Conversions API fault, an error -
is passed to the AI as a signal, and advice about budget, placements or
Advantage+ is dropped whatever it says.

**Technical is decided by Meta's own words.** A recommendation is a code,
a title, a paragraph and the field it blames. The codes are undocumented
and new ones arrive without notice, so the test is the blamed field and
the words: one that names the pixel, the conversions API, an event or an
error is technical. Anything else - "Ad Set Ended", "Your Ad Set Targets
Multiple Countries", every audience and budget suggestion - is not.
"""

from collections.abc import Iterable, Mapping
from typing import Any, Final

WEAK_CONFIDENCE: Final = frozenset({"LOW"})
# Words that make a recommendation technical, read in lower case.
TECHNICAL_WORDS: Final[tuple[str, ...]] = (
    "pixel",
    "conversions api",
    "capi",
    "dataset",
    "event",
    "error",
)
# Words that make it advice the TZ drops even if a technical word is there.
DROPPED_WORDS: Final[tuple[str, ...]] = (
    "budget",
    "placement",
    "advantage",
    "audience",
)


def is_technical(item: Mapping[str, Any]) -> bool:
    """Whether the AI may read this recommendation."""
    if _text(item.get("confidence")).upper() in WEAK_CONFIDENCE:
        return False
    said = " ".join(
        _text(item.get(key)) for key in ("title", "message", "blame_field")
    ).lower()
    if any(word in said for word in DROPPED_WORDS):
        return False
    return any(word in said for word in TECHNICAL_WORDS)


def technical(recommendations: Iterable[Any]) -> list[Mapping[str, Any]]:
    """The technical ones, in Meta's order."""
    return [
        item
        for item in recommendations or ()
        if isinstance(item, Mapping) and is_technical(item)
    ]


def _text(value: Any) -> str:
    return str(value or "").strip()


__all__ = [
    "DROPPED_WORDS",
    "TECHNICAL_WORDS",
    "WEAK_CONFIDENCE",
    "is_technical",
    "technical",
]
