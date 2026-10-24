"""Where one ad set is in its life, and what that stage permits."""

from typing import Final, Literal

from core.strategy.maturity import has_exited_learning

LifecycleStage = Literal["test", "learning", "optimizing", "scaling"]

OPTIMIZING_COOLDOWN_HOURS: Final = 48
SCALING_COOLDOWN_HOURS: Final = 72

_STAGE_COOLDOWN: Final[dict[LifecycleStage, int]] = {
    "optimizing": OPTIMIZING_COOLDOWN_HOURS,
    "scaling": SCALING_COOLDOWN_HOURS,
}


def stage(
    *,
    age_hours: int | None,
    is_learning: bool,
    learning_status: str,
    days_with_spend: int,
    test_hours: int,
    min_days: int,
) -> LifecycleStage:
    """Which stage this ad set is in, strictest reading first."""
    if age_hours is not None and age_hours < test_hours:
        return "test"
    if is_learning:
        return "learning"
    if has_exited_learning(learning_status) and days_with_spend >= min_days:
        return "scaling"
    return "optimizing"


def may_adjust(stage: LifecycleStage) -> bool:
    """Whether budgets, targeting or creatives may change at this stage."""
    return stage in ("optimizing", "scaling")


def may_scale(stage: LifecycleStage) -> bool:
    """Whether raising the budget rests on stable footing here."""
    return stage == "scaling"


def cooldown_hours(*, stage: LifecycleStage, floor_hours: int) -> int:
    """How long this stage leaves an object alone after a change."""
    return max(floor_hours, _STAGE_COOLDOWN.get(stage, floor_hours))


__all__ = [
    "OPTIMIZING_COOLDOWN_HOURS",
    "SCALING_COOLDOWN_HOURS",
    "LifecycleStage",
    "cooldown_hours",
    "may_adjust",
    "may_scale",
    "stage",
]
