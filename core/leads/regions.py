# ruff: noqa: RUF001 - place names in Cyrillic, spelt as people write them.
"""Which of Uzbekistan's fourteen regions a place name belongs to."""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

CAPITAL: Final = "toshkent_shahri"
CAPITAL_REGION: Final = "toshkent"

REGIONS: Final[tuple[tuple[str, str], ...]] = (
    (CAPITAL, "Toshkent shahri"),
    (CAPITAL_REGION, "Toshkent viloyati"),
    ("andijon", "Andijon"),
    ("buxoro", "Buxoro"),
    ("fargona", "Farg'ona"),
    ("jizzax", "Jizzax"),
    ("namangan", "Namangan"),
    ("navoiy", "Navoiy"),
    ("qashqadaryo", "Qashqadaryo"),
    ("samarqand", "Samarqand"),
    ("sirdaryo", "Sirdaryo"),
    ("surxondaryo", "Surxondaryo"),
    ("xorazm", "Xorazm"),
    ("qoraqalpogiston", "Qoraqalpog'iston"),
)
REGION_LABELS: Final[dict[str, str]] = dict(REGIONS)

_REGION_WORDS: Final = frozenset(
    {
        "viloyati", "viloyat", "vil", "region", "province", "oblast",
        "oblasti", "область", "обл", "вилояти", "вилоят",
    }
)  # fmt: skip
_NOISE_WORDS: Final = frozenset(
    {
        "respublikasi", "respublika", "republic", "of", "the", "республика",
        "республикаси", "shahri", "shahar", "sh", "city", "город", "г",
        "uzbekistan", "ozbekiston", "узбекистан", "узбекистана",
        "ўзбекистон",
    }
)  # fmt: skip

_REGION_NAMES: Final[dict[str, tuple[str, ...]]] = {
    CAPITAL_REGION: ("toshkent", "tashkent", "ташкент", "тошкент"),
    "andijon": ("andijon", "andijan", "андижан", "андижон"),
    "buxoro": ("buxoro", "bukhara", "bukhoro", "buhara", "бухара", "бухоро"),
    "fargona": (
        "fargona", "fergana", "ferghana", "фергана", "фарғона", "фаргона",
    ),
    "jizzax": ("jizzax", "jizzakh", "djizak", "jizzak", "джизак", "жиззах"),
    "namangan": ("namangan", "наманган"),
    "navoiy": ("navoiy", "navoi", "navoiyi", "навои", "навоий"),
    "qashqadaryo": (
        "qashqadaryo", "kashkadarya", "qashqadarya", "кашкадарья",
        "кашкадарьинская", "қашқадарё", "кашкадарё",
    ),
    "samarqand": ("samarqand", "samarkand", "самарканд", "самарқанд"),
    "sirdaryo": (
        "sirdaryo", "syrdarya", "sirdarya", "сырдарья", "сырдарьинская",
        "сирдарё",
    ),
    "surxondaryo": (
        "surxondaryo", "surkhandarya", "surxondarya", "сурхандарья",
        "сурхандарьинская", "сурхондарё",
    ),
    "xorazm": ("xorazm", "khorezm", "khorazm", "horazm", "хорезм", "хоразм"),
    "qoraqalpogiston": (
        "qoraqalpogiston", "karakalpakstan", "qaraqalpaqstan", "каракалпакстан",
        "қорақалпоғистон", "коракалпогистон",
    ),
}  # fmt: skip
_ADJECTIVE: Final = re.compile(r"(ская|ский|ское)$")
_APOSTROPHES: Final = re.compile(r"[ʻʼ’‘`'´ʹ]")
_WORD: Final = re.compile(r"[^\W_]+")


@dataclass(frozen=True, slots=True)
class Folded:
    """A place name reduced to what identifies it."""

    base: str
    says_region: bool


def fold(text: str) -> Folded:
    """``"Farg'ona viloyati"`` -> ``Folded("fargona", True)``."""
    text = unicodedata.normalize("NFKC", text).casefold()
    text = _APOSTROPHES.sub("", text)
    text = "".join(
        c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)
    )
    words = _WORD.findall(text)
    says_region = any(word in _REGION_WORDS for word in words)
    kept = [
        _ADJECTIVE.sub("", word)
        for word in words
        if word not in _REGION_WORDS and word not in _NOISE_WORDS
    ]
    return Folded(base="".join(kept), says_region=says_region)


class RegionIndex:
    """Place names to region keys, with the cities a caller knows of."""

    def __init__(self, cities: Iterable[tuple[str, Iterable[str]]] = ()) -> None:
        self._names: dict[str, str] = {}
        for key, names in _REGION_NAMES.items():
            for name in names:
                self._names[fold(name).base] = key
        for region, towns in cities:
            if region not in REGION_LABELS:
                continue
            for town in towns:
                self._names.setdefault(fold(town).base, region)

    def region_of(self, text: str) -> str | None:
        """The region ``text`` names, or ``None`` when it names none."""
        folded = fold(text)
        if not folded.base:
            return None
        key = self._names.get(folded.base)
        if key == CAPITAL_REGION and folded.base in _CAPITAL_BASES:
            return CAPITAL_REGION if folded.says_region else CAPITAL
        return key


_CAPITAL_BASES: Final = frozenset(
    fold(name).base for name in _REGION_NAMES[CAPITAL_REGION]
)


def by_region(
    rows: Iterable[tuple[str, int]], *, index: RegionIndex
) -> tuple[dict[str, int], int]:
    """Counts per place summed per region, and how many named no region."""
    found: dict[str, int] = {}
    unplaced = 0
    for place, count in rows:
        key = index.region_of(place)
        if key is None:
            unplaced += count
        else:
            found[key] = found.get(key, 0) + count
    return found, unplaced
