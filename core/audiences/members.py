"""Turning a customer list into something a provider will match on."""

import hashlib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from adskit import AudienceMemberDTO

from core.leads.phone import to_e164

COUNTRY_CODE_LENGTH: Final = 2


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    """One person as the advertiser holds them, before anything is hashed."""

    email: str = ""
    phone: str = ""
    first_name: str = ""
    last_name: str = ""
    city: str = ""
    country_code: str = ""


def hashed_member(*, record: CustomerRecord, region: str = "") -> AudienceMemberDTO:
    """One person, normalised and hashed, ready to cross the boundary."""
    return AudienceMemberDTO(
        email=_digest(_email(record.email)),
        phone=_digest(_phone(record.phone, region=region)),
        first_name=_digest(_name(record.first_name)),
        last_name=_digest(_name(record.last_name)),
        city=_digest(_place(record.city)),
        country=_digest(_country(record.country_code)),
    )


def hashed_members(
    *, records: Iterable[CustomerRecord], region: str = ""
) -> tuple[AudienceMemberDTO, ...]:
    """A whole list, with the rows that identify nobody left out."""
    hashed = (hashed_member(record=record, region=region) for record in records)
    return tuple(member for member in hashed if not member.is_empty)


def _digest(value: str) -> str:
    """SHA-256, hex, lower case. Empty in, empty out."""
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _email(raw: str) -> str:
    """Lower case, trimmed, and refused if it is not an address."""
    text = raw.strip().lower()
    if text.count("@") != 1 or any(character.isspace() for character in text):
        return ""
    local, _, domain = text.partition("@")
    return text if local and "." in domain else ""


def _phone(raw: str, *, region: str) -> str:
    """E.164 with the plus taken off, which is what every platform wants."""
    return to_e164(raw=raw, region=region).lstrip("+")


def _name(raw: str) -> str:
    """Lower case, no punctuation, no spaces, Latin accents folded away."""
    return _folded(raw)


def _place(raw: str) -> str:
    """A city, by the same rules as a name."""
    return _folded(raw)


def _country(raw: str) -> str:
    """Two letters, lower case, or nothing at all."""
    text = _folded(raw)
    return text if len(text) == COUNTRY_CODE_LENGTH else ""


def _folded(raw: str) -> str:
    """Lower case, letters and digits only, Latin accents removed."""
    return "".join(_letter(character) for character in raw.strip().lower())


def _letter(character: str) -> str:
    """One character, folded if it is a Latin one and dropped if it is not
    a letter or a digit at all."""
    decomposed = unicodedata.normalize("NFD", character)
    base = decomposed[0]

    if base.isascii() and base.isalnum():
        return base
    if base.isalnum():
        return character
    return ""


__all__ = ["COUNTRY_CODE_LENGTH", "CustomerRecord", "hashed_member", "hashed_members"]
