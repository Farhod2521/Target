"""Deciding what a new audience should be built to resemble.

The third way to make one, and the second that touches no personal data.
:mod:`core.audiences.members` prepares people this business holds;
:mod:`core.audiences.rules` describes people the provider already knows
about; this names an audience that already exists and asks for more people
like the ones in it. Nobody's details are read, hashed or sent at any point
- not even the seed's, which stays where it is.

What the domain says is three things and none of them is a number. The
provider's own spelling - a ratio between one and twenty hundredths, a
subtype string, an origin id that sits outside the spec it looks like it
belongs to - is assembled in the adapter, exactly as the money rules and
the rule envelope are.

**The number is worth its own paragraph, because leaving it out is the
whole design.** Meta takes a percentage. Google takes an enum of three
words and has no percentage anywhere in its API. A domain that stored "five
per cent" would hold a figure the second platform cannot be told, and the
first thing a Google adapter would have to do is guess a mapping back out
of it. Storing the intent instead makes both adapters a table lookup - and
it happens to be the better product answer too, because nobody running a
shop knows what the top five per cent of a country is.

No Django, no clock, no configuration.
"""

from typing import Final, get_args

from adskit import AudienceBreadth, ExternalRef, LookalikeSpecDTO

from core.audiences.exceptions import BreadthNotOffered, CountryUnknown
from core.audiences.members import COUNTRY_CODE_LENGTH

# The choices offered, widest match last.
#
# Derived from the type rather than written out again, so a value added to
# one and forgotten in the other is impossible. The order is the type's,
# and the type's order is the order a picker shows: tightest first, because
# that is where an advertiser with a good seed should start.
BREADTHS: Final[tuple[AudienceBreadth, ...]] = get_args(AudienceBreadth)


def build_lookalike(
    *, origin: ExternalRef, breadth: str, country: str
) -> LookalikeSpecDTO:
    """Check the choice, and name what should be built.

    Checked here rather than at the provider, and the difference is what
    the person sees: a refusal from a provider names a code, and one from
    here names the field somebody has to go and fix.

    **What is deliberately not checked is the size of the seed.** Every
    platform asks for a hundred people *in the chosen country*, and none of
    them will report a figure cut that way - the count that comes back is a
    total across everywhere. So a seed with three hundred people split over
    two countries passes everything that can be checked from this side and
    can still be refused. That refusal is left to arrive in the provider's
    own words rather than pre-empted by arithmetic on a number that does
    not mean what it would have to mean.

    ``origin`` is not validated beyond its type, and the type is doing the
    work: an :class:`~adskit.ExternalRef` carries which provider issued the
    id. It matters more here than anywhere else, because one audience id
    looks exactly like another - nothing but the provider on the ref could
    catch a seed belonging to a different platform.
    """
    if breadth not in BREADTHS:
        raise BreadthNotOffered(breadth=breadth)
    # Narrowed to ``AudienceBreadth`` by the check above, and deriving
    # :data:`BREADTHS` from the type is what makes that true rather than
    # merely likely: a hand-written tuple would need a cast here, and a
    # cast is what silently survives a value being added to one and not
    # the other.

    code = country.strip().upper()
    if len(code) != COUNTRY_CODE_LENGTH:
        raise CountryUnknown(country=country)

    return LookalikeSpecDTO(
        origin=origin,
        breadth=breadth,
        country=code,
    )


__all__ = ["BREADTHS", "build_lookalike"]
