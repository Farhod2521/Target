"""What the product itself built: the ids a launch wrote back, and goal campaigns."""

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from metaads.writing import is_dry_run_id
from sqlalchemy import func, select, type_coerce
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    AUTO_START_WAIT_SECONDS,
    MAX_AUTO_START_TRIES,
    LaunchStep,
    ManagedLevel,
)
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch, GoalCampaign
from app.modules.integrations.models import AdAccount

_LEVELS: tuple[tuple[str, str], ...] = (
    (LaunchStep.CAMPAIGN, ManagedLevel.CAMPAIGN),
    (LaunchStep.ADSET, ManagedLevel.ADSET),
    (LaunchStep.AD, ManagedLevel.AD),
)
MIRRORS: dict[str, Any] = {
    ManagedLevel.CAMPAIGN: Campaign,
    ManagedLevel.ADSET: AdSet,
    ManagedLevel.AD: Ad,
}


def owner_id_of(owner: User | uuid.UUID) -> uuid.UUID:
    return owner if isinstance(owner, uuid.UUID) else owner.id


def real_ids(ids: Iterable[str]) -> frozenset[str]:
    return frozenset(i for i in ids if i and not is_dry_run_id(i))


def launch_refs(db: Session, *where: Any) -> list[dict[str, Any]]:
    return [
        row or {}
        for row in db.scalars(select(CampaignLaunch.created_refs).where(*where))
    ]


def has_ref(step: str) -> Any:
    return type_coerce(CampaignLaunch.created_refs, JSONB).has_key(str(step))


# -- goal campaigns: one campaign shared by several launches -------------------------


def _holding(owner: User | uuid.UUID) -> tuple[Any, ...]:
    return (
        CampaignLaunch.owner_id == owner_id_of(owner),
        CampaignLaunch.goal_campaign_id.is_not(None),
        has_ref(LaunchStep.ADSET),
    )


def _shared_rows(owner: User | uuid.UUID) -> Any:
    held = (
        select(CampaignLaunch.goal_campaign_id)
        .where(*_holding(owner))
        .group_by(CampaignLaunch.goal_campaign_id)
        .having(func.count(CampaignLaunch.id) > 1)
    )
    return select(GoalCampaign).where(
        GoalCampaign.owner_id == owner_id_of(owner),
        GoalCampaign.id.in_(held),
        GoalCampaign.external_id != "",
    )


def goal_campaign_ids(
    db: Session, *, owner: User | uuid.UUID, ad_account: AdAccount | None = None
) -> frozenset[str]:
    query = select(GoalCampaign.external_id).where(
        GoalCampaign.owner_id == owner_id_of(owner), GoalCampaign.external_id != ""
    )
    if ad_account is not None:
        query = query.where(GoalCampaign.ad_account_id == ad_account.id)
    return real_ids(db.scalars(query))


def shared_campaign_ids(
    db: Session, *, owner: User | uuid.UUID, ad_account: AdAccount | None = None
) -> frozenset[str]:
    rows = _shared_rows(owner)
    if ad_account is not None:
        rows = rows.where(GoalCampaign.ad_account_id == ad_account.id)
    return real_ids(row.external_id for row in db.scalars(rows))


def shared_adset_ids(db: Session, *, owner: User) -> frozenset[str]:
    shared = _shared_rows(owner).with_only_columns(GoalCampaign.id)
    return real_ids(
        external_id
        for refs in launch_refs(
            db,
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.goal_campaign_id.in_(shared),
        )
        for external_id in ref_field.ref_ids(refs, LaunchStep.ADSET)
    )


def shares_campaign(db: Session, *, launch: CampaignLaunch) -> bool:
    if launch.goal_campaign_id is None:
        return False
    return (
        db.scalar(
            select(CampaignLaunch.id)
            .where(
                *_holding(launch.owner_id),
                CampaignLaunch.goal_campaign_id == launch.goal_campaign_id,
                CampaignLaunch.id != launch.id,
            )
            .limit(1)
        )
        is not None
    )


def ever_switched_on(db: Session, *, row: GoalCampaign) -> bool:
    from app.modules.audit.constants import ActionStatus, ActionType
    from app.modules.audit.models import ActionLog

    started = db.scalar(
        select(CampaignLaunch.id)
        .where(
            CampaignLaunch.owner_id == row.owner_id,
            CampaignLaunch.goal_campaign_id == row.id,
            CampaignLaunch.delivery_started_at.is_not(None),
        )
        .limit(1)
    )
    if started is not None:
        return True
    return (
        db.scalar(
            select(ActionLog.id)
            .where(
                ActionLog.owner_id == row.owner_id,
                ActionLog.target_external_id == row.external_id,
                ActionLog.action == str(ActionType.RESUME),
                ActionLog.status == str(ActionStatus.APPLIED),
                ActionLog.dry_run.is_(False),
            )
            .limit(1)
        )
        is not None
    )


# -- what a launch made ---------------------------------------------------------------


def launched_targets(*, launch: CampaignLaunch) -> list[tuple[str, str]]:
    return [
        (level, external_id)
        for step, level in _LEVELS
        for external_id in ref_field.ref_ids(launch.created_refs or {}, step)
        if not is_dry_run_id(external_id)
    ]


def launched_ad_id(*, launch: CampaignLaunch) -> str:
    ids = ref_field.ref_ids(launch.created_refs or {}, LaunchStep.AD)
    live = [external_id for external_id in ids if not is_dry_run_id(external_id)]
    return live[0] if live else ""


def still_starting(*, launch: CampaignLaunch, now: datetime) -> bool:
    if launch.delivery_started_at is not None or launch.delivery_note:
        return False
    if not launched_targets(launch=launch):
        return False
    since = launch.finished_at or launch.updated_at
    limit = AUTO_START_WAIT_SECONDS * MAX_AUTO_START_TRIES
    return (now - since).total_seconds() < limit


def launch_is_mirrored(db: Session, *, owner: User, launch: CampaignLaunch) -> bool:
    targets = launched_targets(launch=launch)
    if not targets:
        return False
    for level, model in MIRRORS.items():
        wanted = {ref for at, ref in targets if at == level}
        if not wanted:
            continue
        found = db.scalars(
            select(model.external_id).where(
                model.owner_id == owner.id, model.external_id.in_(wanted)
            )
        )
        if set(found) != wanted:
            return False
    return True


def _campaign_ids(refs: Iterable[dict[str, Any]]) -> frozenset[str]:
    return real_ids(
        external_id
        for created_refs in refs
        for external_id in ref_field.ref_ids(created_refs, LaunchStep.CAMPAIGN)
    )


def launched_campaign_ids(
    db: Session, *, owner: User, ad_account: AdAccount | None = None
) -> frozenset[str]:
    from app.modules.integrations.selectors import active_ad_account

    account = (
        ad_account if ad_account is not None else active_ad_account(db, owner=owner)
    )
    if account is None:
        return frozenset()
    refs = launch_refs(
        db,
        CampaignLaunch.owner_id == owner.id,
        CampaignLaunch.ad_account_id == account.id,
    )
    return _campaign_ids(refs) | goal_campaign_ids(db, owner=owner, ad_account=account)


def all_launched_campaign_ids(db: Session, *, owner: User) -> frozenset[str]:
    refs = launch_refs(db, CampaignLaunch.owner_id == owner.id)
    return _campaign_ids(refs) | goal_campaign_ids(db, owner=owner)


def launch_pages(db: Session, *, owner: User) -> dict[str, str]:
    from app.modules.integrations.models import PageAccount

    found: dict[str, str] = {}
    rows = db.execute(
        select(CampaignLaunch.created_refs, PageAccount.external_id)
        .join(PageAccount, PageAccount.id == CampaignLaunch.page_id)
        .where(CampaignLaunch.owner_id == owner.id)
        .order_by(CampaignLaunch.created_at)
    )
    for created_refs, page in rows:
        if not page:
            continue
        for external_id in ref_field.ref_ids(created_refs or {}, LaunchStep.CAMPAIGN):
            if not is_dry_run_id(external_id):
                found[external_id] = str(page)
    return found


def campaign_launch(
    db: Session, *, owner: User, campaign_external_id: str
) -> CampaignLaunch | None:
    rows = db.execute(
        select(CampaignLaunch.id, CampaignLaunch.created_refs)
        .where(CampaignLaunch.owner_id == owner.id)
        .order_by(CampaignLaunch.created_at.desc())
    )
    for pk, created_refs in rows:
        if campaign_external_id in ref_field.ref_ids(
            created_refs or {}, LaunchStep.CAMPAIGN
        ):
            return db.scalars(
                select(CampaignLaunch)
                .options(joinedload(CampaignLaunch.page))
                .where(CampaignLaunch.id == pk)
            ).first()
    return None


def adset_launch(
    db: Session, *, owner: User, adset_external_id: str
) -> CampaignLaunch | None:
    refs = type_coerce(CampaignLaunch.created_refs, JSONB)
    return db.scalars(
        select(CampaignLaunch)
        .options(joinedload(CampaignLaunch.page))
        .where(
            CampaignLaunch.owner_id == owner.id,
            refs[str(LaunchStep.ADSET)].contains([adset_external_id]),
        )
        .order_by(CampaignLaunch.created_at.desc())
        .limit(1)
    ).first()
