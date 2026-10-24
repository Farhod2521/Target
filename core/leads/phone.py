"""Turning what somebody typed into a number that can be dialled.

Every phone number in this product is stored in E.164 - a plus, a country
code, and at most fifteen digits - because that is the only form that means
the same thing in two countries. ``shared.validators.validate_e164``
enforces the shape on the way into the database; this is what produces it.

Not a regex. A number arrives as "90 123 45 67", "+998 90 123-45-67",
"8 (901) 234-56-78" or twenty other shapes, and which of them is valid
depends on the country: the leading trunk zero that must be dropped in one
place is part of the number in another. Deciding that per country is
libphonenumber's whole job, and a hand-rolled version of it is a table of
special cases that grows with every market.

No country is privileged and none is written down here. The region comes
from the business profile, which is where the customer said what country
they operate in - see CLAUDE.md's rule against hard-coding "+998".

**Nothing here raises.** A lead whose phone cannot be parsed is still a
lead, and losing it because a person mistyped a digit would be losing the
thing the whole product exists to collect. An unusable number comes back
empty and the raw answer stays in ``field_data_raw``, which is the honest
record of what they actually wrote.
"""

import phonenumbers

# The two forms libphonenumber will accept as dialable. A number that is
# merely *possible* - right length, wrong prefix - is not stored: it would
# pass the validator, reach a CRM, and fail when somebody dialled it.
_VALID = (phonenumbers.PhoneNumberFormat.E164,)


def to_e164(*, raw: str, region: str = "") -> str:
    """``"90 123 45 67"``, ``"UZ"`` becomes ``"+998901234567"``.

    ``region`` is a two-letter ISO country code and is only consulted when
    the number does not carry its own country code. A number already
    written with a leading ``+`` parses the same whatever region is passed,
    which is why an empty one is not an error: a lead form that collected
    an international number needs no help.

    Returns ``""`` for anything that cannot be turned into a dialable
    number, including an empty input.
    """
    text = raw.strip()
    if not text:
        return ""

    try:
        parsed = phonenumbers.parse(text, region.strip().upper() or None)
    except phonenumbers.NumberParseException:
        return ""

    # `is_valid_number`, not `is_possible_number`. The second only checks
    # the length, so it accepts a number with a prefix no operator in the
    # country uses - which passes every check we have and fails when a
    # person dials it.
    if not phonenumbers.is_valid_number(parsed):
        return ""

    return phonenumbers.format_number(parsed, _VALID[0])


def for_display(e164: str) -> str:
    """``"+998712223344"`` as people write it: ``"+998 71 222 33 44"``.

    The country's own grouping, in spaces only - a dash reads as a minus
    on a small screen. Storage stays E.164; this is for what is shown. A
    number that does not parse comes back as it was.
    """
    try:
        parsed = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException:
        return e164
    shown = phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    return " ".join(shown.replace("-", " ").split())


def dial_code(region: str) -> str:
    """``"UZ"`` becomes ``"+998"``: the prefix a form prints before the box.

    Empty for a region libphonenumber does not know, so the caller draws no
    prefix rather than a wrong one.
    """
    code = phonenumbers.country_code_for_region(region.strip().upper())
    return f"+{code}" if code else ""


def example_national(region: str) -> str:
    """A mobile number of ``region`` as it is written at home, for a
    placeholder: ``"UZ"`` gives ``"91 234 56 78"``. Empty when unknown."""
    code = region.strip().upper()
    if not code:
        return ""
    example = phonenumbers.example_number_for_type(
        code, phonenumbers.PhoneNumberType.MOBILE
    )
    if example is None:
        return ""
    return phonenumbers.format_number(example, phonenumbers.PhoneNumberFormat.NATIONAL)


def example_international(region: str) -> str:
    """A mobile number of ``region`` as it is written abroad, for a
    placeholder and a typing pattern: ``"UZ"`` gives
    ``"+998 91 234 56 78"``. Empty when unknown."""
    code = region.strip().upper()
    if not code:
        return ""
    example = phonenumbers.example_number_for_type(
        code, phonenumbers.PhoneNumberType.MOBILE
    )
    if example is None:
        return ""
    return phonenumbers.format_number(
        example, phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )


__all__ = ["dial_code", "example_international", "example_national", "to_e164"]
