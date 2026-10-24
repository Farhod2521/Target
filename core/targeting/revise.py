"""Changing part of a running audience without losing the rest of it."""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import DISTANCE_UNIT, pins

MALE: Final = 1
FEMALE: Final = 2

_DETAILED_KEY: Final = "flexible_spec"


@dataclass(frozen=True, slots=True)
class AudienceEdit:
    """The answers a person gave about one running audience."""

    age_min: int | None = None
    age_max: int | None = None
    genders: tuple[int, ...] | None = None
    radius_km: int | None = None
    keep_interests: bool = True

    @property
    def is_empty(self) -> bool:
        """Whether this edit names nothing at all."""
        return (
            self.age_min is None
            and self.age_max is None
            and self.genders is None
            and self.radius_km is None
            and self.keep_interests
        )


def revise(spec: Mapping[str, Any], *, edit: AudienceEdit) -> dict[str, Any]:
    """The whole spec again, with only the named layers replaced."""
    if not isinstance(spec, Mapping) or not spec:
        raise InvalidTargeting("there is no stored audience to change", field="spec")

    revised = copy.deepcopy(dict(spec))
    _ages(revised, edit=edit)
    _genders(revised, edit=edit)
    _radius(revised, edit=edit)
    _interests(revised, edit=edit)
    return revised


def changed(spec: Mapping[str, Any], *, edit: AudienceEdit) -> bool:
    """Whether this edit would actually move anything."""
    return revise(spec, edit=edit) != dict(spec)


def _ages(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """The age range, both ends together or neither."""
    if edit.age_min is None and edit.age_max is None:
        return
    if edit.age_min is None or edit.age_max is None:
        raise InvalidTargeting("an age range needs both ends", field="age")
    if edit.age_min > edit.age_max:
        raise InvalidTargeting(
            f"age_min {edit.age_min} is above age_max {edit.age_max}", field="age"
        )

    spec["age_min"] = edit.age_min
    spec["age_max"] = edit.age_max


def _genders(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Who to show it to, where an empty answer removes the key entirely."""
    if edit.genders is None:
        return

    wanted = tuple(value for value in edit.genders if value in (MALE, FEMALE))
    if len(wanted) != len(set(wanted)):
        raise InvalidTargeting("a gender was named twice", field="genders")

    if not wanted or set(wanted) == {MALE, FEMALE}:
        spec.pop("genders", None)
        return
    spec["genders"] = list(wanted)


def _radius(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """How far the circle reaches, for an audience that is a circle."""
    if edit.radius_km is None:
        return
    if edit.radius_km <= 0:
        raise InvalidTargeting(
            f"radius {edit.radius_km} is not a distance", field="radius"
        )

    for place in pins(spec):
        if place.get("distance_unit", DISTANCE_UNIT) != DISTANCE_UNIT:
            continue
        place["radius"] = edit.radius_km


def _interests(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Stop narrowing by interest at all, when that is what was asked."""
    if edit.keep_interests:
        return
    spec.pop(_DETAILED_KEY, None)


__all__ = ["FEMALE", "MALE", "AudienceEdit", "changed", "revise"]
