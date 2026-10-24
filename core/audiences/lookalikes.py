"""Deciding what a new audience should be built to resemble."""

from typing import Final, get_args

from adskit import AudienceBreadth, ExternalRef, LookalikeSpecDTO

from core.audiences.exceptions import BreadthNotOffered, CountryUnknown
from core.audiences.members import COUNTRY_CODE_LENGTH

BREADTHS: Final[tuple[AudienceBreadth, ...]] = get_args(AudienceBreadth)


def build_lookalike(
    *, origin: ExternalRef, breadth: str, country: str
) -> LookalikeSpecDTO:
    """Check the choice, and name what should be built."""
    if breadth not in BREADTHS:
        raise BreadthNotOffered(breadth=breadth)

    code = country.strip().upper()
    if len(code) != COUNTRY_CODE_LENGTH:
        raise CountryUnknown(country=country)

    return LookalikeSpecDTO(
        origin=origin,
        breadth=breadth,
        country=code,
    )


__all__ = ["BREADTHS", "build_lookalike"]
