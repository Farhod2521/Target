"""What one result is, for each thing an ad set can be told to optimise for."""

from collections.abc import Iterable, Mapping
from typing import Final, Literal

Outcome = Literal[
    "lead",
    "chat",
    "call",
    "view",
    "click",
    "recall",
    "profile",
    "site_lead",
    "none",
]

OUTCOMES: Final[dict[str, Outcome]] = {
    "LEAD_GENERATION": "lead",
    "QUALITY_LEAD": "lead",
    "CONVERSATIONS": "chat",
    "QUALITY_CALL": "call",
    "IMPRESSIONS": "view",
    "REACH": "view",
    "AD_RECALL_LIFT": "recall",
    "LANDING_PAGE_VIEWS": "click",
    "LINK_CLICKS": "click",
    "OFFSITE_CONVERSIONS": "none",
    "PROFILE_VISIT": "profile",
}


def outcome_of(optimization_goal: str) -> Outcome:
    """What one result is for an ad set optimising for this."""
    return OUTCOMES.get(optimization_goal.strip().upper(), "none")


SITE_GOAL: Final = "OFFSITE_CONVERSIONS"
SITE_LEAD_EVENT: Final = "LEAD"


def outcome_for(
    optimization_goal: str, promoted_object: Mapping[str, object] | None = None
) -> Outcome:
    """What one result is for an ad set: its goal, and what it promotes."""
    goal = optimization_goal.strip().upper()
    if goal == SITE_GOAL and _event_of(promoted_object) == SITE_LEAD_EVENT:
        return "site_lead"
    return outcome_of(goal)


def _event_of(promoted_object: Mapping[str, object] | None) -> str:
    if not isinstance(promoted_object, Mapping):
        return ""
    return str(promoted_object.get("custom_event_type") or "").strip().upper()


_RANK: Final[dict[Outcome, int]] = {"lead": 0, "site_lead": 1}


def campaign_goal(
    adsets: Iterable[tuple[str, str, Mapping[str, object] | None]],
) -> tuple[str, Mapping[str, object] | None]:
    """The one ad set that speaks for a campaign: its goal and promoted object."""
    ranked = sorted(
        adsets,
        key=lambda row: (_RANK.get(outcome_for(row[1] or "", row[2]), 2), row[0]),
    )
    if not ranked:
        return "", None
    _, goal, promoted = ranked[0]
    return goal or "", promoted


def is_counted(optimization_goal: str) -> bool:
    """Whether there is any figure at all to put against this goal."""
    return outcome_of(optimization_goal) != "none"


LEAD_GOALS: Final[frozenset[str]] = frozenset(
    goal for goal, kind in OUTCOMES.items() if kind == "lead"
)


def counts_leads(optimization_goal: str) -> bool:
    """Whether an ad set optimising for this can produce a lead row here."""
    return outcome_of(optimization_goal) == "lead"


__all__ = [
    "LEAD_GOALS",
    "OUTCOMES",
    "SITE_GOAL",
    "SITE_LEAD_EVENT",
    "Outcome",
    "campaign_goal",
    "counts_leads",
    "is_counted",
    "outcome_for",
    "outcome_of",
]
