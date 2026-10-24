"""Turning "people like these" into the spec Meta wants."""

from typing import Final

from adskit.dto import LookalikeSpecDTO
from adskit.refs import AudienceBreadth

SUBTYPE_LOOKALIKE: Final = "LOOKALIKE"

RATIOS: Final[dict[AudienceBreadth, float]] = {
    "closest": 0.01,
    "balanced": 0.05,
    "broad": 0.10,
}


def ratio_of(spec: LookalikeSpecDTO) -> str:
    """Meta's own number for this breadth, as text."""
    return f"{RATIOS[spec.breadth]:.2f}"


def lookalike_spec(spec: LookalikeSpecDTO) -> dict[str, object]:
    """The spec as Meta reads it. Two keys, and the seed is not one of them."""
    return {
        "ratio": RATIOS[spec.breadth],
        "country": spec.country.strip().upper(),
    }


__all__ = ["RATIOS", "SUBTYPE_LOOKALIKE", "lookalike_spec", "ratio_of"]
