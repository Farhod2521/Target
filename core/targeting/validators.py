"""The half of validation that needs no network."""

import copy
from collections.abc import Mapping
from typing import Any

from core.targeting.adjustments import Adjustment
from core.targeting.audiences import AudienceChoice
from core.targeting.audiences import fit as fit_audiences
from core.targeting.exceptions import BudgetTooLow, InvalidTargeting
from core.targeting.modes import DEFAULT_TARGETING_MODE, TargetingMode
from core.targeting.modes import fit as fit_mode
from core.targeting.placements import DEFAULT_PLACEMENT_MODE, PlacementMode
from core.targeting.placements import fit as fit_placements

MIN_AGE = 18
MAX_AGE = 65

MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 80

SPECIAL_MIN_RADIUS_KM = 24

SPECIAL_FORBIDDEN = (
    "genders",
    "flexible_spec",
    "interests",
    "behaviors",
    "exclusions",
    "excluded_publisher_categories",
)


def validate_structure(
    targeting: Mapping[str, Any],
    *,
    special_ad_category: str = "",
    daily_budget_minor: int = 0,
    min_daily_minor: int = 0,
    currency: str = "",
    targeting_mode: TargetingMode = DEFAULT_TARGETING_MODE,
    placement_mode: PlacementMode = DEFAULT_PLACEMENT_MODE,
    audiences: AudienceChoice | None = None,
) -> tuple[dict[str, Any], tuple[Adjustment, ...]]:
    """Check a rendered spec, correcting what can be corrected."""
    _check_budget(given=daily_budget_minor, minimum=min_daily_minor, currency=currency)

    spec = copy.deepcopy(dict(targeting))
    notes: list[Adjustment] = []

    clamp_age(spec, notes, special=bool(special_ad_category))
    clamp_radius(spec, notes, special=bool(special_ad_category))
    if special_ad_category:
        _apply_special_category(spec, notes, category=special_ad_category)
    fit_mode(spec, notes, mode=targeting_mode)
    fit_audiences(spec, notes, choice=audiences or AudienceChoice())
    fit_placements(spec, notes, mode=placement_mode)
    _drop_empty(spec)

    return spec, tuple(notes)


def _check_budget(*, given: int, minimum: int, currency: str) -> None:
    if minimum > 0 and given < minimum:
        raise BudgetTooLow(given_minor=given, minimum_minor=minimum, currency=currency)


def clamp_age(spec: dict[str, Any], notes: list[Adjustment], *, special: bool) -> None:
    """Pull the age range inside what the provider accepts."""
    if not special and "age_min" not in spec and "age_max" not in spec:
        return

    low = int(spec.get("age_min", MIN_AGE) or MIN_AGE)
    high = int(spec.get("age_max", MAX_AGE) or MAX_AGE)
    if low > high:
        raise InvalidTargeting(f"age_min {low} is above age_max {high}", field="age")

    if special:
        low, high = MIN_AGE, MAX_AGE
    else:
        low = max(low, MIN_AGE)
        high = min(high, MAX_AGE)

    if low != spec.get("age_min") or high != spec.get("age_max"):
        notes.append(
            Adjustment(
                field="age",
                reason="special_ad_category" if special else "age_out_of_range",
                detail=f"{low}-{high}",
            )
        )
    spec["age_min"] = low
    spec["age_max"] = high


def clamp_radius(
    spec: dict[str, Any], notes: list[Adjustment], *, special: bool
) -> None:
    """Every custom location's radius, inside the allowed band."""
    floor = SPECIAL_MIN_RADIUS_KM if special else MIN_RADIUS_KM
    for location in _custom_locations(spec):
        given = int(location.get("radius", floor) or floor)
        allowed = min(max(given, floor), MAX_RADIUS_KM)
        if allowed != given:
            notes.append(
                Adjustment(
                    field="radius",
                    reason="special_ad_category" if special else "radius_out_of_range",
                    detail=f"{given}->{allowed}",
                )
            )
        location["radius"] = allowed


def _apply_special_category(
    spec: dict[str, Any], notes: list[Adjustment], *, category: str
) -> None:
    """Remove what the category forbids, and say which category forbade it."""
    for key in SPECIAL_FORBIDDEN:
        if spec.pop(key, None) is not None:
            notes.append(
                Adjustment(field=key, reason="special_ad_category", detail=category)
            )


def _custom_locations(spec: dict[str, Any]) -> list[dict[str, Any]]:
    geo = spec.get("geo_locations")
    if not isinstance(geo, dict):
        return []
    locations = geo.get("custom_locations")
    if not isinstance(locations, list):
        return []
    return [item for item in locations if isinstance(item, dict)]


def _drop_empty(spec: dict[str, Any]) -> None:
    """Silently, and only for empties."""
    for key in [key for key, value in spec.items() if value in ([], {}, "")]:
        del spec[key]
