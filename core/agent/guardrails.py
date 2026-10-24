"""What may be done to something that is already running."""

from dataclasses import dataclass
from typing import Final

from core.agent.contracts import GuardrailVerdict

REFUSED_ALREADY: Final = "already"
REFUSED_FINISHED: Final = "finished"
REFUSED_LEARNING: Final = "learning"
REFUSED_BELOW_FLOOR: Final = "below_floor"
REFUSED_LAST_AD: Final = "last_ad"

ACTIVE: Final = "active"
PAUSED: Final = "paused"

FINISHED: Final = "finished"

REJECTED: Final = "rejected"

ALLOWED: Final = GuardrailVerdict(allowed=True, reason="")


@dataclass(frozen=True, slots=True)
class ObjectState:
    """The object a change is aimed at, as it was last read."""

    delivery: str
    is_learning: bool = False
    daily_budget_minor: int | None = None
    has_spent: bool = True


def check_status_change(*, state: ObjectState, wanted: str) -> GuardrailVerdict:
    """Whether this object can be switched to ``wanted``."""
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    if state.delivery == wanted:
        return GuardrailVerdict(allowed=False, reason=REFUSED_ALREADY)
    return ALLOWED


def check_budget_change(
    *, state: ObjectState, wanted_minor: int, floor_minor: int
) -> GuardrailVerdict:
    """Whether this object's daily budget may become ``wanted_minor``."""
    if state.is_learning and state.has_spent:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    if state.daily_budget_minor == wanted_minor:
        return GuardrailVerdict(allowed=False, reason=REFUSED_ALREADY)
    if floor_minor > 0 and wanted_minor < floor_minor:
        return GuardrailVerdict(allowed=False, reason=REFUSED_BELOW_FLOOR)
    return ALLOWED


@dataclass(frozen=True, slots=True)
class AdContext:
    """What an advert's ad set looks like, for a decision about the advert."""

    parent_is_learning: bool = False
    other_active_ads: int = 0


def check_ad_pause(*, state: ObjectState, parent: AdContext) -> GuardrailVerdict:
    """Whether one advert inside a group may be switched off."""
    if parent.parent_is_learning:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    if parent.other_active_ads <= 0:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LAST_AD)
    return check_status_change(state=state, wanted=PAUSED)


def check_creative_swap(*, state: ObjectState, parent: AdContext) -> GuardrailVerdict:
    """Whether an advert's words and picture may be replaced."""
    if parent.parent_is_learning and state.delivery != REJECTED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    return ALLOWED


def check_targeting_change(*, state: ObjectState) -> GuardrailVerdict:
    """Whether this object's audience may be replaced."""
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    if state.is_learning:
        return GuardrailVerdict(allowed=False, reason=REFUSED_LEARNING)
    return ALLOWED


def check_limit_change(*, state: ObjectState) -> GuardrailVerdict:
    """Whether this object's end date or total ceiling may be set."""
    if state.delivery == FINISHED:
        return GuardrailVerdict(allowed=False, reason=REFUSED_FINISHED)
    return ALLOWED


def resets_learning(*, state: ObjectState) -> bool:
    """Whether going ahead costs the delivery bought so far."""
    return state.is_learning


__all__ = [
    "ACTIVE",
    "ALLOWED",
    "FINISHED",
    "PAUSED",
    "REFUSED_ALREADY",
    "REFUSED_BELOW_FLOOR",
    "REFUSED_FINISHED",
    "REFUSED_LAST_AD",
    "REFUSED_LEARNING",
    "REJECTED",
    "AdContext",
    "ObjectState",
    "check_ad_pause",
    "check_budget_change",
    "check_creative_swap",
    "check_limit_change",
    "check_status_change",
    "check_targeting_change",
    "resets_learning",
]
