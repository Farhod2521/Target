"""Whether a lead campaign may be bought on quality instead of on volume."""

from typing import Final, Literal

VOLUME_GOAL: Final = "LEAD_GENERATION"
QUALITY_GOAL: Final = "QUALITY_LEAD"

QUALITY_WINDOW_DAYS: Final = 28

MIN_QUALIFIED_FOR_QUALITY: Final = 50


LeadBuying = Literal["volume", "quality"]
BUYING_MODES: Final[tuple[LeadBuying, ...]] = ("volume", "quality")

DEFAULT_BUYING: Final[LeadBuying] = "volume"


def wants_quality(mode: str) -> bool:
    """Whether this answer asks for the quality goal."""
    return mode.strip().casefold() == "quality"


def is_lead_goal(goal: str) -> bool:
    """Whether this goal is one a quality signal could improve."""
    return goal.strip().upper() == VOLUME_GOAL


def is_available(*, reporting: bool, qualified_recently: int) -> bool:
    """Whether this account has earned the right to be offered the goal."""
    return False


def goal_for(
    *, preset_goal: str, chosen: bool, reporting: bool, qualified_recently: int
) -> str:
    """Which goal this ad set is actually created with."""
    if not chosen or not is_lead_goal(preset_goal):
        return preset_goal
    if not is_available(reporting=reporting, qualified_recently=qualified_recently):
        return preset_goal
    return QUALITY_GOAL


__all__ = [
    "BUYING_MODES",
    "DEFAULT_BUYING",
    "MIN_QUALIFIED_FOR_QUALITY",
    "QUALITY_GOAL",
    "QUALITY_WINDOW_DAYS",
    "VOLUME_GOAL",
    "LeadBuying",
    "goal_for",
    "is_available",
    "is_lead_goal",
    "wants_quality",
]
