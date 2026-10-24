"""Words that are heard but not read: the one list of them."""

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

SOFT_PAUSE_SECONDS: Final = 0.4

_APOSTROPHE_CODES: Final = (0x02BB, 0x02BC, 0x2018, 0x2019, 0x60)
_APOSTROPHES: Final = str.maketrans(dict.fromkeys(_APOSTROPHE_CODES, "'"))
_EDGES: Final = ' .,!?…-—:;"«»'


def normal(text: str) -> str:
    """A word as the lists hold it: lower case, plain apostrophe, no edges."""
    return text.translate(_APOSTROPHES).strip(_EDGES).lower()


def is_filler(text: str, *, pause_after: float, next_text: str = "") -> bool:
    """Whether a word is left out of the subtitles."""
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
