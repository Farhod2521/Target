from dataclasses import dataclass, field
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
from app.modules.ads.models import Campaign, CampaignLaunch
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


def own_off(row: Any) -> bool:
    """Its own switch is off. Meta keeps ``status`` PAUSED under a fault too
    (WITH_ISSUES), where ``delivery`` reads «rejected»; a finished object is
    never started again."""
    delivery = str(getattr(row, "delivery", ""))
    if delivery == Delivery.FINISHED:
        return False
    return delivery in SWITCHED_OFF or str(getattr(row, "status", "")).upper() == (
        "PAUSED"
    )


def sole_adset(campaign: Any) -> Any | None:
    """The campaign's one group: the screens show no group then, and the
    campaign's switch is the group's too."""
    groups = list(getattr(campaign, "adsets", None) or [])
    return groups[0] if len(groups) == 1 else None


@dataclass(frozen=True, slots=True)
class ResumePlan:
    """What one «Yoqish» switches on, top first, and what it leaves off to say."""

    targets: list[tuple[str, str]]
    notes: list[str] = field(default_factory=list)


ALL_GROUPS_OFF = (
    "Kampaniya yoqiladi, lekin undagi guruhlarning hammasi o'chiq. "
    "Kerakli guruhni o'zingiz yoqing."
)
ADS_OFF = (
    "«{name}» guruhidagi reklamalarning hammasi o'chiq. "
    "Kerakli reklamani o'zingiz yoqing."
)


def resume_plan(db: Session, *, owner: User, target: Any, level: str) -> ResumePlan:
    """One rule for every «Yoqish», wherever it is pressed.

    Above: whatever is switched off is switched on, or nothing would run.
    Below: a campaign with one group, and a group with one advert, are one
    switch - the screens do not show that group - so the one below goes on
    with it, whoever switched it off. Where there are several, each is the
    owner's to switch: only those a launch made and never started go on.
    """
    above = [
        (parent_level, parent)
        for parent_level, parent in ancestors_of(target=target, level=level)
        if own_off(parent)
    ]
    targets = [(at, str(row.external_id)) for at, row in above]
    if own_off(target) or not targets:
        targets.append((level, str(target.external_id)))
    notes: list[str] = []
    if level == ManagedLevel.AD:
        return ResumePlan(targets=targets, notes=notes)
    waiting = never_started(db, owner=owner)
    groups = list(target.adsets) if level == ManagedLevel.CAMPAIGN else [target]
    turned_on = _groups_on(db, owner=owner, groups=groups, waiting=waiting)
    if level == ManagedLevel.CAMPAIGN:
        targets += [(ManagedLevel.ADSET, str(row.external_id)) for row in turned_on]
        running = [row for row in groups if not own_off(row) or row in turned_on]
        if groups and not running:
            notes.append(ALL_GROUPS_OFF)
    else:
        running = [target]
    for group in running:
        ads, silent = _ads_on(group, waiting=waiting)
        targets += [(ManagedLevel.AD, str(row.external_id)) for row in ads]
        if silent:
            notes.append(ADS_OFF.format(name=group.name or group.external_id))
    return ResumePlan(targets=list(dict.fromkeys(targets)), notes=notes)


def _groups_on(
    db: Session, *, owner: User, groups: list[Any], waiting: frozenset[str]
) -> list[Any]:
    """The groups below a campaign that go on with it."""
    if len(groups) == 1:
        return [row for row in groups if own_off(row)]
    off = [row for row in groups if own_off(row) and row.external_id in waiting]
    # The agent's stop is the agent's to undo, among several groups.
    by_agent = stopped_by_agent(
        db, owner=owner, external_ids=[str(row.external_id) for row in off]
    )
    return [row for row in off if row.external_id not in by_agent]


def _ads_on(group: Any, *, waiting: frozenset[str]) -> tuple[list[Any], bool]:
    """The adverts of a group going on that go on with it, and whether none
    of its adverts would run."""
    ads = [row for row in group.ads if str(row.delivery) != Delivery.FINISHED]
    if len(ads) == 1:
        return [row for row in ads if own_off(row)], False
    chosen = [row for row in ads if own_off(row) and row.external_id in waiting]
    silent = bool(ads) and all(own_off(row) and row not in chosen for row in ads)
    return chosen, silent


def delivery_chain(*, target: Any, level: str) -> list[tuple[str, str]]:
    """What above this object must go on for it to run, and the object."""
    chain = [
        (parent_level, str(parent.external_id))
        for parent_level, parent in ancestors_of(target=target, level=level)
        if own_off(parent)
    ]
    chain.append((level, str(target.external_id)))
    return chain


def campaign_chain(
    db: Session, *, owner: User, campaign: Campaign
) -> list[tuple[str, str]]:
    return resume_plan(
        db, owner=owner, target=campaign, level=ManagedLevel.CAMPAIGN
    ).targets


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
    "ResumePlan",
    "ancestors_of",
    "blocked_above",
    "campaign_chain",
    "delivery_chain",
    "never_started",
    "own_off",
    "parent_switched_off",
    "resume_plan",
    "sole_adset",
    "stopped_by_agent",
]
