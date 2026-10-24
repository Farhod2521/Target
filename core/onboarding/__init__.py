"""The order a cabinet is prepared in, and where it has got to.

Pure ordering logic: what the steps are, which one is next, and whether an
advert can be made yet. It reads no clock, no database and no setting - the
caller gathers the facts and this decides what they add up to, which is what
lets the whole sequence be checked without a provider or a fixture.
"""

from core.onboarding.steps import (
    FINISH_GATES,
    GATES,
    ORDER,
    PAIRED,
    SetupFacts,
    Step,
    StepId,
    StepState,
    blocking,
    can_finish,
    is_ready,
    paired_state,
    plan,
    progress,
)

__all__ = [
    "FINISH_GATES",
    "GATES",
    "ORDER",
    "PAIRED",
    "SetupFacts",
    "Step",
    "StepId",
    "StepState",
    "blocking",
    "can_finish",
    "is_ready",
    "paired_state",
    "plan",
    "progress",
]
