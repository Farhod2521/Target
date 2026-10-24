"""Reading the four answers every platform names the same way.

A lead form asks whatever the advertiser wanted to ask, so most of what
comes back cannot be put in a column and stays in ``field_data`` untouched.
Four answers are the exception: every lead platform has a standard question
for a name, a phone number, an email address and a city, and those four are
what a screen shows, what an export contains and what a duplicate is found
by.

Everything else is turned into a **dictionary keyed by question**, which is
the difference between an answer that is stored and one that can be asked
about. It is not a replacement for the raw payload and does not try to be:
the raw list is what actually arrived and stays exactly as it came.

**Best effort, and never fatal.** An answer that cannot be read leaves its
column empty and stays whole in the raw payload. Losing a lead because
somebody mistyped a digit would be losing the thing the product exists to
collect, and the raw answers remain the honest record of what was actually
written.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from core.leads.phone import to_e164

# The keys a provider may answer one standard question under, in the order
# they are tried. Several per column because platforms disagree in small
# ways - Meta calls a phone number ``phone_number`` and a postcode
# ``zip_code`` - and because a form can ask for a first and last name
# instead of a full one.
#
# Only the standard set is listed. A custom question's key is generated per
# form and can be anything; those are read from ``field_data`` by whoever
# knows which form they belong to.
ANSWER_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "full_name": ("full_name", "name"),
    "phone": ("phone_number", "phone"),
    "email": ("email", "email_address"),
    "city": ("city", "town"),
}

# Read and joined when there is no single full-name answer. Order matters
# and is not alphabetical: it is how a name is written.
NAME_PARTS: Final[tuple[str, ...]] = ("first_name", "last_name")


@dataclass(frozen=True, slots=True)
class NormalisedLead:
    """The four columns, and the whole answer sheet keyed by question.

    Every column can be empty, and an empty one means "not asked, not
    answered, or not readable" - three cases a lead screen shows the same
    way, because the fix for all three is to look at the raw answers.

    ``answers`` is the other half and is a different kind of thing. The
    columns are a convenience for screens, exports and duplicate-finding;
    this is the answer sheet in a shape a database can be asked about. What
    it is *not* is a second copy of the truth - the raw list stays beside
    it and stays authoritative, because this drops what a projection must
    drop (see :func:`_answers`).
    """

    full_name: str = ""
    phone_e164: str = ""
    email: str = ""
    city: str = ""
    # Keyed by the **provider's** own answer key, never by the question
    # type that was sent. The two are not the same word and were never
    # promised to be - a question sent as ``PHONE`` comes back named
    # ``phone_number`` - so keying by what arrived is what makes the
    # asymmetry harmless instead of a mapping table to maintain.
    #
    # Values stay a tuple rather than collapsing to the first one. The four
    # columns above take the first deliberately, because a name is one
    # name; a multiple-choice question genuinely has several answers and
    # keeping one of them would be losing the answer.
    answers: dict[str, tuple[str, ...]] = field(default_factory=dict)


def normalise(
    *, field_data: Iterable[Mapping[str, Any]], region: str = ""
) -> NormalisedLead:
    """The standard answers, read out of one lead's answer sheet.

    ``region`` is the two-letter country code the business operates in, and
    it is only consulted for a phone number that does not carry its own
    country code. It is a parameter rather than a constant because no
    country is privileged here - see CLAUDE.md's rule against writing
    ``"+998"`` down anywhere.
    """
    rows = list(field_data)

    return NormalisedLead(
        full_name=_name(rows),
        phone_e164=to_e164(raw=_answer(rows, ANSWER_KEYS["phone"]), region=region),
        email=_answer(rows, ANSWER_KEYS["email"]).lower(),
        city=_answer(rows, ANSWER_KEYS["city"]),
        answers=_answers(rows),
    )


def _answers(rows: list[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    """The whole answer sheet as ``{question key: answers}``.

    A dictionary and not the list that arrived, because the list cannot be
    asked a question. "What did people answer to q2" over a form's leads is
    a key lookup on this shape and a scan through nested arrays on the
    other one - and the second is the shape the product already stores
    whole, so nothing is lost by holding the first beside it.

    Keyed by what the provider called the field. A standard question comes
    back under the provider's own name and a custom one under the key that
    was sent for it, and this makes no attempt to reconcile the two: the
    key that arrived is the key the answer is filed under, which is the one
    fact about it that cannot be wrong.

    **Two things are dropped on purpose, and the raw list keeps both.** A
    key seen twice keeps its first answer, on the same reasoning the
    columns use - a repeated field is the provider echoing something the
    person edited. And an answer with no values at all is left out
    entirely, because a question somebody skipped is not a question they
    answered with nothing.
    """
    found: dict[str, tuple[str, ...]] = {}

    for row in rows:
        key = str(row.get("name", "")).strip()
        if not key or key in found:
            continue
        values = row.get("values")
        if not isinstance(values, list):
            continue
        answers = tuple(str(value).strip() for value in values if str(value).strip())
        if answers:
            found[key] = answers

    return found


def _name(rows: list[Mapping[str, Any]]) -> str:
    """A full name, or the parts joined into one.

    Joined rather than stored separately because a screen shows one name
    and an export writes one column. The parts are still in the raw answers
    for anybody who needs them apart.
    """
    whole = _answer(rows, ANSWER_KEYS["full_name"])
    if whole:
        return whole

    parts = [_answer(rows, (key,)) for key in NAME_PARTS]
    return " ".join(part for part in parts if part)


def _answer(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> str:
    """The first answer to the first of these keys that was asked.

    First and not joined: a repeated answer is the provider echoing a field
    the person edited, and concatenating them produces a name that is two
    names.
    """
    for key in keys:
        for row in rows:
            if str(row.get("name", "")).strip().lower() != key:
                continue
            values = row.get("values")
            if isinstance(values, list) and values:
                found = str(values[0]).strip()
                if found:
                    return found
    return ""


__all__ = ["ANSWER_KEYS", "NormalisedLead", "normalise"]
