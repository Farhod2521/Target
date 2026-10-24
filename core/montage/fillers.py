"""Words that are heard but not read: the one list of them.

The planner is told these are not content (the prompt shows
:func:`for_prompt`), and the subtitles leave them out (:func:`is_filler`).
One list, so the two never disagree about what a filler is.

Three kinds:

* **sounds** - hesitations with no meaning: "ee", "mmm", "э".
* **words** - real words used as padding so often in speech that, said
  on camera, they are padding: "xo'sh", "anaqa", "haligi", "koroche",
  "vot", "nu", "tipa".
* **soft** - words that are padding only sometimes. "Endi bu startapni..."
  needs its "endi"; "endi... bilasizmi" does not. One of these is dropped
  only when the speaker stops right after it, or says it twice in a row.

Comparison ignores case, the punctuation around a word, and which of the
four apostrophes Uzbek Latin is typed with.
"""

from typing import Final

SOUNDS: Final = frozenset(
    {"e", "ee", "eee", "eh", "em", "emm", "m", "mm", "mmm", "hmm", "xmm",
     "a", "aa", "aaa", "uh", "um", "umm", "э", "ээ", "эээ", "мм", "ммм", "хм"}
)  # fmt: skip
WORDS: Final = frozenset(
    {"xo'sh", "anaqa", "haligi", "koroche", "karoche", "vot", "nu", "tipa",
     "короче", "вот", "ну", "типа"}
)  # fmt: skip
SOFT: Final = frozenset({"mana", "endi", "вообще"})

# A soft filler followed by at least this much silence was a pause for
# thought, not the start of a phrase.
SOFT_PAUSE_SECONDS: Final = 0.4

# Okina, modifier apostrophe, both curly quotes and the backtick.
_APOSTROPHE_CODES: Final = (0x02BB, 0x02BC, 0x2018, 0x2019, 0x60)
_APOSTROPHES: Final = str.maketrans(dict.fromkeys(_APOSTROPHE_CODES, "'"))
_EDGES: Final = ' .,!?…-—:;"«»'


def normal(text: str) -> str:
    """A word as the lists hold it: lower case, plain apostrophe, no edges."""
    return text.translate(_APOSTROPHES).strip(_EDGES).lower()


def is_filler(text: str, *, pause_after: float, next_text: str = "") -> bool:
    """Whether a word is left out of the subtitles.

    ``pause_after`` is the silence before the next word (a large number
    when it is the last); ``next_text`` is that word.
    """
    word = normal(text)
    if word in SOUNDS or word in WORDS:
        return True
    if word in SOFT:
        return pause_after >= SOFT_PAUSE_SECONDS or normal(next_text) == word
    return False


def for_prompt() -> str:
    """The sounds and words, quoted, for a prompt that asks they be cut."""
    shown = sorted(WORDS - {"karoche"}, key=lambda w: (not w.isascii(), w))
    return ", ".join(f'"{w}"' for w in ("ee", "mmm", *shown))
