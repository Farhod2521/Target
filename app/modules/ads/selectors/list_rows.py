from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.presets import goal_labels, goals_for
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import LaunchStep
from app.modules.ads.models import Campaign, CampaignLaunch, GoalCampaign

OTHER_GOAL = ""
OTHER_LABEL = "Boshqa reklamalar"
type ListRow = Campaign


@dataclass(slots=True)
class GoalGroup:
    goal: str
    label: Any
    rows: list[ListRow] = field(default_factory=list)


def by_goal(
    db: Session, *, owner: User, rows: list[ListRow], category: str, provider: str
) -> list[GoalGroup]:
    goal_of = _goals(db, owner=owner)
    presets = goals_for(category=category, provider=provider) if category else ()
    groups = {
        preset.goal: GoalGroup(goal=preset.goal, label=preset.label)
        for preset in presets
    }
    named = goal_labels(provider=provider)
    other = GoalGroup(goal=OTHER_GOAL, label=OTHER_LABEL)
    for row in rows:
        goal = goal_of.get(campaign_id_of(row), OTHER_GOAL)
        if goal == OTHER_GOAL:
            other.rows.append(row)
            continue
        groups.setdefault(
            goal, GoalGroup(goal=goal, label=named.get(goal, OTHER_LABEL))
        ).rows.append(row)
    return [group for group in [*groups.values(), other] if group.rows]


def campaign_id_of(row: ListRow) -> str:
    return str(row.external_id)


def _goals(db: Session, *, owner: User) -> dict[str, str]:
    found: dict[str, str] = {}
    launches = db.execute(
        select(CampaignLaunch.created_refs, CampaignLaunch.answers).where(
            CampaignLaunch.owner_id == owner.id
        )
    )
    for created_refs, answers in launches:
        goal = str((answers or {}).get("goal") or "")
        for external_id in ref_field.ref_ids(created_refs or {}, LaunchStep.CAMPAIGN):
            if goal:
                found.setdefault(external_id, goal)
    shared = db.execute(
        select(GoalCampaign.external_id, GoalCampaign.goal).where(
            GoalCampaign.owner_id == owner.id, GoalCampaign.external_id != ""
        )
    )
    for external_id, goal in shared:
        found[external_id] = goal
    return found


__all__ = ["GoalGroup", "ListRow", "by_goal", "campaign_id_of"]
