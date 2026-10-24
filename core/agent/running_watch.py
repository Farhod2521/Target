"""A group past its first week, watched for as long as it runs."""

from dataclasses import dataclass
from datetime import date
from typing import Final

from core.agent.launch_watch import Move, Watch, WatchedGroup

RECENT_DAYS: Final = 7
BEFORE_DAYS: Final = 21

DRY_STEPS: Final = (3, 7, 14)

MIN_RESULTS: Final = 5

DEARER_PCT: Final = 150
FAR_DEARER_PCT: Final = 300
CHEAPER_PCT: Final = 70

SPENT_UP_PCT: Final = 90

MAX_STALLED_DAYS: Final = 3

RUNNING_STEP_PCT: Final = 20


@dataclass(frozen=True, slots=True)
class Tally:
    """Money and results over some finished days."""

    spend_minor: int = 0
    results: int = 0


@dataclass(frozen=True, slots=True)
class Running:
    """A group past its first week, in finished days."""

    dry_days: int
    dry_spend_minor: int
    spell: int
    expected_cost_minor: int | None
    recent: Tally
    before: Tally
    idle_days: int
    idle_since: date | None
    spent_before: bool
    week: str
    before_days: int = BEFORE_DAYS


def running_watch(group: WatchedGroup, facts: Running) -> Watch | None:
    """What to say about a group past its first week, or nothing."""
    return (
        _stalled(group, facts)
        or _dry(group, facts)
        or _dearer(group, facts)
        or _cheaper(group, facts)
    )


def _stalled(group: WatchedGroup, facts: Running) -> Watch | None:
    if group.spend_minor > 0 or group.in_review:
        return None
    if not 1 <= facts.idle_days <= MAX_STALLED_DAYS or not facts.spent_before:
        return None
    moves: tuple[Move, ...] = ("wait",)
    if _may_move_budget(group):
        moves = ("budget_up", "wait")
    return Watch(
        stage="stalled",
        moves=moves,
        advised=moves[0],
        tag=str(facts.idle_since or ""),
        step_pct=RUNNING_STEP_PCT,
    )


def _dry(group: WatchedGroup, facts: Running) -> Watch | None:
    if group.results is None or group.results > 0:
        return None
    step = max((days for days in DRY_STEPS if days <= facts.dry_days), default=0)
    if not step or not _dry_enough(group, facts, step=step):
        return None
    expected = facts.expected_cost_minor
    far = expected is not None and facts.dry_spend_minor >= 3 * expected
    advised: Move = "pause" if (step > DRY_STEPS[0] or far) else "wait"
    if group.learning and step == DRY_STEPS[0]:
        advised = "wait"
    return Watch(
        stage="dry",
        moves=("pause", "wait"),
        advised=advised,
        tag=f"{step}:{facts.spell}",
        step_pct=RUNNING_STEP_PCT,
    )


def _dry_enough(group: WatchedGroup, facts: Running, *, step: int) -> bool:
    """Whether the money gone would have bought a result by now."""
    if facts.expected_cost_minor:
        return facts.dry_spend_minor >= facts.expected_cost_minor
    budget = group.daily_budget_minor or 0
    return budget > 0 and facts.dry_spend_minor * 2 >= budget * step


def _dearer(group: WatchedGroup, facts: Running) -> Watch | None:
    ratio = _ratio(facts)
    if ratio is None or not _priced(group) or facts.recent.results < 1:
        return None
    far = ratio >= FAR_DEARER_PCT
    if not far and (ratio < DEARER_PCT or facts.recent.results < MIN_RESULTS):
        return None
    moves: tuple[Move, ...] = ("pause", "wait")
    advised: Move = "wait"
    if _may_move_budget(group):
        moves = ("budget_down", "pause", "wait")
        advised = "budget_down"
    return Watch(
        stage="dearer",
        moves=moves,
        advised="pause" if far else advised,
        tag=facts.week,
        step_pct=RUNNING_STEP_PCT,
    )


def _cheaper(group: WatchedGroup, facts: Running) -> Watch | None:
    ratio = _ratio(facts)
    if ratio is None or not _priced(group) or facts.recent.results < MIN_RESULTS:
        return None
    if ratio > CHEAPER_PCT or not _may_move_budget(group):
        return None
    budget = group.daily_budget_minor or 0
    if facts.recent.spend_minor * 100 < budget * RECENT_DAYS * SPENT_UP_PCT:
        return None
    return Watch(
        stage="cheaper",
        moves=("budget_up", "wait"),
        advised="budget_up",
        tag=facts.week,
        step_pct=RUNNING_STEP_PCT,
    )


def _ratio(facts: Running) -> int | None:
    """The last week's price as a percentage of the weeks before, or nothing."""
    before, recent = facts.before, facts.recent
    if before.results < MIN_RESULTS or before.spend_minor <= 0 or not recent.results:
        return None
    return (recent.spend_minor * before.results * 100) // (
        before.spend_minor * recent.results
    )


def _priced(group: WatchedGroup) -> bool:
    """Whether the group's price is a price: not learning, and not stuck."""
    return not group.learning and not group.limited


def _may_move_budget(group: WatchedGroup) -> bool:
    """A button only on a budget that is the group's own, and a real price."""
    return group.owns_budget and bool(group.daily_budget_minor) and _priced(group)


__all__ = [
    "BEFORE_DAYS",
    "CHEAPER_PCT",
    "DEARER_PCT",
    "DRY_STEPS",
    "FAR_DEARER_PCT",
    "MAX_STALLED_DAYS",
    "MIN_RESULTS",
    "RECENT_DAYS",
    "RUNNING_STEP_PCT",
    "SPENT_UP_PCT",
    "Running",
    "Tally",
    "running_watch",
]
