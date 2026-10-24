"""Turning what somebody typed into a number that can be dialled."""

import phonenumbers

_VALID = (phonenumbers.PhoneNumberFormat.E164,)


def to_e164(*, raw: str, region: str = "") -> str:
    """``"90 123 45 67"``, ``"UZ"`` becomes ``"+998901234567"``."""
    text = raw.strip()
    if not text:
        return ""

    try:
        parsed = phonenumbers.parse(text, region.strip().upper() or None)
    except phonenumbers.NumberParseException:
        return ""

    if not phonenumbers.is_valid_number(parsed):
        return ""

    return phonenumbers.format_number(parsed, _VALID[0])


def for_display(e164: str) -> str:
    """``"+998712223344"`` as people write it: ``"+998 71 222 33 44"``."""
    try:
        parsed = phonenumbers.parse(e164, None)
    except phonenumbers.NumberParseException:
        return e164
    shown = phonenumbers.format_number(
        parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    return " ".join(shown.replace("-", " ").split())


def dial_code(region: str) -> str:
    """``"UZ"`` becomes ``"+998"``: the prefix a form prints before the box."""
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
