"""When the same people have seen an advert too often: three rising levels.

**The advert set's own seven days, counted in people.** Frequency is
impressions over reach, and reach counts a person once however many days
they were shown it - so the figure here is the provider's range count, the
same one the diagnosis, the cards and the chat read, and never a mean of
daily frequencies.

Three levels, each said once, and only upwards: a suggestion at 1.70, a
warning at 2.00, and at 2.50 a change that is required and does not go
away until a creative is added or the frequency falls back. A group whose
frequency falls under 1.70, or that gets a new creative, starts again from
nothing. The bars are the brief's starting values.

Pure, like the rest of ``core``: what was said before arrives as plain
values and the answer is a decision, not a write.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, Literal

Level = Literal["advice", "warning", "required"]

# The bars, in hundredths of a showing per person, lowest first.
BARS: Final[tuple[tuple[Level, int], ...]] = (
    ("advice", 170),
    ("warning", 200),
    ("required", 250),
)
RANK: Final[dict[Level, int]] = {
    level: index for index, (level, _bar) in enumerate(BARS)
}
# Under the lowest bar a group starts again.
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


def seen_too_often(frequency: int | None) -> bool:
    """Whether the same people have seen it often enough to tire of it.

    The first bar, and the only frequency test anything here makes: the
    diagnosis's worn-out cause and the audience rule read this, so a group
    is never called worn out at a frequency the morning's levels call fine.
    """
    return frequency is not None and frequency >= BARS[0][1]


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
    """Tonight's decision for one group, given the levels already said.

    ``said`` is the levels said since the group last started again. A group
    that spent under ``min_spend_minor`` over the week is not read at all:
    its frequency rests on too few showings to mean anything.
    """
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
    "seen_too_often",
]
