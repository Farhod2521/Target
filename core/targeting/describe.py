"""Reading a finished spec back into something a person recognises."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

GeoShape = Literal["", "around", "places", "country"]

_PLACE_KEYS: Final[tuple[str, ...]] = (
    "cities",
    "regions",
    "zips",
    "places",
    "geo_markets",
    "electoral_districts",
)
_COUNTRY_KEYS: Final[tuple[str, ...]] = ("countries", "country_groups")

_DETAILED_KEYS: Final[tuple[str, ...]] = (
    "interests",
    "behaviors",
    "life_events",
    "industries",
    "income",
    "family_statuses",
    "education_statuses",
    "work_positions",
)

_MALE: Final = 1
_FEMALE: Final = 2


@dataclass(frozen=True, slots=True)
class AudienceSketch:
    """What one spec is aimed at, as far as the spec itself can say."""

    geo: GeoShape = ""
    radius: int | None = None
    radius_unit: str = ""
    places: int = 0
    age_min: int | None = None
    age_max: int | None = None
    genders: Literal["", "male", "female"] = ""
    interests: int = 0
    uses_own_lists: bool = False
    excludes_own_lists: bool = False
    is_automatic: bool = False

    @property
    def is_empty(self) -> bool:
        """Whether the spec said nothing this sketch can report."""
        return not (
            self.geo
            or self.age_min
            or self.age_max
            or self.genders
            or self.interests
            or self.uses_own_lists
        )


def describe(spec: object) -> AudienceSketch:
    """One spec, sketched."""
    if not isinstance(spec, Mapping):
        return AudienceSketch()

    shape, radius, unit, places = _geography(spec.get("geo_locations"))
    return AudienceSketch(
        geo=shape,
        radius=radius,
        radius_unit=unit,
        places=places,
        age_min=_whole(spec.get("age_min")),
        age_max=_whole(spec.get("age_max")),
        genders=_genders(spec.get("genders")),
        interests=_detailed(spec.get("flexible_spec")),
        uses_own_lists=_nonempty(spec.get("custom_audiences")),
        excludes_own_lists=_nonempty(spec.get("excluded_custom_audiences")),
        is_automatic=_nonempty(spec.get("targeting_automation")),
    )


def _geography(block: Any) -> tuple[GeoShape, int | None, str, int]:
    """Which of the three shapes, and its one measurement."""
    if not isinstance(block, Mapping):
        return "", None, "", 0

    pins = block.get("custom_locations")
    if isinstance(pins, Sequence) and not isinstance(pins, str | bytes) and pins:
        first = pins[0] if isinstance(pins[0], Mapping) else {}
        return (
            "around",
            _whole(first.get("radius")),
            str(first.get("distance_unit", "")),
            len(pins),
        )

    named = sum(_count(block.get(key)) for key in _PLACE_KEYS)
    if named:
        return "places", None, "", named

    countries = sum(_count(block.get(key)) for key in _COUNTRY_KEYS)
    if countries:
        return "country", None, "", countries

    return "", None, "", 0


def _detailed(flexible: Any) -> int:
    """How many detailed-targeting rows the audience names, across blocks."""
    if not isinstance(flexible, Sequence) or isinstance(flexible, str | bytes):
        return 0
    return sum(
        _count(block.get(key))
        for block in flexible
        if isinstance(block, Mapping)
        for key in _DETAILED_KEYS
    )


def _genders(value: Any) -> Literal["", "male", "female"]:
    """One answer, and everybody is the answer for three different inputs."""
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ""
    numbers = {_whole(item) for item in value}
    if numbers == {_MALE}:
        return "male"
    if numbers == {_FEMALE}:
        return "female"
    return ""


def _count(value: Any) -> int:
    """Length, for something that is a list and zero for anything else."""
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return len(value)
    return 0


def _nonempty(value: Any) -> bool:
    """Whether a key carries anything at all."""
    if isinstance(value, Mapping):
        return bool(value)
    return _count(value) > 0


def _whole(value: Any) -> int | None:
    """An integer, or nothing."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


__all__ = ["AudienceSketch", "GeoShape", "describe"]
