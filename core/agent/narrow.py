"""One step inward, when part of the audience only ever spent money."""

import copy
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from core.metrics import UNKNOWN, split_segment
from core.targeting import MAX_AGE, MIN_AGE
from core.targeting.modes import AUTOMATION_FIELD, AUTOMATION_KEY, AUTOMATION_OFF

NarrowingStep = Literal["age", "gender"]

GENDER_CODES: Final[Mapping[str, int]] = {"male": 1, "female": 2}


@dataclass(frozen=True, slots=True)
class Narrowing:
    """A spec that stops paying for a dead slice, and which slice it was."""

    step: NarrowingStep
    targeting: dict[str, Any]
    detail: Mapping[str, Any] = field(default_factory=dict)


def keeps_its_audience(targeting: Mapping[str, Any]) -> bool:
    """Whether the advertiser's own audience is still the audience here."""
    block = targeting.get(AUTOMATION_KEY)
    if not isinstance(block, dict):
        return False
    return block.get(AUTOMATION_FIELD) == AUTOMATION_OFF


def narrow(
    targeting: Mapping[str, Any],
    *,
    dead: Mapping[str, int],
    alive: Collection[str],
) -> Narrowing | None:
    """The next single step inward, or ``None`` when none can be expressed."""
    if not dead or not keeps_its_audience(targeting):
        return None
    for attempt in (_age, _gender):
        found = attempt(targeting, dead, alive)
        if found is not None:
            return found
    return None


def _age(
    targeting: Mapping[str, Any], dead: Mapping[str, int], alive: Collection[str]
) -> Narrowing | None:
    """Stop paying for the youngest or the oldest band."""
    bands = _bands(dead, alive)
    if len(bands) < 2:
        return None

    low = _as_int(targeting.get("age_min")) or MIN_AGE
    high = _as_int(targeting.get("age_max")) or MAX_AGE

    bottom, top = bands[0], bands[-1]
    options: list[tuple[int, str, int]] = []
    if bottom.is_dead and bottom.high + 1 > low and bottom.high + 1 < high:
        options.append((bottom.spend, "age_min", bottom.high + 1))
    if top.is_dead and top.low - 1 < high and top.low - 1 > low:
        options.append((top.spend, "age_max", top.low - 1))
    if not options:
        return None

    spend, field_name, value = max(options, key=lambda item: item[0])
    spec = copy.deepcopy(dict(targeting))
    before = low if field_name == "age_min" else high
    spec[field_name] = value

    return Narrowing(
        step="age",
        targeting=spec,
        detail={
            "cut": field_name,
            "from_age": before,
            "to_age": value,
            "dropped_spend_minor": spend,
        },
    )


def _gender(
    targeting: Mapping[str, Any], dead: Mapping[str, int], alive: Collection[str]
) -> Narrowing | None:
    """Stop showing the ad to a gender that never once responded."""
    if targeting.get("genders"):
        return None

    dead_genders = {
        gender: sum(spend for name, spend in dead.items() if _gender_of(name) == gender)
        for gender in {_gender_of(name) for name in dead}
        if gender in GENDER_CODES
    }
    live_genders = {_gender_of(name) for name in alive} & set(GENDER_CODES)

    cuttable = {
        name: spend for name, spend in dead_genders.items() if name not in live_genders
    }
    keep = live_genders - set(cuttable)
    if len(cuttable) != 1 or not keep:
        return None

    dropped, spend = next(iter(cuttable.items()))
    spec = copy.deepcopy(dict(targeting))
    spec["genders"] = sorted(GENDER_CODES[name] for name in keep)

    return Narrowing(
        step="gender",
        targeting=spec,
        detail={"dropped_gender": dropped, "dropped_spend_minor": spend},
    )


@dataclass(frozen=True, slots=True)
class _Band:
    """One age bucket of the report, and what became of it."""

    low: int
    high: int
    spend: int
    is_dead: bool


def _bands(dead: Mapping[str, int], alive: Collection[str]) -> list[_Band]:
    """Every age band the comparison saw, youngest first."""
    live_ages = {_age_of(name) for name in alive}
    spent: dict[str, int] = {}
    for name, spend in dead.items():
        bucket = _age_of(name)
        if bucket == UNKNOWN:
            continue
        spent[bucket] = spent.get(bucket, 0) + spend

    bands: list[_Band] = []
    for bucket in spent.keys() | live_ages:
        edges = _edges(bucket)
        if edges is None:
            continue
        bands.append(
            _Band(
                low=edges[0],
                high=edges[1],
                spend=spent.get(bucket, 0),
                is_dead=bucket in spent and bucket not in live_ages,
            )
        )
    return sorted(bands, key=lambda band: band.low)


def _edges(bucket: str) -> tuple[int, int] | None:
    """``"25-34"`` as ``(25, 34)``, ``"65+"`` as ``(65, 65)``."""
    text = bucket.strip()
    if text.endswith("+"):
        low = _as_int(text[:-1])
        return None if low is None else (low, MAX_AGE)
    if "-" not in text:
        return None
    low_text, _, high_text = text.partition("-")
    low, high = _as_int(low_text), _as_int(high_text)
    if low is None or high is None or high < low:
        return None
    return (low, high)


def _age_of(segment: str) -> str:
    return split_segment(segment)[0]


def _gender_of(segment: str) -> str:
    parts = split_segment(segment)
    return parts[1] if len(parts) > 1 else UNKNOWN


def _as_int(value: Any) -> int | None:
    """A figure as a whole number, or nothing - see ``widen._as_int``."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except ValueError:
        return None


__all__ = [
    "GENDER_CODES",
    "Narrowing",
    "NarrowingStep",
    "keeps_its_audience",
    "narrow",
]
