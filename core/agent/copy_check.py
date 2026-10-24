"""Whether advert copy says only what the owner said, the way the button allows.

Deterministic, cheap and deliberately limited. It finds what can be found by
reading: a number the owner never wrote, a promise the owner never made, a
sentence about the reader's own health or money, a closing line that asks
for something the button does not do, a phone number on the wrong kind of
advert, and words too thin to be an advert at all.

What it cannot find is a fact bent into another fact out of the same digits:
"5 days in Madinah" written as "10 days" when the offer also says "10"
somewhere, or a place the owner never named. That is what the second read by
Claude is for - see :mod:`apps.ads.services.review_copy` - and what these
findings are handed to it beside, so it can confirm each one rather than
start from nothing.

Codes rather than sentences, like every domain answer here: the review
screen words them in three languages.
"""

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

# Below this many words the text names nothing a customer could want. "Ariza
# qoldiring" is two, and it reached three live adverts in every field.
MIN_WORDS: Final = 4

# A local number is nine digits and an international one longer. Prices stop
# well short of that - "1 500 000" is seven - so the count is what tells a
# phone number from an amount written with spaces.
MIN_PHONE_DIGITS: Final = 9

_PHONE: Final = re.compile(r"\+?\(?\d[\d\s().-]{7,}\d")
# Thousands grouped by a space, dot or comma first ("79 000", "95.000"), then
# a plain or decimal number ("1,5"), so one amount is one value on both sides.
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
    """What is wrong with the words on their own.

    The whole check for text the owner wrote themselves: the promises in it
    are theirs to make, but two words in every field is a mistake whoever
    typed it.
    """
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
    """Everything :func:`check_words` asks, and whether the words keep to the offer.

    ``facts`` is what the owner wrote about the business and the pictures.
    ``sends_to`` is where the button takes somebody, in the domain's words.
    """
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
