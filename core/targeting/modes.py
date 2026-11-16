"""What each of the three audience modes does to a spec."""

from collections.abc import Mapping
from dataclasses import dataclass
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


FieldUse = Literal["exact", "hint", "unused", "required"]
"""What a mode does with one audience field, for a screen to draw from.

``exact``: sent and kept to. ``hint``: sent, but the provider may reach
beyond it. ``unused``: never sent in this mode, so not shown. ``required``:
sent and kept to, and the launch is refused without one.
"""


@dataclass(frozen=True, slots=True)
class AgeRule:
    """The ages a screen may offer under one mode."""

    min: int = 18
    max: int = 65
    lowest_max: int = 65
    upper_sent: bool = True
    fixed: bool = False


@dataclass(frozen=True, slots=True)
class ModeRules:
    """One mode, field by field, as the spec builder treats it."""

    mode: TargetingMode
    interests: FieldUse
    habits: FieldUse
    genders: FieldUse
    include_lists: FieldUse
    age: AgeRule


def mode_rules(mode: TargetingMode, *, special: bool = False) -> ModeRules:
    """What ``build`` does with each field in ``mode``; one truth for both.

    A special ad category is built with the switch off and without genders
    or detailed targeting (``validators.SPECIAL_FORBIDDEN``), whatever mode
    was stored, so every mode reads the same there.
    """
    if special:
        return ModeRules(
            mode=mode,
            interests="unused",
            habits="unused",
            genders="unused",
            include_lists="exact",
            age=AgeRule(min=18, max=65, fixed=True),
        )
    detailed: FieldUse = "unused"
    if wants_interests(mode):
        detailed = "required" if requires_interests(mode) else "exact"
    automatic = mode == "automatic"
    return ModeRules(
        mode=mode,
        interests=detailed,
        habits="exact" if wants_interests(mode) else "unused",
        # Under the switch the provider reads both as suggestions only.
        genders="hint" if automatic else "exact",
        include_lists="hint" if automatic else "exact",
        age=AgeRule(
            lowest_max=AUTOMATIC_MAX_AGE_MIN if automatic else 65,
            upper_sent=not automatic,
        ),
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
    "AgeRule",
    "FieldUse",
    "ModeRules",
    "automation",
    "fit",
    "fit_automatic_ages",
    "is_automatic",
    "mode_rules",
    "requires_interests",
    "resolve_mode",
    "sent_ages",
    "wants_interests",
]
