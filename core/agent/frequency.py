"""When the same people have seen an advert too often: three rising levels."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

Level = Literal["advice", "warning", "required"]

BARS: Final[tuple[tuple[Level, int], ...]] = (
    ("advice", 170),
    ("warning", 200),
    ("required", 250),
)
RANK: Final[dict[Level, int]] = {
    level: index for index, (level, _bar) in enumerate(BARS)
}
RESET_BELOW: Final = BARS[0][1]


@dataclass(frozen=True, slots=True)
class Reading:
    """One delivering group's seven days, as the levels read them."""

    adset_id: str
    impressions: int
    reach: int
    spend_minor: int

    @property
    def frequency(self) -> int | None:
        """Showings per person, in hundredths, or nothing with nobody reached."""
        if self.reach <= 0:
            return None
        return round(self.impressions * 100 / self.reach)


def level_of(frequency: int | None) -> Level | None:
    """The highest bar this frequency has reached, or none."""
    if frequency is None:
        return None
    found: Level | None = None
    for level, bar in BARS:
        if frequency >= bar:
            found = level
    return found


@dataclass(frozen=True, slots=True)
class Decision:
    """What tonight does for one group: start again, raise, or nothing."""

    reset: bool = False
    raise_to: Level | None = None


def decide(
    *,
    reading: Reading,
    said: Iterable[Level],
    min_spend_minor: int,
    new_creative: bool,
) -> Decision:
    """Tonight's decision for one group, given the levels already said."""
    frequency = reading.frequency
    if new_creative or (frequency is not None and frequency < RESET_BELOW):
        return Decision(reset=True)
    if reading.spend_minor < min_spend_minor:
        return Decision()
    level = level_of(frequency)
    if level is None:
        return Decision()
    highest = max((RANK[each] for each in said), default=-1)
    return Decision(raise_to=level if RANK[level] > highest else None)


__all__ = [
    "BARS",
    "RANK",
    "RESET_BELOW",
    "Decision",
    "Level",
    "Reading",
    "decide",
    "level_of",
]
