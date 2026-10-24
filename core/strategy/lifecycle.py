"""Where one ad set is in its life, and what that stage permits.

The account has a maturity; each ad set has a stage. The two are different
clocks - a proven account launches a brand-new ad set and that ad set is
still in its test window, untouchable, however seasoned everything around
it is.

Four stages, in the order an ad set meets them:

  test        - younger than the grace period. Untouchable: three days of
                astronomical time, not of spend, because a fresh object's
                numbers are noise whatever they say
  learning    - the provider says it is still learning. Untouchable for
                edits, exactly as today's guardrails already refuse - a
                budget or targeting change here throws the learning away
                and buys nothing
  optimizing  - past both. Budgets, targeting and creatives may move
  scaling     - the provider's own SUCCESS verdict plus enough evidence
                days. The only stage where *raising* is a stable-footing
                decision rather than a bet, and the stage that earns the
                longer cooldown - slow scaling is the seventh strategy,
                not an accident of pacing

**The grace period and ``Policy.min_days`` answer different questions and
both stay.** Seventy-two hours is age - how long the object has existed;
``min_days`` is evidence - how many days it actually spent. An ad set
created six days ago that spent on two of them is past its grace period
and still short of evidence, and collapsing the two would lose one check
or the other.

No Django, no clock: age arrives as a number of hours somebody else
computed, the same bargain the rest of ``core`` makes.
"""

from typing import Final, Literal

from core.strategy.maturity import has_exited_learning

LifecycleStage = Literal["test", "learning", "optimizing", "scaling"]

# The stage each cooldown belongs to. The scaling figure is deliberately
# the longer one: a raise needs its results *read* before the next raise,
# and seventy-two hours is the shortest gap at which two full provider
# days sit between them whatever the timezone. The optimizing figure
# matches today's default. Both are floors the owner's own setting can
# raise but not lower - see :func:`cooldown_hours`.
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
    """Which stage this ad set is in, strictest reading first.

    Test wins over learning when both hold: a day-old ad set is always
    learning too, and "too young to judge" is the stricter and more
    truthful of the two sentences.

    ``age_hours`` is ``None`` when nobody knows - a hand-built ad set
    whose start the mirror never saw. Unknown age is not treated as young:
    holding an object in its test window forever would silence the agent
    about it for good, and a genuinely fresh ad set is protected by the
    learning check anyway, which the provider answers for every ad set
    whoever built it.

    Scaling needs both halves. The SUCCESS verdict alone is the provider
    saying the ad set *can* be scaled; ``min_days`` of actual spend is the
    evidence a decision would be made on. One without the other is
    optimizing.
    """
    if age_hours is not None and age_hours < test_hours:
        return "test"
    if is_learning:
        return "learning"
    if has_exited_learning(learning_status) and days_with_spend >= min_days:
        return "scaling"
    return "optimizing"


def may_adjust(stage: LifecycleStage) -> bool:
    """Whether budgets, targeting or creatives may change at this stage.

    False for the two untouchable stages. Stopping is not covered here and
    never will be: a pause is allowed in every stage of every object,
    because the thing being stopped is spending somebody's money - the
    rule ``core.agent.guardrails`` states and this module inherits.
    """
    return stage in ("optimizing", "scaling")


def may_scale(stage: LifecycleStage) -> bool:
    """Whether raising the budget rests on stable footing here.

    Only scaling. An optimizing ad set can still be *edited* upward -
    nothing here forbids it - but a strategy that proposes growth reads
    this, because growth on an unproven ad set is a bet dressed as a plan.
    """
    return stage == "scaling"


def cooldown_hours(*, stage: LifecycleStage, floor_hours: int) -> int:
    """How long this stage leaves an object alone after a change.

    The larger of the stage's own figure and the owner's setting, so the
    one knob the settings screen offers can lengthen the quiet period and
    never shorten what the stage requires. Test and learning have no
    figure of their own: nothing is changed there at all, so the owner's
    floor is returned for completeness rather than for use.
    """
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
