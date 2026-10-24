"""Recognising a typed question that asks for a name, a phone or an email.

Meta asks for those three itself: a standard question is prefilled from the
person's own profile. The same thing asked as a typed question, answered
into a free-text box, is what its review reads as collecting personal data
outside its rules - and it rejects the advert, after the campaign exists.

So a typed question is read for what it asks, in the three languages the
product's customers write in. The match is on word beginnings rather than
on whole labels, because "Ismingiz", "Ismingizni yozing" and "Ism va
familiyangiz" are one question.
"""

import re
from typing import Final, Literal

ContactKind = Literal["full_name", "phone", "email"]

# Word beginnings, per kind. A word matches when it starts with one of them.
#
# Short and specific on purpose. "nom" is not here - "Kurs nomi" asks for
# a course - and neither is a bare "mail" prefix, which would read
# "mailing" as an address.
_PREFIXES: Final[dict[ContactKind, tuple[str, ...]]] = {
    "full_name": ("ism", "familiya", "fio", "name", "имя", "имени", "фио", "фамили"),
    "phone": ("telefon", "phone", "nomer", "телефон", "номер"),
    "email": ("email", "gmail", "емейл", "имейл"),
}

# Whole words, per kind: too short to be a safe beginning.
_WORDS: Final[dict[ContactKind, frozenset[str]]] = {
    "full_name": frozenset(),
    "phone": frozenset({"tel", "тел"}),
    "email": frozenset(
        {"mail", "pochta", "pochtangiz", "pochtangizni", "почта", "почту", "почты"}
    ),
}

# "Raqam" alone is a phone number only in a short question: "Raqamingiz",
# "Aloqa raqami". In a longer one it is as likely to be a passport, a
# group or a house.
_NUMBER: Final = "raqam"
_SHORT: Final = 3

# "F.I.O." written with its dots is three one-letter words.
_INITIALS: Final = frozenset({"fio", "фио"})

# Postcode, not an address to write to.
_NOT_EMAIL: Final = ("indeks", "индекс")

# Apostrophes and hyphens split words: "e-mail" is "e" and "mail", and no
# beginning above has either inside it.
_WORD: Final = re.compile(r"\w+")


def contact_kind(label: str) -> ContactKind | None:
    """Which of the three the question asks for, or ``None``.

    Phone before name: "Ismingiz va telefon raqamingiz" is a request for a
    number as much as for a name, and the number is the one a lead cannot
    be followed up without.
    """
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
