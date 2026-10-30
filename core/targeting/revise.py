"""Changing part of a running audience without losing the rest of it.

Only what the edit names is written, and what is written obeys the rules the
launch's builder obeys (``validators``, ``modes``): the same age band, a
special category's limits, Advantage+'s ages. Whatever those rules moved is
returned as adjustments, so the owner is told rather than surprised.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.targeting.adjustments import Adjustment
from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import DISTANCE_UNIT, pins
from core.targeting.modes import AUTOMATIC_AGE_MAX, fit_automatic_ages, is_automatic
from core.targeting.validators import MAX_AGE, MIN_AGE, clamp_age, clamp_radius

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


def revise(
    spec: Mapping[str, Any], *, edit: AudienceEdit, special: bool = False
) -> dict[str, Any]:
    """The whole spec again, with only the named layers replaced."""
    return revised(spec, edit=edit, special=special)[0]


def revised(
    spec: Mapping[str, Any], *, edit: AudienceEdit, special: bool = False
) -> tuple[dict[str, Any], tuple[Adjustment, ...]]:
    """:func:`revise`, and what the rules changed of what was asked."""
    if not isinstance(spec, Mapping) or not spec:
        raise InvalidTargeting("there is no stored audience to change", field="spec")

    result = copy.deepcopy(dict(spec))
    notes: list[Adjustment] = []
    _ages(result, notes, edit=edit, special=special)
    _genders(result, notes, edit=edit, special=special)
    _radius(result, notes, edit=edit, special=special)
    _interests(result, edit=edit)
    return result, tuple(notes)


def changed(
    spec: Mapping[str, Any], *, edit: AudienceEdit, special: bool = False
) -> bool:
    """Whether this edit would actually move anything."""
    return revise(spec, edit=edit, special=special) != dict(spec)


def _ages(
    spec: dict[str, Any],
    notes: list[Adjustment],
    *,
    edit: AudienceEdit,
    special: bool,
) -> None:
    """The age range, both ends together or neither, inside the rules.

    An absent key is the provider's own default, so a range equal to what the
    spec already means is no change: the dialog shows 18-65 for a spec with
    no ages, and sending those back must not open a write.
    """
    if edit.age_min is None and edit.age_max is None:
        return
    if edit.age_min is None or edit.age_max is None:
        raise InvalidTargeting("an age range needs both ends", field="age")
    if edit.age_min > edit.age_max:
        raise InvalidTargeting(
            f"age_min {edit.age_min} is above age_max {edit.age_max}", field="age"
        )

    wanted: dict[str, Any] = {"age_min": edit.age_min, "age_max": edit.age_max}
    clamp_age(wanted, notes, special=special)
    if is_automatic(spec):
        if wanted["age_max"] == AUTOMATIC_AGE_MAX:
            del wanted["age_max"]
        fit_automatic_ages(wanted, notes)

    now = {
        "age_min": spec.get("age_min", MIN_AGE),
        "age_max": spec.get("age_max", MAX_AGE),
    }
    if all(now[key] == value for key, value in wanted.items()):
        return
    spec.update(wanted)


def _genders(
    spec: dict[str, Any],
    notes: list[Adjustment],
    *,
    edit: AudienceEdit,
    special: bool,
) -> None:
    """Who to show it to, where an empty answer removes the key entirely."""
    if edit.genders is None:
        return

    if any(value not in (MALE, FEMALE) for value in edit.genders):
        raise InvalidTargeting(f"{edit.genders} is not a gender", field="genders")
    wanted = tuple(edit.genders)
    if len(wanted) != len(set(wanted)):
        raise InvalidTargeting("a gender was named twice", field="genders")

    everybody = not wanted or set(wanted) == {MALE, FEMALE}
    if special:
        if not everybody:
            notes.append(Adjustment(field="genders", reason="special_ad_category"))
        return
    if everybody:
        spec.pop("genders", None)
        return
    spec["genders"] = list(wanted)


def _radius(
    spec: dict[str, Any],
    notes: list[Adjustment],
    *,
    edit: AudienceEdit,
    special: bool,
) -> None:
    """How far the circle reaches, for an audience that is a circle."""
    if edit.radius_km is None:
        return
    if edit.radius_km <= 0:
        raise InvalidTargeting(
            f"radius {edit.radius_km} is not a distance", field="radius"
        )

    ours = [
        place
        for place in pins(spec)
        if place.get("distance_unit", DISTANCE_UNIT) == DISTANCE_UNIT
    ]
    for place in ours:
        place["radius"] = edit.radius_km
    clamp_radius({"geo_locations": {"custom_locations": ours}}, notes, special=special)


def _interests(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Stop narrowing by interest at all, when that is what was asked."""
    if edit.keep_interests:
        return
    spec.pop(_DETAILED_KEY, None)


__all__ = ["FEMALE", "MALE", "AudienceEdit", "changed", "revise", "revised"]
