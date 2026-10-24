"""Turning a customer list into something a provider will match on.

The one place in this project where personal data is prepared to leave it,
and the only place it may be. What comes out the far side is
:class:`~adskit.AudienceMemberDTO` - SHA-256 digests and nothing else - so
the provider packages never receive a name, a number or an address at all.
That is the whole reason this lives here rather than in ``metaads``: a
package that cannot be handed personal data cannot leak it, and the test
that says so rests on the type rather than on a review of one function.

The second reason is :mod:`core.leads.phone`. Every platform wants a phone
number as digits with a country code and no plus - which is E.164 minus one
character - and E.164 is what that module already produces, correctly, from
whatever somebody typed. ``packages/`` may not import ``core/``, so hashing
in a provider package would have meant a second phone parser living beside
the first and drifting away from it.

**Getting a rule wrong here does not fail.** It produces rows the provider
accepts the shape of and matches to nobody, and the only symptom is an
audience that stays small. Which is why every rule below is written out
with the reason for it, and why the digests are pinned in tests against
values computed by hand.

No Django, no clock, no configuration. The country a phone number should be
read against arrives as an argument, because no country is privileged here.
"""

import hashlib
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from adskit import AudienceMemberDTO

from core.leads.phone import to_e164

# ISO-3166 alpha-2, and nothing else is a country. A longer or shorter
# value is a column somebody filled in with a country *name*, which hashes
# to something no provider has ever stored.
COUNTRY_CODE_LENGTH: Final = 2


@dataclass(frozen=True, slots=True)
class CustomerRecord:
    """One person as the advertiser holds them, before anything is hashed.

    Plaintext, and therefore never sent anywhere. It exists so the
    normalisation below has a named input and so the boundary is visible:
    a ``CustomerRecord`` is on this side of it and an
    :class:`~adskit.AudienceMemberDTO` is on the other.

    Every field is optional, because every source of these is partial. A
    lead that answered only a phone number is still worth uploading -
    providers hash each key independently and match on whatever is there.
    """

    email: str = ""
    phone: str = ""
    first_name: str = ""
    last_name: str = ""
    city: str = ""
    # ISO-3166 alpha-2. Not the phone's region, although they are usually
    # the same: this one is where the person is, and that one is how to
    # read a number they wrote without a country code.
    country_code: str = ""


def hashed_member(*, record: CustomerRecord, region: str = "") -> AudienceMemberDTO:
    """One person, normalised and hashed, ready to cross the boundary.

    ``region`` is the two-letter country code a phone number without its own
    country code should be read against - the advertiser's own country. It
    is consulted for nothing else, and a number written with a leading plus
    ignores it.

    A field that cannot be normalised comes back empty rather than hashed
    as it stands, and that is the important half of this function. A phone
    number missing its country code, an email with no ``@``, a "country"
    holding the word "Uzbekistan" - each of them hashes perfectly happily
    into sixty-four characters that no provider has ever seen. An empty
    field says "we do not know this about them", which is true; a digest of
    a malformed value says "we know this" and is a lie the match rate pays
    for.
    """
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
    """A whole list, with the rows that identify nobody left out.

    A record whose every field failed to normalise - a blank line in a
    spreadsheet, a lead that answered nothing readable - would upload as
    six empty strings, which the provider counts as a row and matches to
    nobody. Dropping it here is what keeps the count on the screen an
    honest one.
    """
    hashed = (hashed_member(record=record, region=region) for record in records)
    return tuple(member for member in hashed if not member.is_empty)


def _digest(value: str) -> str:
    """SHA-256, hex, lower case. Empty in, empty out.

    Empty out matters: hashing an empty string produces a perfectly valid
    digest of nothing, and every row missing that field would then carry
    the same one - which is a value the provider tries to match, and a
    column where every row is identical is a column that can only slow the
    matching down.
    """
    if not value:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _email(raw: str) -> str:
    """Lower case, trimmed, and refused if it is not an address.

    The shape check is deliberately loose - one ``@``, something on each
    side, no whitespace - because this is not validation and an address
    this rejects is one the advertiser cannot use anyway. What it is for is
    the column somebody filled in with a note instead of an email.
    """
    text = raw.strip().lower()
    if text.count("@") != 1 or any(character.isspace() for character in text):
        return ""
    local, _, domain = text.partition("@")
    return text if local and "." in domain else ""


def _phone(raw: str, *, region: str) -> str:
    """E.164 with the plus taken off, which is what every platform wants.

    Reusing :func:`core.leads.phone.to_e164` rather than stripping
    non-digits, and the difference is not tidiness. A trunk zero has to be
    dropped in one country and kept in another, and a number typed without
    a country code has to have one added - both of which depend on where
    the advertiser is, and both of which are libphonenumber's whole job.
    Digits alone would send ``901234567`` where ``998901234567`` was meant,
    and that matches nobody rather than failing.

    Empty for anything that cannot be parsed into a dialable number. The
    raw answer is still on the lead; it is only unfit for *this*.
    """
    return to_e164(raw=raw, region=region).lstrip("+")


def _name(raw: str) -> str:
    """Lower case, no punctuation, no spaces, Latin accents folded away.

    The folding is per character and only where the base letter is ASCII,
    which is fussier than it looks and is there for one reason: decomposing
    the whole string and dropping every combining mark does not only remove
    accents. Cyrillic short-i and Uzbek Cyrillic short-u are each written as
    a base letter plus a breve, so a blanket rule turns them into the plain
    letters underneath - which are different letters, in different names,
    that a provider stores apart.

    So an acute over a Latin ``e`` is dropped and a breve over a Cyrillic
    letter is kept. The turned commas Uzbek writes in the Latin alphabet go
    either way, because they are punctuation on every platform's list.
    """
    return _folded(raw)


def _place(raw: str) -> str:
    """A city, by the same rules as a name.

    Spaces included: ``Nukus``, ``New York`` and ``Yangi Yo'l`` are
    ``nukus``, ``newyork`` and ``yangiyol``. Removing them is the
    platforms' own rule and it is why a city is worth so little on its own
    - it is a supporting key, matched beside a name rather than instead of
    one.
    """
    return _folded(raw)


def _country(raw: str) -> str:
    """Two letters, lower case, or nothing at all.

    Refused rather than truncated when it is longer. A column holding
    "Uzbekistan" is not a country code with extra letters on it, and
    keeping the first two would send ``uz`` - which happens to be right
    here and would be silently wrong for ``United States``.
    """
    text = _folded(raw)
    return text if len(text) == COUNTRY_CODE_LENGTH else ""


def _folded(raw: str) -> str:
    """Lower case, letters and digits only, Latin accents removed.

    One function for names, cities and country codes because the platforms
    apply one rule to all three. Digits are kept: they are part of a
    postcode and of a handful of real place names, and dropping them here
    would be a rule invented rather than followed.
    """
    return "".join(_letter(character) for character in raw.strip().lower())


def _letter(character: str) -> str:
    """One character, folded if it is a Latin one and dropped if it is not
    a letter or a digit at all."""
    decomposed = unicodedata.normalize("NFD", character)
    base = decomposed[0]

    if base.isascii() and base.isalnum():
        # ``é`` -> ``e``, ``ñ`` -> ``n``. The marks after the base are what
        # NFD split off and they are exactly what is being dropped.
        return base
    if base.isalnum():
        # Anything outside ASCII keeps its marks: see :func:`_name`.
        return character
    return ""


__all__ = ["COUNTRY_CODE_LENGTH", "CustomerRecord", "hashed_member", "hashed_members"]
