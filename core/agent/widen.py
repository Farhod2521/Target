"""One step outward, when the provider cannot find enough people."""

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from core.targeting import DISTANCE_UNIT, MAX_AGE, MAX_RADIUS_KM, MIN_AGE, pins

WideningStep = Literal["radius", "age", "interests"]

RADIUS_FACTOR: Final = 2

AGE_STEP: Final = 5


@dataclass(frozen=True, slots=True)
class Widening:
    """A spec that reaches further, and what was given up to get there."""

    step: WideningStep
    targeting: dict[str, Any]
    detail: Mapping[str, Any] = field(default_factory=dict)


def widen(targeting: Mapping[str, Any]) -> Widening | None:
    """The next single step outward, or ``None`` at the widest."""
    for attempt in (_radius, _age, _interests):
        found = attempt(targeting)
        if found is not None:
            return found
    return None


def _radius(targeting: Mapping[str, Any]) -> Widening | None:
    """Draw the circle wider."""
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
    """Accept people a few years either side."""
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
    """Stop narrowing by interest at all."""
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
    """A provider figure as a whole number, or nothing."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except ValueError:
        return None


__all__ = ["AGE_STEP", "RADIUS_FACTOR", "Widening", "WideningStep", "widen"]
