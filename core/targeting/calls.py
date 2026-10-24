"""The number a call ad dials, and the two things that can be wrong with it."""

import phonenumbers

from core.leads.phone import to_e164


def dialable(*, raw: str, region: str) -> str:
    """What was typed, as a number that can be rung, or ``""``."""
    return to_e164(raw=raw, region=region)


def region_of(number: str) -> str:
    """Which country a dialable number belongs to, as an ISO-3166 code."""
    try:
        parsed = phonenumbers.parse(number, None)
    except phonenumbers.NumberParseException:
        return ""
    return phonenumbers.region_code_for_number(parsed) or ""


def is_local(*, number: str, region: str) -> bool:
    """Whether the number is from the country the ad will be shown in."""
    wanted = region.strip().upper()
    if not wanted:
        return True
    found = region_of(number)
    if not found:
        return True
    return found == wanted


__all__ = ["dialable", "is_local", "region_of"]
