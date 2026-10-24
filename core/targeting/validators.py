"""The half of validation that needs no network.

Two stages exist because ``core/`` cannot make an HTTP call. This is the
structural one: shapes, ranges, and the rules that follow from a Special Ad
Category. The live one - does this interest id exist, how many people does
this reach - runs in a Celery task against the provider, and its answer
arrives back here as data.

**Everything here corrects rather than refuses**, with one exception -
a budget below the account's floor, which is arithmetic rather than
judgement. A radius of 200 km is not a reason to stop the wizard; it is a
reason to send 80 and say so.

The refusals live next door in :mod:`core.targeting.gate`, and the split
is that sentence: this module rewrites a spec so it can be sent, and that
one decides whether sending it is allowed at all. They also run at
different moments - this one on every edit of the review screen, that one
once, when the button is pressed.
"""

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

# The provider's own limits. Below 18 is illegal in most markets and the
# provider refuses it; above 65 it stops distinguishing ages at all.
MIN_AGE = 18
MAX_AGE = 65

MIN_RADIUS_KM = 1
MAX_RADIUS_KM = 80

# A Special Ad Category forbids tight geography. The floor is the provider's,
# not ours, and a smaller radius is rejected outright rather than widened.
SPECIAL_MIN_RADIUS_KM = 24

# What a Special Ad Category removes outright. Housing, employment and
# credit ads may not choose their audience by who the audience is - that is
# the whole point of the category, and a spec that tries is refused.
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
    """Check a rendered spec, correcting what can be corrected.

    ``min_daily_minor`` is zero when nobody knows it yet - the provider
    publishes a different floor per currency and per account, and it is read
    from the connected account rather than written down here. Zero means the
    budget check does not run, which is honest: a made-up minimum would
    block real campaigns for a number we invented.

    ``targeting_mode`` is applied **after the category**, and the order is
    load-bearing in both directions. A Special Ad Category pins the age at
    18-65 first, so the automatic mode finds an age range it already agrees
    with; and the switch it writes has to survive :func:`_drop_empty` below,
    which it does because it is never empty. See :mod:`core.targeting.modes`.

    ``audiences`` is applied after it and for the same reason - an empty
    side must be absent rather than ``[]`` - and after the category, which
    takes nothing away here: custom audience inclusion and exclusion are
    both listed as available beside one. The rule a category *does* impose
    on them is refused rather than corrected, in :func:`validate_launchable`.

    ``placement_mode`` is applied after all three and **takes nothing from
    the category**, which is a decision rather than an omission: the
    provider's restrictions on housing, employment and credit ads are about
    who may be targeted, and its documentation names no placement among
    them. Inventing one here would narrow delivery on a rule nobody wrote.
    See :mod:`core.targeting.placements`.
    """
    _check_budget(given=daily_budget_minor, minimum=min_daily_minor, currency=currency)

    spec = copy.deepcopy(dict(targeting))
    notes: list[Adjustment] = []

    _clamp_age(spec, notes, special=bool(special_ad_category))
    _clamp_radius(spec, notes, special=bool(special_ad_category))
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


def _clamp_age(spec: dict[str, Any], notes: list[Adjustment], *, special: bool) -> None:
    """Pull the age range inside what the provider accepts.

    A preset that names no age at all keeps naming none - inventing 18-65
    would mean the same thing to the provider but would report an
    adjustment the owner never made.
    """
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


def _clamp_radius(
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
    """Silently, and only for empties.

    An absent ``genders`` and an empty ``genders`` mean the same thing to
    the provider - everyone - so removing one is not a change the owner
    needs told about. Sending the empty list, on the other hand, is an error
    on some fields and a no-op on others, which is the worst of both.

    One key is not like the others and it is worth naming: a position list
    emptied by the retirement table leaves that platform's positions to the
    provider's default, which is *all* of them. It cannot happen with
    today's standard list - none of its values is retired, and a test says
    so - but the day it can, the honest fix is to drop the platform rather
    than to send an empty list of its positions. See
    :mod:`core.targeting.placements`.
    """
    for key in [key for key, value in spec.items() if value in ([], {}, "")]:
        del spec[key]
