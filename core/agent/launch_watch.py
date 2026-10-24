"""The first days of a new ad group, watched for the two ways they go quiet."""

from dataclasses import dataclass
from typing import Final, Literal

FIRST_LOOK_HOURS: Final = 6
DAY_HOURS: Final = 24
LATE_UNSTARTED_HOURS: Final = 48
LATE_QUIET_HOURS: Final = 72

WATCH_HOURS: Final = 7 * 24

SPENT_SHARE_PCT: Final = 50

BUDGET_STEP_PCT: Final = 50

Stage = Literal[
    "unstarted",
    "in_review",
    "idle",
    "stuck",
    "quiet",
    "fruitless",
    "stalled",
    "dry",
    "dearer",
    "cheaper",
    "stopped",
]

Move = Literal["wait", "budget_up", "budget_down", "pause", "delete", "resume"]


@dataclass(frozen=True, slots=True)
class WatchedGroup:
    """One new group, in the facts these questions need."""

    adset_id: str
    hours: float
    spend_minor: int
    results: int | None
    daily_budget_minor: int | None
    in_review: bool = False
    blocked: bool = False
    owns_budget: bool = True
    learning: bool = False
    limited: bool = False


@dataclass(frozen=True, slots=True)
class Watch:
    """What is due: the step, the buttons, and which one is advised."""

    stage: Stage
    moves: tuple[Move, ...]
    advised: Move
    tag: str = ""
    step_pct: int = BUDGET_STEP_PCT


def watch(group: WatchedGroup) -> Watch | None:
    """What to say about this group now, or nothing."""
    if group.blocked or not FIRST_LOOK_HOURS <= group.hours < WATCH_HOURS:
        return None
    if group.spend_minor <= 0:
        return _unstarted(group)
    return _quiet(group)


def moved_budget(
    *, budget_minor: int, move: Move, step_pct: int = BUDGET_STEP_PCT
) -> int:
    """The daily figure a budget button sets. Never zero."""
    sign = {"budget_up": 1, "budget_down": -1}.get(move, 0)
    return max(1, round(budget_minor * (100 + sign * step_pct) / 100))


def _unstarted(group: WatchedGroup) -> Watch:
    if group.hours >= LATE_UNSTARTED_HOURS:
        return Watch(stage="stuck", moves=("delete", "wait"), advised="delete")
    if group.hours < DAY_HOURS:
        return Watch(stage="unstarted", moves=("wait",), advised="wait")
    if group.in_review:
        return Watch(stage="in_review", moves=("wait",), advised="wait")
    if not (group.owns_budget and group.daily_budget_minor):
        return Watch(stage="idle", moves=("wait",), advised="wait")
    return Watch(
        stage="idle",
        moves=("budget_up", "budget_down", "wait"),
        advised="budget_up",
    )


def _quiet(group: WatchedGroup) -> Watch | None:
    budget = group.daily_budget_minor
    if group.results is None or group.results > 0 or not budget:
        return None
    if group.hours < DAY_HOURS or not _spent(group, days=1):
        return None
    if group.hours >= LATE_QUIET_HOURS and _spent(group, days=3):
        return Watch(
            stage="fruitless", moves=("delete", "pause", "wait"), advised="delete"
        )
    return Watch(stage="quiet", moves=("wait",), advised="wait")


def _spent(group: WatchedGroup, *, days: int) -> bool:
    budget = group.daily_budget_minor or 0
    return group.spend_minor * 100 >= budget * SPENT_SHARE_PCT * days


__all__ = [
    "BUDGET_STEP_PCT",
    "DAY_HOURS",
    "FIRST_LOOK_HOURS",
    "LATE_QUIET_HOURS",
    "LATE_UNSTARTED_HOURS",
    "SPENT_SHARE_PCT",
    "WATCH_HOURS",
    "Move",
    "Stage",
    "Watch",
    "WatchedGroup",
    "moved_budget",
    "watch",
]
