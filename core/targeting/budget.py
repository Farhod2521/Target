"""What a provider will actually accept per day, given what it optimises for."""

from typing import Final

RARE_EVENT_GOALS: Final[frozenset[str]] = frozenset(
    {
        "LEAD_GENERATION",
        "QUALITY_LEAD",
        "QUALITY_CALL",
        "CONVERSATIONS",
        "OFFSITE_CONVERSIONS",
        "VALUE",
        "APP_INSTALLS",
    }
)

RARE_EVENT_MULTIPLIER: Final = 2


SEEN_GOALS: Final[frozenset[str]] = frozenset(
    {"IMPRESSIONS", "REACH", "AD_RECALL_LIFT"}
)


FREQUENCY_GOALS: Final[frozenset[str]] = frozenset({"REACH"})


CAPPABLE_GOALS: Final[frozenset[str]] = frozenset(
    {"LEAD_GENERATION", "OFFSITE_CONVERSIONS"}
)


def accepts_cap(optimization_goal: str) -> bool:
    """Whether a price per result means anything for this goal."""
    return optimization_goal.strip().upper() in CAPPABLE_GOALS


CAP_BUDGET_MULTIPLE: Final = 3


def min_daily_for_cap(*, cap_minor: int) -> int:
    """The smallest daily budget this cap can deliver on."""
    return max(0, cap_minor) * CAP_BUDGET_MULTIPLE


def cap_fits(*, cap_minor: int, daily_budget_minor: int) -> bool:
    """Whether this pair can deliver, before anything is created."""
    if cap_minor <= 0:
        return True
    return daily_budget_minor >= min_daily_for_cap(cap_minor=cap_minor)


def daily_floor(*, account_minor: int, optimization_goal: str) -> int:
    """The smallest daily budget this goal can be launched with."""
    if account_minor <= 0:
        return 0
    if optimization_goal.strip().upper() in RARE_EVENT_GOALS:
        return account_minor * RARE_EVENT_MULTIPLIER
    return account_minor


PER_AD_FLOOR_MULTIPLE: Final = 2


def per_ad_floor(*, floor_minor: int) -> int:
    """The least one advert should have behind it once a budget is shared."""
    return max(0, floor_minor) * PER_AD_FLOOR_MULTIPLE


def ads_budget_carries(*, daily_budget_minor: int, floor_minor: int, ads: int) -> int:
    """How many adverts this daily budget gives a fair share to."""
    if floor_minor <= 0:
        return ads
    return max(1, daily_budget_minor // per_ad_floor(floor_minor=floor_minor))


CAP_BELOW_DAILY: Final = "cap_below_daily"


def spend_limits_fit(*, daily_minor: int, total_cap_minor: int = 0) -> str:
    """Why this total cannot hold, or ``""`` when it can."""
    if total_cap_minor and total_cap_minor < daily_minor:
        return CAP_BELOW_DAILY
    return ""


__all__ = [
    "CAPPABLE_GOALS",
    "CAP_BELOW_DAILY",
    "CAP_BUDGET_MULTIPLE",
    "FREQUENCY_GOALS",
    "PER_AD_FLOOR_MULTIPLE",
    "RARE_EVENT_GOALS",
    "RARE_EVENT_MULTIPLIER",
    "SEEN_GOALS",
    "accepts_cap",
    "ads_budget_carries",
    "cap_fits",
    "daily_floor",
    "min_daily_for_cap",
    "per_ad_floor",
    "spend_limits_fit",
]
