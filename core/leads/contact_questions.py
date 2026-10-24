"""Recognising a typed question that asks for a name, a phone or an email."""

import re
from typing import Final, Literal

ContactKind = Literal["full_name", "phone", "email"]

_PREFIXES: Final[dict[ContactKind, tuple[str, ...]]] = {
    "full_name": ("ism", "familiya", "fio", "name", "имя", "имени", "фио", "фамили"),
    "phone": ("telefon", "phone", "nomer", "телефон", "номер"),
    "email": ("email", "gmail", "емейл", "имейл"),
}

_WORDS: Final[dict[ContactKind, frozenset[str]]] = {
    "full_name": frozenset(),
    "phone": frozenset({"tel", "тел"}),
    "email": frozenset(
        {"mail", "pochta", "pochtangiz", "pochtangizni", "почта", "почту", "почты"}
    ),
}

_NUMBER: Final = "raqam"
_SHORT: Final = 3

_INITIALS: Final = frozenset({"fio", "фио"})

_NOT_EMAIL: Final = ("indeks", "индекс")

_WORD: Final = re.compile(r"\w+")


def contact_kind(label: str) -> ContactKind | None:
    """Which of the three the question asks for, or ``None``."""
    text = label.casefold()
    words = _WORD.findall(text)
    if not words:
        return None

    if _has(words, "phone") or (
        len(words) <= _SHORT and any(word.startswith(_NUMBER) for word in words)
    ):
        return "phone"
    if _has(words, "email") and not any(word in text for word in _NOT_EMAIL):
        return "email"
    if _has(words, "full_name") or "".join(words) in _INITIALS:
        return "full_name"
    return None


def _has(words: list[str], kind: ContactKind) -> bool:
    prefixes = _PREFIXES[kind]
    whole = _WORDS[kind]
    return any(word in whole or word.startswith(prefixes) for word in words)
