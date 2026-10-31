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
from core.targeting.audiences import (
    EXCLUDE_KEY,
    INCLUDE_KEY,
    AudienceChoice,
    AudienceRef,
    fit,
)
from core.targeting.describe import _DETAILED_KEYS
from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import (
    DISTANCE_UNIT,
    GeoChoice,
    GeoPlace,
    geo_locations,
    pins,
    places_in,
)
from core.targeting.modes import AUTOMATIC_AGE_MAX, fit_automatic_ages, is_automatic
from core.targeting.validators import MAX_AGE, MIN_AGE, clamp_age, clamp_radius

MALE: Final = 1
FEMALE: Final = 2

_DETAILED_KEY: Final = "flexible_spec"
_EXCLUSIONS_KEY: Final = "exclusions"
_LOCALES_KEY: Final = "locales"
_WHERE_KEY: Final = "geo_locations"
_NOT_WHERE_KEY: Final = "excluded_geo_locations"
_WHERE_SETTINGS: Final = frozenset({"location_types", "location_cluster_ids"})


@dataclass(frozen=True, slots=True)
class Detail:
    """One row of detailed targeting; ``kind`` is the spec key it is filed under."""

    id: str
    name: str = ""
    kind: str = "interests"


@dataclass(frozen=True, slots=True)
class AudienceEdit:
    """The answers a person gave about one running audience."""

    age_min: int | None = None
    age_max: int | None = None
    genders: tuple[int, ...] | None = None
    radius_km: int | None = None
    keep_interests: bool = True
    places: tuple[GeoPlace, ...] | None = None
    detailed: tuple[Detail, ...] | None = None
    excluded_detailed: tuple[Detail, ...] | None = None
    included_lists: tuple[AudienceRef, ...] | None = None
    excluded_lists: tuple[AudienceRef, ...] | None = None
    locales: tuple[int, ...] | None = None
    excluded_places: tuple[GeoPlace, ...] | None = None
    pin: tuple[str, str] | None = None

    @property
    def is_empty(self) -> bool:
        """Whether this edit names nothing at all."""
        return (
            self.age_min is None
            and self.age_max is None
            and self.genders is None
            and self.radius_km is None
            and self.keep_interests
            and self.places is None
            and self.detailed is None
            and self.excluded_detailed is None
            and self.included_lists is None
            and self.excluded_lists is None
            and self.locales is None
            and self.excluded_places is None
            and self.pin is None
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
    _pin(result, edit=edit)
    _radius(result, notes, edit=edit, special=special)
    _interests(result, edit=edit)
    _detailed(result, edit=edit)
    _lists(result, notes, edit=edit)
    _locales(result, edit=edit)
    _places(result, edit=edit)
    _not_places(result, edit=edit)
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


def only_place_moved(before: Mapping[str, Any], after: Mapping[str, Any]) -> bool:
    """Whether two specs differ in where they reach and in nothing else."""
    rest = [
        {key: value for key, value in spec.items() if key != _WHERE_KEY}
        for spec in (before, after)
    ]
    return rest[0] == rest[1] and before.get(_WHERE_KEY) != after.get(_WHERE_KEY)


def _places(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Where it reaches, replaced whole; the block's own settings stay."""
    if edit.places is None:
        return
    choice = GeoChoice(mode="places", places=edit.places)
    spec[_WHERE_KEY] = geo_locations(choice) | _kept_where(spec)


def _pin(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """One point on the map in place of where it reached; ``_radius`` sets how far."""
    if edit.pin is None:
        return
    held = pins(spec)
    radius = edit.radius_km or (held[0].get("radius") if held else None)
    lat, lng = edit.pin
    choice = GeoChoice(mode="around", lat=lat, lng=lng, radius_km=radius)
    spec[_WHERE_KEY] = geo_locations(choice) | _kept_where(spec)


def _kept_where(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in (spec.get(_WHERE_KEY) or {}).items()
        if key in _WHERE_SETTINGS
    }


def _not_places(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Where it must not reach, replaced whole; none left removes the block."""
    if edit.excluded_places is None:
        return
    if not edit.excluded_places:
        spec.pop(_NOT_WHERE_KEY, None)
        return
    choice = GeoChoice(mode="places", places=edit.excluded_places)
    spec[_NOT_WHERE_KEY] = geo_locations(choice)


def _detailed(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Interests and the like, and who they rule out, each replaced whole."""
    if edit.detailed is not None:
        if not detail_is_open(spec):
            raise InvalidTargeting(
                "this audience narrows in several steps", field="flexible_spec"
            )
        if edit.detailed:
            spec[_DETAILED_KEY] = [_block(edit.detailed)]
        else:
            spec.pop(_DETAILED_KEY, None)
    if edit.excluded_detailed is not None:
        rest = {
            key: value
            for key, value in (spec.get(_EXCLUSIONS_KEY) or {}).items()
            if key not in _DETAILED_KEYS
        }
        written = rest | _block(edit.excluded_detailed)
        if written:
            spec[_EXCLUSIONS_KEY] = written
        else:
            spec.pop(_EXCLUSIONS_KEY, None)


def _block(rows: tuple[Detail, ...]) -> dict[str, list[dict[str, str]]]:
    block: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        if row.kind not in _DETAILED_KEYS:
            raise InvalidTargeting(f"{row.kind} is not detail", field="flexible_spec")
        block.setdefault(row.kind, []).append({"id": row.id, "name": row.name})
    return block


def _lists(
    spec: dict[str, Any], notes: list[Adjustment], *, edit: AudienceEdit
) -> None:
    """The owner's own audiences; a side not named stays as it is."""
    if edit.included_lists is None and edit.excluded_lists is None:
        return
    fit(
        spec,
        notes,
        choice=AudienceChoice(
            included=_side(spec, INCLUDE_KEY, edit.included_lists),
            excluded=_side(spec, EXCLUDE_KEY, edit.excluded_lists),
        ),
    )


def _side(
    spec: Mapping[str, Any], key: str, named: tuple[AudienceRef, ...] | None
) -> tuple[AudienceRef, ...]:
    if named is not None:
        return named
    return tuple(
        AudienceRef(external_id=str(row["id"]))
        for row in spec.get(key) or ()
        if isinstance(row, Mapping) and row.get("id")
    )


def _locales(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Which languages it reaches; none left is every language."""
    if edit.locales is None:
        return
    if edit.locales:
        spec[_LOCALES_KEY] = list(edit.locales)
    else:
        spec.pop(_LOCALES_KEY, None)


def detail_is_open(spec: Mapping[str, Any]) -> bool:
    """Whether the detail is one block: several narrow in steps only Ads Manager draws."""
    return len(spec.get(_DETAILED_KEY) or ()) <= 1


def detailed_of(spec: Mapping[str, Any]) -> tuple[Detail, ...]:
    """Every interest-like row the spec narrows by, whichever block holds it."""
    blocks = spec.get(_DETAILED_KEY) or ()
    return tuple(row for block in blocks for row in _rows(block))


def excluded_detailed_of(spec: Mapping[str, Any]) -> tuple[Detail, ...]:
    """Every interest-like row the spec rules out."""
    return _rows(spec.get(_EXCLUSIONS_KEY))


def excluded_places_of(spec: Mapping[str, Any]) -> tuple[GeoPlace, ...]:
    """The places the spec rules out."""
    return places_in(spec.get(_NOT_WHERE_KEY))


def _rows(block: object) -> tuple[Detail, ...]:
    if not isinstance(block, Mapping):
        return ()
    return tuple(
        Detail(id=str(row["id"]), name=str(row.get("name") or row["id"]), kind=key)
        for key in _DETAILED_KEYS
        for row in block.get(key) or ()
        if isinstance(row, Mapping) and row.get("id")
    )


def _interests(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Stop narrowing by interest at all, when that is what was asked."""
    if edit.keep_interests:
        return
    spec.pop(_DETAILED_KEY, None)


__all__ = [
    "FEMALE",
    "MALE",
    "AudienceEdit",
    "Detail",
    "changed",
    "detail_is_open",
    "detailed_of",
    "excluded_detailed_of",
    "excluded_places_of",
    "only_place_moved",
    "revise",
    "revised",
]
