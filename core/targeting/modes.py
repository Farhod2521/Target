"""What each of the three audience modes does to a spec."""

from collections.abc import Mapping
from typing import Any, Final, Literal, get_args

from core.targeting.adjustments import Adjustment

TargetingMode = Literal["automatic", "interests", "broad"]

DEFAULT_TARGETING_MODE: Final[TargetingMode] = "automatic"


MODES: Final[tuple[TargetingMode, ...]] = get_args(TargetingMode)

AUTOMATION_KEY: Final = "targeting_automation"
AUTOMATION_FIELD: Final = "advantage_audience"
AUTOMATION_ON: Final = 1
AUTOMATION_OFF: Final = 0

AUTOMATIC_MAX_AGE_MIN: Final = 25

AUTOMATIC_AGE_MAX: Final = 65


def wants_interests(mode: TargetingMode) -> bool:
    """Whether a detailed-targeting block belongs in this spec at all."""
    return mode == "interests"


def requires_interests(mode: TargetingMode) -> bool:
    """Whether a launch in this mode may go out with nothing detailed in it."""
    return mode == "interests"


def automation(mode: TargetingMode) -> dict[str, int]:
    """The switch, spelled the provider's way. Never absent."""
    value = AUTOMATION_ON if mode == "automatic" else AUTOMATION_OFF
    return {AUTOMATION_FIELD: value}


def fit(spec: dict[str, Any], notes: list[Adjustment], *, mode: TargetingMode) -> None:
    """Write the switch and correct what the mode will not accept beside it."""
    spec[AUTOMATION_KEY] = automation(mode)
    if mode == "automatic":
        fit_automatic_ages(spec, notes)


def is_automatic(spec: Mapping[str, Any]) -> bool:
    """Whether a finished spec has the switch on, whoever wrote it."""
    switch = spec.get(AUTOMATION_KEY)
    return isinstance(switch, Mapping) and switch.get(AUTOMATION_FIELD) == AUTOMATION_ON


def fit_automatic_ages(spec: dict[str, Any], notes: list[Adjustment]) -> None:
    """No upper age, and a lower one no later than the mode allows."""
    if spec.pop("age_max", None) is not None:
        notes.append(
            Adjustment(
                field="age_max",
                reason="automatic_targeting",
                detail=str(AUTOMATIC_AGE_MAX),
            )
        )

    given = spec.get("age_min")
    if isinstance(given, int) and given > AUTOMATIC_MAX_AGE_MIN:
        spec["age_min"] = AUTOMATIC_MAX_AGE_MIN
        notes.append(
            Adjustment(
                field="age_min",
                reason="automatic_targeting",
                detail=f"{given}->{AUTOMATIC_MAX_AGE_MIN}",
            )
        )


def resolve_mode(value: object) -> TargetingMode:
    """A stored mode, or the default for a missing or unknown one."""
    return value if value in MODES else DEFAULT_TARGETING_MODE


def sent_ages(
    age_min: int | None, age_max: int | None, *, mode: TargetingMode
) -> tuple[int | None, int | None]:
    """The age range the provider is actually sent under this mode."""
    if mode != "automatic":
        return age_min, age_max
    low = None if age_min is None else min(age_min, AUTOMATIC_MAX_AGE_MIN)
    return low, None


__all__ = [
    "AUTOMATIC_AGE_MAX",
    "AUTOMATIC_MAX_AGE_MIN",
    "AUTOMATION_FIELD",
    "AUTOMATION_KEY",
    "AUTOMATION_OFF",
    "AUTOMATION_ON",
    "MODES",
    "automation",
    "fit",
    "fit_automatic_ages",
    "is_automatic",
    "requires_interests",
    "resolve_mode",
    "sent_ages",
    "wants_interests",
]
