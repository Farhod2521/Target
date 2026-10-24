"""How far along one account is, read from what the provider has learned."""

from dataclasses import dataclass
from typing import Final, Literal

AccountMaturity = Literal["new", "growing", "proven"]

SIGNAL_WINDOW_DAYS: Final = 90

LEARNING_SUCCESS: Final = "SUCCESS"


def has_exited_learning(learning_status: str) -> bool:
    """Whether the provider itself says this ad set finished learning."""
    return learning_status.strip().upper() == LEARNING_SUCCESS


@dataclass(frozen=True, slots=True)
class SignalHistory:
    """What the provider has had to learn from, over a long window."""

    window_days: int
    reported_results: int = 0
    days_with_spend: int = 0
    has_proven_adset: bool = False


@dataclass(frozen=True, slots=True)
class MaturityThresholds:
    """The two numbers used when the provider's verdict is not available."""

    proven_weekly_results: int = 50
    min_results: int = 10


DEFAULT_THRESHOLDS: Final = MaturityThresholds()


def maturity(
    *,
    history: SignalHistory,
    thresholds: MaturityThresholds = DEFAULT_THRESHOLDS,
) -> AccountMaturity:
    """Where this account stands, safest reading first."""
    if history.window_days <= 0 or history.days_with_spend <= 0:
        return "new"
    if history.has_proven_adset:
        return "proven"

    weekly = history.reported_results * 7 / history.window_days
    if weekly >= thresholds.proven_weekly_results:
        return "proven"
    if history.reported_results < thresholds.min_results:
        return "new"
    return "growing"


__all__ = [
    "DEFAULT_THRESHOLDS",
    "LEARNING_SUCCESS",
    "SIGNAL_WINDOW_DAYS",
    "AccountMaturity",
    "MaturityThresholds",
    "SignalHistory",
    "has_exited_learning",
    "maturity",
]
