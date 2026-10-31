"""Who holds a launch's daily budget: the campaign, or each of its ad groups."""

from dataclasses import dataclass

from app.modules.ads.constants import (
    BUDGET_AT_ADSET,
    BUDGET_AT_CAMPAIGN,
    BUDGET_LEVEL,
    BUDGET_SHARING,
)
from app.modules.ads.models import CampaignLaunch


def budget_level(*, launch: CampaignLaunch) -> str:
    """The owner's choice; untouched, the campaign, except a draft already divided."""
    chosen = str((launch.answers or {}).get(BUDGET_LEVEL) or "")
    if chosen:
        return chosen
    return BUDGET_AT_ADSET if launch.ad_groups else BUDGET_AT_CAMPAIGN


def held_by_campaign(*, launch: CampaignLaunch) -> bool:
    return budget_level(launch=launch) == BUDGET_AT_CAMPAIGN


def shares_budget(*, launch: CampaignLaunch) -> bool:
    """Ad groups lending each other a fifth, which only groups with budgets can do."""
    return not held_by_campaign(launch=launch) and bool(
        (launch.answers or {}).get(BUDGET_SHARING)
    )


def campaign_budget_minor(*, launch: CampaignLaunch) -> int | None:
    """What the campaign itself must hold, or nothing when its groups do."""
    if not held_by_campaign(launch=launch):
        return None
    return int(launch.daily_budget_minor or 0)


@dataclass(frozen=True, slots=True)
class BudgetChoice:
    level: str
    sharing: bool
    locked: bool


def budget_choice(*, launch: CampaignLaunch) -> BudgetChoice:
    from app.modules.ads.selectors.campaign_type import campaign_type_locked

    return BudgetChoice(
        level=budget_level(launch=launch),
        sharing=shares_budget(launch=launch),
        locked=campaign_type_locked(launch=launch),
    )
