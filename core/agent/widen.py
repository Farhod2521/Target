"""One step outward, when the provider cannot find enough people.

An ad set that spends a third of its budget is not performing badly - it is
barely running. No amount of money fixes that, because the money is not the
constraint: the audience is. The only useful change is to make the audience
bigger, and this module works out what the next smallest way to do that is.

**One step at a time, and always the gentlest one left.** Widening is
irreversible in the sense that matters: it throws away the delivery the ad
set has learned, and it also throws away the owner's own intent, one layer
at a time. So the order runs from the change that costs least meaning to
the change that costs most - reach further, then accept more ages, then
stop asking about interests at all. A night that widens the radius and
finds it was enough never touches the interests.

Meta-shaped, like ``core.targeting.builder`` and for the reason CLAUDE.md
gives: an intent abstraction invented from one provider would be shaped
like that provider. This is the only module in ``core.agent`` that knows
what a targeting key means.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from core.targeting import DISTANCE_UNIT, MAX_AGE, MAX_RADIUS_KM, MIN_AGE, pins

# Which layer of the audience was loosened. Codes, not sentences: the
# Django layer turns them into Uzbek, the same as every other domain word
# a person eventually reads.
WideningStep = Literal["radius", "age", "interests"]

# How much further, in one step. Doubling rather than a fixed number of
# kilometres, because the same +10 km is a rounding error around a capital
# and a different province around a small town.
RADIUS_FACTOR: Final = 2

# How many years are added to each end of the age range in one step.
AGE_STEP: Final = 5


@dataclass(frozen=True, slots=True)
class Widening:
    """A spec that reaches further, and what was given up to get there."""

    step: WideningStep
    targeting: dict[str, Any]
    # The numbers behind the sentence: from 5 km to 10 km, from six
    # interests to none. Stored on the suggestion so the explanation can be
    # rebuilt without the spec it came from.
    detail: Mapping[str, Any] = field(default_factory=dict)


def widen(targeting: Mapping[str, Any]) -> Widening | None:
    """The next single step outward, or ``None`` at the widest.

    ``None`` is an answer, not a failure. An ad set already showing to
    every adult in the country with no interest filter cannot be widened,
    and proposing something anyway would be the agent inventing work.
    """
    for attempt in (_radius, _age, _interests):
        found = attempt(targeting)
        if found is not None:
            return found
    return None


def _radius(targeting: Mapping[str, Any]) -> Widening | None:
    """Draw the circle wider.

    Only for a pin. Named cities and whole countries have no radius - a
    delivery service covering Tashkent is not "within N km of" anything -
    and a radius invented for them would replace the outline of a city
    with a circle that misses half its districts.

    Locations in another unit are left alone. This product shows kilometres
    and sends kilometres; a spec written elsewhere in miles is somebody
    else's decision and doubling a number whose unit we did not check is
    how an ad set ends up advertising to a neighbouring country.

    **The pins are read through** ``core.targeting.pins``, not off the top
    of the spec. A real spec keeps its locations under ``geo_locations`` -
    that is what the builder writes and what the ad set stores - so a read
    off the top finds nothing, finds it silently, and this step never fires
    at all. Nothing fails visibly: the agent simply goes straight to
    widening the ages, which is the step after this one and costs more of
    the owner's intent.
    """
    spec = copy.deepcopy(dict(targeting))
    places = pins(spec)
    if not places:
        return None

    before: list[int] = []
    after: list[int] = []

    for place in places:
        if place.get("distance_unit", DISTANCE_UNIT) != DISTANCE_UNIT:
            continue
        current = _as_int(place.get("radius"))
        if current is None or current >= MAX_RADIUS_KM:
            continue
        widened = min(current * RADIUS_FACTOR, MAX_RADIUS_KM)
        place["radius"] = widened
        before.append(current)
        after.append(widened)

    if not after:
        return None

    return Widening(
        step="radius",
        targeting=spec,
        detail={"from_km": max(before), "to_km": max(after)},
    )


def _age(targeting: Mapping[str, Any]) -> Widening | None:
    """Accept people a few years either side.

    Both ends move together. Moving one would turn a range somebody chose
    into a range nobody did - "25 to 45" becoming "25 to 50" reads as a
    decision about older customers, and the agent made no such decision. It
    is loosening a constraint, not aiming somewhere new.
    """
    low = _as_int(targeting.get("age_min")) or MIN_AGE
    high = _as_int(targeting.get("age_max")) or MAX_AGE

    wider_low = max(MIN_AGE, low - AGE_STEP)
    wider_high = min(MAX_AGE, high + AGE_STEP)
    if (wider_low, wider_high) == (low, high):
        return None

    spec = copy.deepcopy(dict(targeting))
    spec["age_min"] = wider_low
    spec["age_max"] = wider_high

    return Widening(
        step="age",
        targeting=spec,
        detail={
            "from_min": low,
            "from_max": high,
            "to_min": wider_low,
            "to_max": wider_high,
        },
    )


def _interests(targeting: Mapping[str, Any]) -> Widening | None:
    """Stop narrowing by interest at all.

    The last step and much the largest, which is why it is last. Interests
    are the part of the audience the owner picked by hand off a screen, and
    removing them is the agent overruling the one choice it was most
    clearly told about - worth doing only when reaching further and
    accepting more ages have both already failed to fill the budget.

    Removed whole rather than trimmed. There is no evidence for which
    interest is the dead weight: the provider reports spend per ad set and
    never per interest, so picking one to drop would be a guess dressed up
    as a decision.
    """
    blocks = targeting.get("flexible_spec")
    if not isinstance(blocks, list) or not blocks:
        return None

    dropped = sum(
        len(block["interests"])
        for block in blocks
        if isinstance(block, dict) and isinstance(block.get("interests"), list)
    )
    if dropped <= 0:
        return None

    spec = copy.deepcopy(dict(targeting))
    del spec["flexible_spec"]

    return Widening(step="interests", targeting=spec, detail={"dropped": dropped})


def _as_int(value: Any) -> int | None:
    """A provider figure as a whole number, or nothing.

    Meta answers with strings as often as with numbers and with ``null``
    for "not set". A ``None`` here means "no such constraint", which is
    what every caller above treats as nothing left to loosen.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None


__all__ = ["AGE_STEP", "RADIUS_FACTOR", "Widening", "WideningStep", "widen"]
