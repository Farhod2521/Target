"""A greeting at the very start is cut, whatever the plan said.

"Assalomu alaykum, do'stlar" is how people start talking to a camera and
the worst way to start a video in a feed: it spends the first second on
nothing. When the video opens on one of :data:`GREETINGS` and the speaker
goes on to say something in the same stretch, the stretch starts on the
first word after it (with the usual breath room). A stretch that is the
greeting and nothing more is left alone - the planner kept it for a
reason, and an empty video is worse.

Words are compared as the filler list compares them (:func:`normal`),
greetings one after another taken off together.
"""

from collections.abc import Sequence
from typing import Final

from videokit import Cut

from core.montage.captions import SpokenWord
from core.montage.fillers import normal

GREETINGS: Final[tuple[tuple[str, ...], ...]] = (
    ("assalomu", "alaykum"),
    ("assalom", "alaykum"),
    ("hammaga", "salom"),
    ("salom",),
    ("do'stlar",),
    ("всем", "привет"),
    ("привет",),
    ("друзья",),
    ("здравствуйте",),
)
# What has to remain after the greeting for it to be cut: a few words.
CONTENT_WORDS: Final = 3
PAD_BEFORE: Final = 0.08


def without_greeting(cuts: Sequence[Cut], words: Sequence[SpokenWord]) -> list[Cut]:
    """``cuts`` with a greeting at the start of the first one cut off."""
    if not cuts:
        return list(cuts)
    first = cuts[0]
    said = [w for w in words if first.start - 0.05 <= w.start < first.end]
    skip = _greeting_length([normal(w.text) for w in said])
    if not skip or len(said) - skip < CONTENT_WORDS:
        return list(cuts)
    start = max(said[skip].start - PAD_BEFORE, said[skip - 1].end)
    return [first.model_copy(update={"start": round(start, 3)}), *cuts[1:]]


def _greeting_length(said: list[str]) -> int:
    """How many words at the start are greetings, one after another."""
    taken = 0
    while True:
        found = next(
            (g for g in GREETINGS if tuple(said[taken : taken + len(g)]) == g), None
        )
        if found is None:
            return taken
        taken += len(found)
