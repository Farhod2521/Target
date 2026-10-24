"""An Uzbek ending written apart from the brand's word it belongs to.

The recogniser splits a word it does not know from the ending it hears
on it: "Meta dan" for "Metadan", "Bahor ning" for "Bahorning". Uzbek
endings are never words of their own, so an ending (:data:`ENDINGS`) said
straight after one of the brand's own words - its name, its key terms -
with no pause between them (:data:`MAX_GAP`) is joined back on, the
ending's time with it.

Only for Uzbek: in Russian "до" or "на" after a name is a word.
"""

from collections.abc import Sequence
from typing import Final

from core.montage.captions import SpokenWord

ENDINGS: Final = frozenset(
    {"dan", "ning", "ga", "ka", "qa", "ni", "da", "ta", "lar", "dagi", "niki",
     "lari", "larni", "larga", "lardan", "larda", "larning", "dek", "day",
     "cha", "gacha", "dir"}
)  # fmt: skip
# Seconds between the word and its ending that still count as one word.
MAX_GAP: Final = 0.08
_PUNCTUATION: Final = '.,!?:;…"«»'
_APOSTROPHES: Final = str.maketrans(
    dict.fromkeys(("'", *map(chr, (0x2019, 0x2BB, 0x2BC))), "")
)


def joined_endings(
    words: Sequence[SpokenWord], terms: Sequence[str]
) -> tuple[tuple[SpokenWord, ...], list[dict[str, object]]]:
    """``words`` with the endings joined, and what each join changed."""
    tails = {_bare(term.split()[-1]) for term in terms if term.split()}
    out: list[SpokenWord] = []
    diff: list[dict[str, object]] = []
    for index, word in enumerate(words):
        before = out[-1] if out else None
        ending = _bare(word.text)
        if (
            before is not None
            and before.text[-1:] not in _PUNCTUATION
            and _bare(before.text) in tails
            and ending in ENDINGS
            and word.start - before.end <= MAX_GAP
        ):
            joined = SpokenWord(
                text=before.text + word.text, start=before.start, end=word.end
            )
            diff.append(
                {
                    "at": index - 1,
                    "kind": "ending",
                    "was": [
                        [before.text, before.start, before.end],
                        [word.text, word.start, word.end],
                    ],
                    "now": [[joined.text, joined.start, joined.end]],
                }
            )
            out[-1] = joined
        else:
            out.append(word)
    return tuple(out), diff


def _bare(text: str) -> str:
    return text.strip(_PUNCTUATION).translate(_APOSTROPHES).casefold()
