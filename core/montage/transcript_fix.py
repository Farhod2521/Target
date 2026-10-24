"""The transcript put right where the recogniser clearly misheard it.

Speech recognition knows Uzbek, not this business: a brand's name, its
products and its slogan come back as the nearest common words -
"Targetolog AI" heard as "targetologiya" (``kind="brand"``). It also
mishears ordinary words now and then - "yordamiylasiz" for
"yordamingizsiz" (``kind="word"``). One cheap look by Claude, with the
brand's own words beside it, names the stretches it got wrong
(:class:`TranscriptFixes`); everything else is done here.

**Meaning is never changed.** Claude marks how sure it is, and only a
``high`` fix is made. A ``medium`` one - words that make no sense as
heard, with a guess at what was said - is not made but listed for a
person to read (:func:`doubts`), and so is a sure fix the guard below
refused. An ordinary word must also be put right into
something spelled much like it (:data:`MIN_LIKENESS`) - a mishearing
sounds like what was said - and may not add or take away a "not"
(:data:`_NEGATIONS`): "ishlaydi" into "ishlamaydi" is a different
sentence however alike it looks.

**Times are kept.** A fix replaces words ``first`` to ``last`` with new
ones that take the same stretch of time between them, shared out by
length: one word heard where two were said is split in proportion. Every
other word keeps its time to the millisecond, and its place: the numbers
the planner ties graphics to are counted on the transcript after this.

**Checked, not trusted.** A fix pointing outside the transcript, crossing
another, longer than a few words, changing nothing, unsure, or (for an
ordinary word) unlike what was heard or turning it negative is dropped. A word
that ended a sentence keeps its full stop.

**Kept as a diff.** What each fix replaced and with what, times and all,
so the words as heard can be read back and the fix can be judged.
"""

import re
from collections.abc import Sequence
from difflib import SequenceMatcher
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from core.montage.captions import SpokenWord

MAX_FIXES: Final = 40
# How many words one fix may replace, and how many it may put in.
MAX_SPAN: Final = 5
MAX_NEW_WORDS: Final = 5
_CLOSING: Final = ".,!?:;…"
# How alike, letter by letter (0-1), an ordinary word and its fix must be.
MIN_LIKENESS: Final = 0.6
# Words and endings that make an Uzbek sentence negative. Broad on
# purpose: a word caught by mistake only keeps its fix from being made.
_NEGATIONS: Final = re.compile(
    r"\b(?:emas|yo['\u02bb\u02bc]?q)\b|ma(?:y|di|gan|sin|ng|s)", re.IGNORECASE
)


class Fix(BaseModel):
    """One misheard stretch and what was said instead."""

    model_config = ConfigDict(frozen=True)

    first: int = Field(ge=0, description="Number (#) of the first misheard word.")
    last: int = Field(ge=0, description="Number (#) of the last misheard word.")
    text: str = Field(
        min_length=1,
        max_length=80,
        description="What was actually said there, spelled the brand's way.",
    )
    kind: Literal["brand", "word"] = Field(
        default="brand",
        description="brand: one of the business's own words; word: an "
        "ordinary word the recogniser misheard.",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        default="high",
        description="high: certain what was said - it is put right. medium: "
        "the words make no sense as heard and this is the best guess - left "
        "as heard, shown to a person. low: a hunch - ignored.",
    )
    note: str = Field(
        default="",
        max_length=120,
        description="For a medium one: in a few words, why it reads wrong.",
    )


class TranscriptFixes(BaseModel):
    """Claude's answer: the stretches to put right. Empty when none."""

    model_config = ConfigDict(frozen=True)

    fixes: list[Fix] = Field(max_length=MAX_FIXES)


def indexed_words(words: Sequence[SpokenWord]) -> str:
    """The transcript as the prompt shows it: ``#12 targetologiya``, one a line."""
    return "\n".join(f"#{index} {word.text}" for index, word in enumerate(words))


def apply_fixes(
    words: Sequence[SpokenWord], fixes: Sequence[Fix]
) -> tuple[tuple[SpokenWord, ...], list[dict[str, object]]]:
    """The transcript with ``fixes`` made, and what each one changed."""
    kept = _usable(words, fixes)
    out: list[SpokenWord] = []
    diff: list[dict[str, object]] = []
    cursor = 0
    for fix in kept:
        out.extend(words[cursor : fix.first])
        was = list(words[fix.first : fix.last + 1])
        now = _respoken(was, fix.text)
        out.extend(now)
        diff.append(
            {
                "at": fix.first,
                "kind": fix.kind,
                "was": [[w.text, w.start, w.end] for w in was],
                "now": [[w.text, w.start, w.end] for w in now],
            }
        )
        cursor = fix.last + 1
    out.extend(words[cursor:])
    return tuple(out), diff


def doubts(
    words: Sequence[SpokenWord], fixes: Sequence[Fix]
) -> list[dict[str, object]]:
    """What a person should read: the medium fixes, and the sure ones the
    meaning guard refused - each with the words as heard and the guess."""
    out: list[dict[str, object]] = []
    for fix in sorted(fixes, key=lambda f: f.first):
        if fix.last < fix.first or fix.last >= len(words):
            continue
        heard = " ".join(w.text for w in words[fix.first : fix.last + 1])
        refused = (
            fix.confidence == "high"
            and fix.kind == "word"
            and not _same_meaning(heard, fix.text)
        )
        if fix.confidence == "medium" or refused:
            out.append(
                {
                    "at": fix.first,
                    "time": words[fix.first].start,
                    "heard": heard,
                    "guess": fix.text,
                    "note": "changes the meaning" if refused else fix.note,
                }
            )
    return out


def _usable(words: Sequence[SpokenWord], fixes: Sequence[Fix]) -> list[Fix]:
    kept: list[Fix] = []
    taken = -1
    for fix in sorted(fixes, key=lambda f: (f.first, f.last)):
        new = fix.text.split()
        heard = " ".join(w.text for w in words[fix.first : fix.last + 1])
        if (
            fix.last < fix.first
            or fix.last >= len(words)
            or fix.first <= taken
            or fix.last - fix.first + 1 > MAX_SPAN
            or not new
            or len(new) > MAX_NEW_WORDS
            or " ".join(new) == heard
            or fix.confidence != "high"
            or (fix.kind == "word" and not _same_meaning(heard, " ".join(new)))
        ):
            continue
        kept.append(fix)
        taken = fix.last
    return kept


def _same_meaning(heard: str, said: str) -> bool:
    """Whether putting ``heard`` right as ``said`` only respells it."""
    alike = SequenceMatcher(None, heard.lower(), said.lower()).ratio()
    negative = bool(_NEGATIONS.search(heard)) != bool(_NEGATIONS.search(said))
    return alike >= MIN_LIKENESS and not negative


def _respoken(was: list[SpokenWord], text: str) -> list[SpokenWord]:
    """``text``'s words over the time ``was`` took, shared by length."""
    new = text.split()
    ending = was[-1].text[-1]
    if ending in _CLOSING and not new[-1].endswith(ending):
        new[-1] += ending
    start, end = was[0].start, was[-1].end
    total = sum(len(token) for token in new)
    out, at = [], start
    for index, token in enumerate(new):
        until = (
            end if index == len(new) - 1 else at + (end - start) * len(token) / total
        )
        out.append(SpokenWord(text=token, start=round(at, 3), end=round(until, 3)))
        at = until
    return out
