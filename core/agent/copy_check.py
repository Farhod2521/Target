"""Whether advert copy says only what the owner said, the way the button allows."""

import re
from dataclasses import dataclass
from typing import Final, Literal

from core.agent.copy_words import (
    ACTIONS,
    ALLOWED_ACTIONS,
    PHONE_KEPT,
    PHONE_UNWANTED,
    PROMISES,
    SECOND_PERSON,
    SENSITIVE,
    first_stem,
    normalize,
)

FindingCode = Literal[
    "empty",
    "too_short",
    "same_in_all_fields",
    "number_not_in_offer",
    "promise_not_in_offer",
    "personal_attribute",
    "action_mismatch",
    "phone_in_form_ad",
    "phone_dropped",
]

MIN_WORDS: Final = 4

MIN_PHONE_DIGITS: Final = 9

_PHONE: Final = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
_NUMBER: Final = re.compile(r"\d{1,3}(?:[ .,]\d{3})+(?!\d)|\d+(?:[.,]\d+)?")
_GROUPED: Final = re.compile(r"\d{1,3}(?:[ .,]\d{3})+")
_SENTENCE: Final = re.compile(r"[.!?]+")


@dataclass(frozen=True, slots=True)
class AdWords:
    """The three lines of one advert."""

    primary_text: str
    headline: str
    description: str

    def joined(self) -> str:
        """All three as one text, each ending a sentence of its own."""
        return ". ".join((self.primary_text, self.headline, self.description))


@dataclass(frozen=True, slots=True)
class CopyFinding:
    """One thing wrong with an advert, and the words that show it."""

    code: FindingCode
    detail: str = ""


def check_words(*, words: AdWords) -> tuple[CopyFinding, ...]:
    """What is wrong with the words on their own."""
    text = words.primary_text.strip()
    if not text:
        return (CopyFinding("empty"),)

    found: list[CopyFinding] = []
    if len(text.split()) < MIN_WORDS:
        found.append(CopyFinding("too_short"))
    lines = [
        normalize(line)
        for line in (words.primary_text, words.headline, words.description)
        if line.strip()
    ]
    if len(set(lines)) < len(lines):
        found.append(CopyFinding("same_in_all_fields"))
    return tuple(found)


def check_against_offer(
    *, words: AdWords, facts: str, sends_to: str
) -> tuple[CopyFinding, ...]:
    """Everything :func:`check_words` asks, and whether the words keep to the offer."""
    copy = normalize(words.joined())
    offer = normalize(facts)
    return (
        *check_words(words=words),
        *_numbers(copy, offer),
        *_promises(copy, offer),
        *_personal(copy),
        *_actions(copy, sends_to),
        *_phones(copy, offer, sends_to),
    )


def _numbers(copy: str, offer: str) -> tuple[CopyFinding, ...]:
    missing = sorted(_number_set(copy) - _number_set(offer))
    if not missing:
        return ()
    return (CopyFinding("number_not_in_offer", ", ".join(missing)),)


def _promises(copy: str, offer: str) -> tuple[CopyFinding, ...]:
    found = []
    for stems in PROMISES.values():
        said = first_stem(copy, stems)
        if said and not first_stem(offer, stems):
            found.append(CopyFinding("promise_not_in_offer", said))
    return tuple(found)


def _personal(copy: str) -> tuple[CopyFinding, ...]:
    for sentence in _SENTENCE.split(copy):
        said = first_stem(sentence, SENSITIVE)
        if said and SECOND_PERSON.search(sentence):
            return (CopyFinding("personal_attribute", sentence.strip()),)
    return ()


def _actions(copy: str, sends_to: str) -> tuple[CopyFinding, ...]:
    allowed = ALLOWED_ACTIONS.get(sends_to, ALLOWED_ACTIONS["nothing"])
    found = []
    for kind, stems in ACTIONS.items():
        said = "" if kind in allowed else first_stem(copy, stems)
        if said:
            found.append(CopyFinding("action_mismatch", said))
    return tuple(found)


def _phones(copy: str, offer: str, sends_to: str) -> tuple[CopyFinding, ...]:
    written = _phones_in(copy)
    if sends_to in PHONE_UNWANTED and written:
        return (CopyFinding("phone_in_form_ad", written[0]),)
    if sends_to in PHONE_KEPT:
        kept = {phone[-MIN_PHONE_DIGITS:] for phone in written}
        lost = [p for p in _phones_in(offer) if p[-MIN_PHONE_DIGITS:] not in kept]
        if lost:
            return (CopyFinding("phone_dropped", lost[0]),)
    return ()


def _phones_in(text: str) -> list[str]:
    """Every phone number in the text, as its digits."""
    found = (re.sub(r"\D", "", match.group()) for match in _PHONE.finditer(text))
    return [digits for digits in found if len(digits) >= MIN_PHONE_DIGITS]


def _number_set(text: str) -> set[str]:
    """Every amount in the text, phone numbers left out, in one spelling."""
    without_phones = _PHONE.sub(_blank_if_phone, text)
    values = set()
    for match in _NUMBER.finditer(without_phones):
        raw = match.group()
        if _GROUPED.fullmatch(raw):
            values.add(re.sub(r"\D", "", raw))
        else:
            values.add(raw.replace(",", "."))
    return values


def _blank_if_phone(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group())
    return " " if len(digits) >= MIN_PHONE_DIGITS else match.group()
