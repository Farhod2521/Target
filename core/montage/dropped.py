"""A graphic the planner asked for that the finished video does not show."""

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
    """One graphic left out: what, on which word, when, and why."""

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
