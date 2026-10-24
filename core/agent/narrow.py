"""One step inward, when part of the audience only ever spent money.

The mirror of :mod:`core.agent.widen`, and it exists for the opposite
complaint: not "the provider cannot find enough people" but "it found
them, and a whole slice of them never once filled in a form". The remedy
is the same kind of change - the ad set's audience is replaced - and the
discipline is the same: one step at a time, the gentlest one left.

**A slice can only be cut out if the provider can express it.** An ad set
has one age range and one gender list, so an arbitrary cell - thirty-five
to forty-four year old men, while the women of that age convert fine -
cannot be excluded at all. Two shapes can: an age band at either **end**
of the range, and a gender when the whole of it is dead. Everything else
comes back ``None``, which is an answer rather than a failure.

**Under the provider's own audience automation, none of it holds.** Its
documentation names what it will not expand past - *"location constraints,
minimum age, language, and custom audience exclusions"* - and a maximum
age and a gender are not on that list: they are suggestions it may deliver
beyond. So narrowing either one there is a change that would be accepted,
recorded, and quietly ignored, which is worse than no change at all. The
switch is read only where it is present and explicit; an absent one is not
read as "off" - see :func:`keeps_its_audience`.

Meta-shaped, like ``widen`` and ``core.targeting.builder`` next door: this
is the second module in ``core.agent`` that knows what a targeting key
means, and the ambition stops there.
"""

import copy
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any, Final, Literal

from core.metrics import UNKNOWN, split_segment
from core.targeting import MAX_AGE, MIN_AGE

# The automation switch by its own module rather than through the package
# root, which does not re-export these three: they are the vocabulary of
# one decision and only :mod:`core.targeting.modes` has ever needed them.
from core.targeting.modes import AUTOMATION_FIELD, AUTOMATION_KEY, AUTOMATION_OFF

# Which layer of the audience was cut back. Codes, not sentences - the
# Django layer turns them into Uzbek, the same as ``WideningStep``.
NarrowingStep = Literal["age", "gender"]

# The provider's own words for the genders it will target, and the numbers
# it takes them as. ``unknown`` is in neither: it is a real slice of a
# report and not a thing anybody can aim at, so a dead ``unknown`` cell is
# evidence about nobody.
GENDER_CODES: Final[Mapping[str, int]] = {"male": 1, "female": 2}


@dataclass(frozen=True, slots=True)
class Narrowing:
    """A spec that stops paying for a dead slice, and which slice it was."""

    step: NarrowingStep
    targeting: dict[str, Any]
    # The numbers behind the sentence: which band was dropped, what it had
    # spent. Stored on the suggestion so the explanation survives without
    # the comparison it came from.
    detail: Mapping[str, Any] = field(default_factory=dict)


def keeps_its_audience(targeting: Mapping[str, Any]) -> bool:
    """Whether the advertiser's own audience is still the audience here.

    True only when the automation switch is present and off. An absent
    switch is **not** read as off: from v23.0 an omitted value means the
    provider chooses, and it chooses on - so absence is exactly the state
    this cannot tell apart from a deliberate opt-out, which is the finding
    ``core.targeting.modes`` is built around.
    """
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
    """The next single step inward, or ``None`` when none can be expressed.

    ``dead`` maps a segment name to what it spent - both halves are used:
    membership decides what may be cut, and the spend decides which end is
    worth cutting first. ``alive`` is every segment that produced anything
    at all, and it is a veto: no step may remove a cell that converts.

    Age before gender, because it is the smaller change. Dropping a band
    at the end of a range gives up a slice of the audience; dropping a
    gender gives up about half of it, and an ad set that then cannot spend
    its budget has traded one problem for a worse one.
    """
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
    """Stop paying for the youngest or the oldest band.

    Only an **end** of the range, and only when nothing in that band
    converts. A dead band in the middle cannot be cut without taking the
    live bands on the far side of it with it, so it is left alone and the
    money keeps going there - which is a smaller loss than an ad set whose
    audience was halved by a rule that could not see what it was removing.

    The new boundary is read off the band itself rather than from a table
    of the provider's buckets: the band above ``18-24`` starts at 25
    whatever the provider decides to call it next year.
    """
    bands = _bands(dead, alive)
    if len(bands) < 2:
        # One band is the whole audience. Cutting it leaves nobody, and a
        # comparison that saw only one band saw no comparison at all.
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
    """Stop showing the ad to a gender that never once responded.

    Refused unless the spec is currently aimed at everybody. A list that
    already names one gender has been narrowed - by the owner, by an
    earlier proposal - and narrowing it again is either a change that does
    nothing or one that empties the audience.
    """
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
    """Every age band the comparison saw, youngest first.

    A band counts as dead only if nothing in it converted: one live cell
    anywhere in it - either gender - keeps the whole band, because a range
    cannot be trimmed by gender and by age at once.
    """
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
    """``"25-34"`` as ``(25, 34)``, ``"65+"`` as ``(65, 65)``.

    ``None`` for anything that is not a band - ``unknown`` above all,
    which is the provider's word for a person it could not place and not
    a slice anybody can stop advertising to.
    """
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
