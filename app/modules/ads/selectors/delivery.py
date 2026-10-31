from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    SWITCHED_OFF,
    Delivery,
    LaunchStatus,
    LaunchStep,
    ManagedLevel,
)
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.audit.constants import ActionStatus, ActionType, ActorType
from app.modules.audit.models import ActionLog

_PARENT_ATTR: dict[str, str] = {
    ManagedLevel.ADSET: "campaign",
    ManagedLevel.AD: "adset",
}
_PARENT_LEVEL: dict[str, str] = {
    ManagedLevel.ADSET: ManagedLevel.CAMPAIGN,
    ManagedLevel.AD: ManagedLevel.ADSET,
}


def ancestors_of(*, target: Any, level: str) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    at, obj = (level, target)
    while at in _PARENT_ATTR:
        parent = getattr(obj, _PARENT_ATTR[at], None)
        if parent is None:
            break
        found.append((_PARENT_LEVEL[at], parent))
        at, obj = (_PARENT_LEVEL[at], parent)
    found.reverse()
    return found


def blocked_above(*, target: Any, level: str) -> bool:
    if str(getattr(target, "delivery", "")) == Delivery.PAUSED_ABOVE:
        return True
    return any(
        (
            str(getattr(parent, "delivery", "")) != Delivery.ACTIVE
            for _level, parent in ancestors_of(target=target, level=level)
        )
    )


def parent_switched_off(*, target: Any, level: str) -> bool:
    return any(
        (
            str(getattr(parent, "delivery", "")) in SWITCHED_OFF
            for _level, parent in ancestors_of(target=target, level=level)
        )
    )


def delivery_chain(*, target: Any, level: str) -> list[tuple[str, str]]:
    chain = [
        (parent_level, str(parent.external_id))
        for parent_level, parent in ancestors_of(target=target, level=level)
        if str(getattr(parent, "delivery", "")) in SWITCHED_OFF
    ]
    chain.append((level, str(target.external_id)))
    return chain


def campaign_chain(
    db: Session, *, owner: User, campaign: Campaign
) -> list[tuple[str, str]]:
    adsets = list(
        db.execute(
            select(AdSet.external_id, AdSet.delivery).where(
                AdSet.owner_id == owner.id, AdSet.campaign_id == campaign.id
            )
        )
    )
    ads = list(
        db.execute(
            select(Ad.external_id, Ad.delivery)
            .join(AdSet, AdSet.id == Ad.adset_id)
            .where(Ad.owner_id == owner.id, AdSet.campaign_id == campaign.id)
        )
    )
    waiting = never_started(db, owner=owner)
    below = [
        (level, external_id)
        for level, rows in ((ManagedLevel.ADSET, adsets), (ManagedLevel.AD, ads))
        for external_id, delivery in rows
        if str(delivery) in SWITCHED_OFF and (external_id in waiting or _none_on(rows))
    ]
    by_agent = stopped_by_agent(
        db, owner=owner, external_ids=[external_id for _level, external_id in below]
    )
    return [
        (ManagedLevel.CAMPAIGN, str(campaign.external_id)),
        *(pair for pair in below if pair[1] not in by_agent),
    ]


def _none_on(rows: Sequence[Any]) -> bool:
    """A level with nothing on: the campaign would start and still show nothing."""
    return all(str(delivery) in SWITCHED_OFF for _external_id, delivery in rows)


def never_started(db: Session, *, owner: User) -> frozenset[str]:
    refs = db.scalars(
        select(CampaignLaunch.created_refs).where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.status == str(LaunchStatus.CREATED),
            CampaignLaunch.delivery_started_at.is_(None),
        )
    )
    return frozenset(
        external_id
        for created_refs in refs
        for step in (LaunchStep.ADSET, LaunchStep.AD)
        for external_id in ref_field.ref_ids(created_refs or {}, step)
    )


def stopped_by_agent(db: Session, *, owner: User, external_ids: list[str]) -> set[str]:
    if not external_ids:
        return set()
    rows = db.execute(
        select(ActionLog.target_external_id, ActionLog.action, ActionLog.actor_type)
        .where(
            ActionLog.owner_id == owner.id,
            ActionLog.target_external_id.in_(external_ids),
            ActionLog.status == str(ActionStatus.APPLIED),
            ActionLog.dry_run.is_(False),
        )
        .order_by(ActionLog.target_external_id, ActionLog.created_at.desc())
        .ext(distinct_on(ActionLog.target_external_id))
    )
    return {
        target
        for target, action, actor_type in rows
        if action == ActionType.PAUSE and actor_type == ActorType.AGENT
    }


__all__ = [
    "ancestors_of",
    "blocked_above",
    "campaign_chain",
    "delivery_chain",
    "never_started",
    "parent_switched_off",
    "stopped_by_agent",
]
