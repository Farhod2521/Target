"""A graphic the planner asked for that the finished video does not show.

Every place that leaves one out says so here, with why, so staff can see
what became of the plan instead of counting graphics by eye.

- ``collision``: its band was taken, and neither moving it nor
  shortening a panel made room;
- ``same_twice``: it would follow one of its own kind;
- ``late_cta``: a button where the closing one is about to come;
- ``size_limit``: the render request grew too large and it went;
- ``end_card``: no room left for it before the closing card;
- ``no_brand``: it shows the brand, and the brand has none of that;
- ``max_uses``: the video already shows it as often as it may;
- ``word_cut``: none of its words are in the finished video;
- ``face``: no room for it off the speaker's face.
"""

from dataclasses import dataclass
from typing import Any, Literal

DropReason = Literal[
    "collision",
    "same_twice",
    "late_cta",
    "size_limit",
    "end_card",
    "no_brand",
    "max_uses",
    "word_cut",
    "face",
]


@dataclass(frozen=True, slots=True)
class Dropped:
    """One graphic left out: what, on which word, when, and why.

    ``at`` is the second of the finished video it asked to start at;
    ``anchor_word`` is None for one the code added itself.
    """

    component: str
    anchor_word: int | None
    at: float
    reason: DropReason

    def as_row(self) -> dict[str, Any]:
        """As kept in ``Montage.cut["dropped_events"]``."""
        return {
            "component": self.component,
            "anchor_word": self.anchor_word,
            "at": round(self.at, 3),
            "reason": self.reason,
        }
