"""The rules that decide whether a customer list matches anybody.

Every expected digest here is computed **in the test**, from the string the
normalisation is supposed to produce - never copied from a run of the code
it is checking. A test asserting that ``_email`` returns what ``_email``
returned would pass through any rewrite of the rule, including the ones
that quietly lose the match rate.

Getting one of these wrong does not fail anywhere. The provider accepts a
digest of the wrong thing, matches it to nobody, and reports an audience
that is simply small - so these are the only place the rules are checked at
all.
"""

import hashlib

import pytest
from adskit import AudienceMemberDTO
from pydantic import ValidationError

from core.audiences import CustomerRecord, hashed_member, hashed_members


def digest(value: str) -> str:
    """What the provider is supposed to receive for ``value``."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# --- The four rules ---------------------------------------------------
def test_an_email_is_trimmed_and_lowercased() -> None:
    member = hashed_member(record=CustomerRecord(email="  John.Doe@Example.COM "))

    assert member.email == digest("john.doe@example.com")


def test_a_phone_becomes_digits_with_a_country_code_and_no_plus() -> None:
    """The single rule most likely to be got wrong, and the most expensive.

    A local number sent without its country code is the right shape, hashes
    fine, and matches nobody - so the whole audience comes back small and
    nothing anywhere says why.
    """
    member = hashed_member(record=CustomerRecord(phone="90 123 45 67"), region="UZ")

    assert member.phone == digest("998901234567")


def test_a_number_that_already_carries_its_country_ignores_the_region() -> None:
    member = hashed_member(record=CustomerRecord(phone="+998901234567"), region="TR")

    assert member.phone == digest("998901234567")


def test_a_name_loses_its_punctuation_and_its_latin_accents() -> None:
    member = hashed_member(
        record=CustomerRecord(first_name="José", last_name="O'Neill-Smith")
    )

    assert member.first_name == digest("jose")
    assert member.last_name == digest("oneillsmith")


def test_a_cyrillic_name_keeps_the_marks_that_are_part_of_its_letters() -> None:
    """The reason the folding is per character rather than per string.

    Decomposing everything and dropping every combining mark turns the
    Cyrillic short-i into a plain i and the Uzbek Cyrillic short-u into a
    plain u. Those are different letters in different names, and a provider
    files them apart - so the blanket rule would silently mismatch every
    name that contains one.
    """
    member = hashed_member(record=CustomerRecord(first_name="Йўлдош"))

    assert member.first_name == digest("йўлдош")


def test_a_city_loses_its_spaces_as_well() -> None:
    member = hashed_member(record=CustomerRecord(city="New York"))

    assert member.city == digest("newyork")


def test_a_country_is_two_letters_lowercased() -> None:
    member = hashed_member(record=CustomerRecord(country_code="UZ"))

    assert member.country == digest("uz")


# --- What is refused rather than hashed -------------------------------
def test_a_country_name_is_refused_rather_than_truncated() -> None:
    """Keeping the first two letters would be right here and wrong for
    ``United States``, which is the definition of a rule not to have."""
    member = hashed_member(record=CustomerRecord(country_code="Uzbekistan"))

    assert member.country == ""


def test_a_string_that_is_not_an_address_is_not_hashed_as_one() -> None:
    for text in ("not-an-email", "two@at@signs.com", "spaces in@it.com", "no@domain"):
        assert hashed_member(record=CustomerRecord(email=text)).email == ""


def test_an_unparseable_number_is_left_out_rather_than_guessed_at() -> None:
    member = hashed_member(record=CustomerRecord(phone="123"), region="UZ")

    assert member.phone == ""


def test_an_empty_field_stays_empty_rather_than_hashing_nothing() -> None:
    """A digest of the empty string is a perfectly valid digest, and every
    row missing that field would carry the same one - a value the provider
    tries to match, in a column where every row is identical."""
    member = hashed_member(record=CustomerRecord(email="a@b.co"))

    assert member.phone == ""
    assert member.first_name == ""
    assert member.city == ""


# --- The boundary itself ----------------------------------------------
def test_the_dto_refuses_to_hold_anything_that_is_not_a_digest() -> None:
    """**The lock this whole design rests on.**

    Unhashed personal data cannot reach a provider package because it
    cannot be put in the object that crosses into one. Not a convention and
    not a review item - the type refuses.
    """
    for plaintext in ("someone@example.com", "+998901234567", "Aziz", "a" * 63):
        with pytest.raises(ValidationError):
            AudienceMemberDTO(email=plaintext)


def test_an_upper_case_digest_is_refused_too() -> None:
    """Providers specify lower case, and hex is case-insensitive to a human
    and not to a hash table."""
    with pytest.raises(ValidationError):
        AudienceMemberDTO(email=digest("a@b.co").upper())


def test_everything_hashed_here_satisfies_that_boundary() -> None:
    """The two halves must agree, and this is where they are checked
    against each other rather than each against its own idea."""
    member = hashed_member(
        record=CustomerRecord(
            email="a@b.co",
            phone="+998901234567",
            first_name="Aziz",
            last_name="Karimov",
            city="Toshkent",
            country_code="UZ",
        ),
        region="UZ",
    )

    assert not member.is_empty
    for value in (
        member.email,
        member.phone,
        member.first_name,
        member.last_name,
        member.city,
        member.country,
    ):
        assert len(value) == 64


# --- Whole lists ------------------------------------------------------
def test_a_row_that_identifies_nobody_is_dropped() -> None:
    """It would upload as six empty strings, which the provider counts as a
    row and matches to nobody - making the number on the screen a lie."""
    members = hashed_members(
        records=[
            CustomerRecord(),
            CustomerRecord(email="not-an-email"),
            CustomerRecord(email="real@example.com"),
        ]
    )

    assert len(members) == 1
    assert members[0].email == digest("real@example.com")


def test_a_row_with_only_a_city_still_counts_as_nobody_at_the_domain_level() -> None:
    """A city alone is a real value and identifies no one, so it survives
    the hashing and is filtered by the selector rather than here. What this
    pins is that hashing does not silently decide it."""
    members = hashed_members(records=[CustomerRecord(city="Toshkent")])

    assert len(members) == 1
    assert members[0].city == digest("toshkent")
    assert members[0].email == ""
