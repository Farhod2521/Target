"""The number a call ad dials, and the two things that can be wrong with it.

A call ad buys one thing: somebody tapping the button and their phone
ringing at the business. Everything that decides whether that happens is
in one string, and the string is the only part of this flow the provider
cannot supply, correct or complain about.

**Meta takes the number in the button and from nowhere else.** Not from
the Page, which has one; not from the ad account; not from the preset. The
call-ads guide puts it in ``call_to_action.value.link`` as ``tel:+…`` while
the creative's own ``link`` stays a formality, exactly as it is on a lead
ad. So a number nobody typed is not a call ad missing a number - it is the
*other* branch of that same key, a button that opens a web page, which
Meta accepts and runs and reports clicks for.

Two checks, and they fail in the same silence:

``dialable``   the number has to parse into E.164 for the country the
               business operates in. A number that does not is stored as
               typed, dialled by nobody, and looks fine on every screen.
``local``      Meta's own limitation, quoted: *"The phone number included
               in Call to Action must be from the same country as the
               target audience."* A Tashkent shop advertising in Uzbekistan
               with a Russian mobile in the button is a campaign that
               delivers and never rings.

Neither raises here. This module answers questions; the form and the gate
are what refuse, in the reader's own language - the same division every
other module in this package keeps.

The country is never written down. It arrives from the business profile,
which is where the advertiser said which country they operate in, and
CLAUDE.md's rule against hard-coding a dialling prefix is the reason there
is no default anywhere below.
"""

import phonenumbers

from core.leads.phone import to_e164


def dialable(*, raw: str, region: str) -> str:
    """What was typed, as a number that can be rung, or ``""``.

    ``region`` is the two-letter country the business operates in, and it
    is only consulted when the number does not carry its own country code -
    a bare local number needs it and one already written with a leading
    plus does not.

    The same function the lead pipeline normalises with, deliberately.
    A number this product dials and a number a customer left have to mean
    the same thing, and two spellings of "turn this into E.164" drift.
    """
    return to_e164(raw=raw, region=region)


def region_of(number: str) -> str:
    """Which country a dialable number belongs to, as an ISO-3166 code.

    ``""`` when the number cannot be parsed or belongs to no single country
    - a shared code such as +882 is real and is nobody's country. Empty is
    "cannot tell", never "wrong", which is why :func:`is_local` treats it
    as permission to carry on.
    """
    try:
        parsed = phonenumbers.parse(number, None)
    except phonenumbers.NumberParseException:
        return ""
    return phonenumbers.region_code_for_number(parsed) or ""


def is_local(*, number: str, region: str) -> bool:
    """Whether the number is from the country the ad will be shown in.

    Meta's limitation rather than a preference, and it is the kind that
    does not fail loudly: the ad set is created, the ad delivers, the
    button appears, and the call is never placed.

    **Unknown answers yes.** A business profile with no country, a number
    no country claims - neither is evidence of a mismatch, and refusing a
    launch over a question nobody could answer is the more expensive
    mistake. The same rule ``preflight`` follows for every field Meta has
    not told us about.
    """
    wanted = region.strip().upper()
    if not wanted:
        return True
    found = region_of(number)
    if not found:
        return True
    return found == wanted


__all__ = ["dialable", "is_local", "region_of"]
