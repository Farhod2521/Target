"""Names for adverts other screens mention, whose advert a webhook is about,
and how many campaigns a trial may still switch on."""

import uuid
from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from metaads import PROVIDER as META
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads import refs as ref_field
from app.modules.ads.constants import (
    ACTION_STALE_MINUTES,
    NOT_RUNNING,
    LaunchStep,
    ManagedLevel,
)
from app.modules.ads.models import Ad, AdSet, Campaign, CampaignLaunch
from app.modules.ads.selectors.launched import (
    all_launched_campaign_ids,
    shared_adset_ids,
    shared_campaign_ids,
)
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.integrations.models import AdAccount


@dataclass(frozen=True, slots=True)
class AdLabel:
    external_id: str
    name: str = ""
    adset_external_id: str = ""
    adset_name: str = ""
    campaign_name: str = ""
    campaign_id: str = ""
    delivery: str = ""

    @property
    def title(self) -> str:
        return self.name or self.external_id


def ad_labels(db: Session, *, owner: User, external_ids: Iterable[str]) -> dict[str, AdLabel]:
    wanted = {value for value in external_ids if value}
    if not wanted:
        return {}
    rows = db.scalars(
        select(Ad)
        .options(joinedload(Ad.adset).joinedload(AdSet.campaign))
        .where(Ad.owner_id == owner.id, Ad.external_id.in_(wanted))
    )
    return {row.external_id: _label(row) for row in rows}


def ad_label(db: Session, *, owner: User, external_id: str) -> AdLabel | None:
    return ad_labels(db, owner=owner, external_ids=[external_id]).get(external_id)


def campaign_names(db: Session, *, owner: User, external_ids: Iterable[str]) -> dict[str, str]:
    wanted = {value for value in external_ids if value}
    if not wanted:
        return {}
    rows = db.execute(
        select(Campaign.external_id, Campaign.name).where(
            Campaign.owner_id == owner.id, Campaign.external_id.in_(wanted)
        )
    )
    return {external_id: name for external_id, name in rows if name}


def _label(row: Ad) -> AdLabel:
    adset = row.adset
    campaign = adset.campaign if adset is not None else None
    return AdLabel(
        external_id=row.external_id,
        name=row.name,
        adset_external_id=adset.external_id if adset is not None else "",
        adset_name=adset.name if adset is not None else "",
        campaign_name=campaign.name if campaign is not None else "",
        campaign_id=str(campaign.id) if campaign is not None else "",
        delivery=row.delivery,
    )


def advert_owner(
    db: Session,
    *,
    provider: str,
    owner_ids: Collection[uuid.UUID],
    adset: str = "",
    campaign: str = "",
    ad: str = "",
) -> uuid.UUID | None:
    owners = set(owner_ids)
    for model, external_id in ((AdSet, adset), (Campaign, campaign), (Ad, ad)):
        if not external_id:
            continue
        found = db.scalar(
            select(model.owner_id)
            .where(model.provider == provider, model.external_id == external_id)
            .limit(1)
        )
        if found in owners:
            return found
    wanted = {LaunchStep.ADSET: adset, LaunchStep.CAMPAIGN: campaign, LaunchStep.AD: ad}
    if not owners:
        return None
    for owner_id, created_refs in db.execute(
        select(CampaignLaunch.owner_id, CampaignLaunch.created_refs).where(
            CampaignLaunch.owner_id.in_(owners)
        )
    ):
        for step, external_id in wanted.items():
            if external_id and external_id in ref_field.ref_ids(created_refs or {}, step):
                return owner_id
    return None


# -- the tier's ceiling ---------------------------------------------------------------


def adsets_delivering(db: Session, *, owner: User, scope: PageScope) -> int:
    launched = all_launched_campaign_ids(db, owner=owner)
    return (
        db.scalar(
            select(func.count(AdSet.id))
            .join(Campaign, Campaign.id == AdSet.campaign_id)
            .join(AdAccount, AdAccount.id == Campaign.ad_account_id)
            .where(
                AdSet.owner_id == owner.id,
                AdSet.delivery.not_in([str(d) for d in NOT_RUNNING]),
                AdSet.external_id.not_in(list(scope.outside)),
                AdAccount.is_active.is_(True),
                Campaign.external_id.in_(list(launched)),
            )
        )
        or 0
    )


def counted_by_tier(db: Session, *, owner: User, account: AdAccount) -> bool:
    from app.modules.integrations.selectors import enabled_ad_accounts

    return any(row.id == account.id for row in enabled_ad_accounts(db, owner=owner))


def ceiling_scope(*, whole: PageScope, page_id: str = "") -> PageScope:
    wanted = page_id or whole.current
    return whole.only(wanted) if wanted in whole.pages else whole


def adsets_here(db: Session, *, owner: User) -> int:
    from app.modules.ads.selectors.pages import page_scope

    whole = page_scope(db, owner=owner)
    return adsets_delivering(db, owner=owner, scope=ceiling_scope(whole=whole))


def campaigns_switched_on(db: Session, *, owner: User, since: datetime) -> frozenset[str]:
    from app.modules.audit.constants import ActionStatus, ActionType
    from app.modules.audit.models import ActionLog

    cutoff = utcnow() - timedelta(minutes=ACTION_STALE_MINUTES)
    landed_or_on_its_way = or_(
        ActionLog.status.in_([str(ActionStatus.APPLIED), str(ActionStatus.REVERTED)]),
        and_(ActionLog.status == str(ActionStatus.PENDING), ActionLog.created_at >= cutoff),
    )
    pressed = list(
        db.execute(
            select(ActionLog.target_level, ActionLog.target_external_id)
            .where(
                ActionLog.owner_id == owner.id,
                landed_or_on_its_way,
                ActionLog.target_level.in_([str(ManagedLevel.CAMPAIGN), str(ManagedLevel.ADSET)]),
                ActionLog.target_provider == META,
                ActionLog.action == str(ActionType.RESUME),
                ActionLog.created_at >= since,
            )
            .distinct()
        ).all()
    )
    if not pressed:
        return frozenset()
    shared_campaigns = shared_campaign_ids(db, owner=owner)
    shared_adsets = (
        shared_adset_ids(db, owner=owner)
        if any(level == ManagedLevel.ADSET for level, _id in pressed)
        else frozenset()
    )
    return frozenset(
        external_id
        for level, external_id in pressed
        if (level == ManagedLevel.CAMPAIGN and external_id not in shared_campaigns)
        or (level == ManagedLevel.ADSET and external_id in shared_adsets)
    )


def trial_campaigns_left(db: Session, *, owner: User) -> int | None:
    from app.modules.billing.constants import TRIAL_MAX_CAMPAIGNS
    from app.modules.billing.selectors import trial_in_progress

    trial = trial_in_progress(db, owner=owner)
    if trial is None:
        return None
    spent = len(campaigns_switched_on(db, owner=owner, since=trial.started_at))
    return max(0, TRIAL_MAX_CAMPAIGNS - spent)
