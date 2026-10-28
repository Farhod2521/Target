"""Reading the four answers every platform names the same way."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from core.leads.phone import to_e164

# The keys a custom question is sent under when it asks for a name, a phone
# or an email to be typed rather than prefilled, so its answer lands in its
# column like a standard one.
TYPED_KEYS: Final[dict[str, str]] = {
    "full_name": "typed_full_name",
    "phone": "typed_phone",
    "email": "typed_email",
}

ANSWER_KEYS: Final[dict[str, tuple[str, ...]]] = {
    "full_name": ("full_name", "name", TYPED_KEYS["full_name"]),
    "phone": ("phone_number", "phone", TYPED_KEYS["phone"]),
    "email": ("email", "email_address", TYPED_KEYS["email"]),
    "city": ("city", "town"),
}

NAME_PARTS: Final[tuple[str, ...]] = ("first_name", "last_name")


@dataclass(frozen=True, slots=True)
class NormalisedLead:
    """The four columns, and the whole answer sheet keyed by question."""

    full_name: str = ""
    phone_e164: str = ""
    email: str = ""
    city: str = ""
    answers: dict[str, tuple[str, ...]] = field(default_factory=dict)


def normalise(
    *, field_data: Iterable[Mapping[str, Any]], region: str = ""
) -> NormalisedLead:
    """The standard answers, read out of one lead's answer sheet."""
    rows = list(field_data)

    return NormalisedLead(
        full_name=_name(rows),
        phone_e164=to_e164(raw=_answer(rows, ANSWER_KEYS["phone"]), region=region),
        email=_answer(rows, ANSWER_KEYS["email"]).lower(),
        city=_answer(rows, ANSWER_KEYS["city"]),
        answers=_answers(rows),
    )


def _answers(rows: list[Mapping[str, Any]]) -> dict[str, tuple[str, ...]]:
    """The whole answer sheet as ``{question key: answers}``."""
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
    """A full name, or the parts joined into one."""
    whole = _answer(rows, ANSWER_KEYS["full_name"])
    if whole:
        return whole

    parts = [_answer(rows, (key,)) for key in NAME_PARTS]
    return " ".join(part for part in parts if part)


def _answer(rows: list[Mapping[str, Any]], keys: tuple[str, ...]) -> str:
    """The first answer to the first of these keys that was asked."""
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


__all__ = ["ANSWER_KEYS", "TYPED_KEYS", "NormalisedLead", "normalise"]
