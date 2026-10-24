"""A field this package changed on its own, and why."""

from dataclasses import dataclass
from typing import Literal

AdjustmentReason = Literal[
    "special_ad_category",
    "unconfirmed_interest",
    "unsupported_placement",
    "age_out_of_range",
    "radius_out_of_range",
    "location_missing",
    "conversion_source_missing",
    "automatic_targeting",
    "audience_on_both_sides",
    "audience_unavailable",
    "goal_takes_no_cap",
    "cap_below_daily",
]


@dataclass(frozen=True, slots=True)
class Adjustment:
    """A field this package changed on its own, and why."""

    field: str
    reason: AdjustmentReason
    detail: str = ""


__all__ = ["Adjustment", "AdjustmentReason"]
