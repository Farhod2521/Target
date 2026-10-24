"""An Uzbek ending written apart from the brand's word it belongs to."""

from collections.abc import Sequence
from typing import Final

from core.montage.captions import SpokenWord

ENDINGS: Final = frozenset(
    {"dan", "ning", "ga", "ka", "qa", "ni", "da", "ta", "lar", "dagi", "niki",
     "lari", "larni", "larga", "lardan", "larda", "larning", "dek", "day",
     "cha", "gacha", "dir"}
)  # fmt: skip
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
