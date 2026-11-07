"""TZ 2: copies of what runs - a campaign, a group, an advert - made by Meta.

Meta copies a tree in one call only while it holds three adverts or fewer, so
a bigger one is copied a level at a time inside the task: the campaign alone,
then each group with its adverts, or each group alone and then its adverts.
The task runs in the background and the screen follows it as any change.

A campaign's and a group's copy is paused - the owner checks it and turns it
on. An advert put into a group that already runs is made active at once;
into a new group, paused.
"""

import logging
from dataclasses import dataclass
from typing import Any, Final

from adskit.dto import ActionResult
from metaads import PROVIDER
from metaads.campaigns import REMOVED_STATUSES
from metaads.copies import (
    ACTIVE,
    INHERITED,
    PAUSED,
    SYNC_DEEP_COPY_ADS,
    StatusOption,
    copy_ad,
    copy_adset,
    copy_campaign,
)
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import (
    AdditionNotOffered,
    CampaignFinished,
    UnknownTarget,
)
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors.actions import managed_target
from app.modules.ads.services.additions import _not_finished, _settled
from app.modules.ads.services.manage import (
    ADDITION,
    Planned,
    _live,
    state_payload,
    target_for,
)
from app.modules.audit.constants import ActionType
from app.modules.audit.models import ActionLog
from core.agent.guardrails import FINISHED

logger = logging.getLogger(__name__)

# TZ 2.1: the copy's name, the original's with this after it.
COPY_SUFFIX: Final = " — nusxa"
# An advert's copy put into a new group of its own (TZ 2.3).
NEW_GROUP: Final = "new"
COPIES: Final = frozenset(
    {ActionType.COPY_CAMPAIGN, ActionType.COPY_ADSET, ActionType.COPY_AD}
)


def _copyable(target: Any) -> None:
    if target.provider != PROVIDER:
        raise AdditionNotOffered
    if str(target.delivery) == FINISHED:
        raise CampaignFinished


def _kept(rows: Any) -> list[Any]:
    """What Meta still holds: a deleted or archived object cannot be copied."""
    return [row for row in rows if str(row.status).upper() not in REMOVED_STATUSES]


# -- planning --------------------------------------------------------------------------


def plan_copy_campaign(db: Session, *, user: User, external_id: str) -> Planned:
    """TZ 2.1: the campaign with its groups and adverts, paused."""
    _live(db, user)
    campaign = target_for(
        db,
        user=user,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        aspect=ADDITION,
    )
    _copyable(campaign)
    return Planned(
        target=campaign,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.COPY_CAMPAIGN,
        requested={"suffix": COPY_SUFFIX},
        previous=state_payload(campaign),
        dispatch=_dispatch,
        revertible=False,
    )


def plan_copy_adset(
    db: Session, *, user: User, external_id: str, campaign: str = ""
) -> Planned:
    """TZ 2.2: the group with its adverts, paused, into this or another campaign."""
    _live(db, user)
    group = target_for(
        db,
        user=user,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        aspect=ADDITION,
    )
    _copyable(group)
    into = group.campaign
    if campaign and campaign != into.external_id:
        into = _own_campaign(db, user=user, external_id=campaign, beside=group)
    return Planned(
        target=group,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        action=ActionType.COPY_ADSET,
        requested={"campaign": into.external_id, "suffix": COPY_SUFFIX},
        previous=state_payload(group),
        dispatch=_dispatch,
        revertible=False,
    )


def plan_copy_ad(
    db: Session, *, user: User, external_id: str, adset: str = ""
) -> Planned:
    """TZ 2.3: the advert, as it is, into its group, another of the campaign's, or a new one."""
    _live(db, user)
    ad = target_for(
        db,
        user=user,
        level=ManagedLevel.AD,
        external_id=external_id,
        aspect=ADDITION,
    )
    _copyable(ad)
    group = ad.adset
    if adset == NEW_GROUP:
        into, status = NEW_GROUP, PAUSED
    else:
        found = group if not adset or adset == group.external_id else None
        if found is None:
            found = next(
                (row for row in group.campaign.adsets if row.external_id == adset),
                None,
            )
        if found is None or str(found.status).upper() in REMOVED_STATUSES:
            raise UnknownTarget
        into, status = found.external_id, ACTIVE
    return Planned(
        target=ad,
        level=ManagedLevel.AD,
        external_id=external_id,
        action=ActionType.COPY_AD,
        requested={"adset": into, "status": status, "suffix": COPY_SUFFIX},
        previous=state_payload(ad),
        dispatch=_dispatch,
        revertible=False,
    )


def plan_copy(
    db: Session, *, user: User, level: str, external_id: str, into: str = ""
) -> Planned:
    """One of the three, by the level asked for."""
    if level == ManagedLevel.CAMPAIGN:
        return plan_copy_campaign(db, user=user, external_id=external_id)
    if level == ManagedLevel.ADSET:
        return plan_copy_adset(db, user=user, external_id=external_id, campaign=into)
    if level == ManagedLevel.AD:
        return plan_copy_ad(db, user=user, external_id=external_id, adset=into)
    raise UnknownTarget


def _own_campaign(
    db: Session, *, user: User, external_id: str, beside: AdSet
) -> Campaign:
    """Another of the owner's campaigns, on the same ad account."""
    found = managed_target(
        db, owner=user, level=ManagedLevel.CAMPAIGN, external_id=external_id
    )
    if (
        not isinstance(found, Campaign)
        or found.provider != beside.provider
        or found.ad_account_id != beside.campaign.ad_account_id
        or str(found.delivery) == FINISHED
    ):
        raise UnknownTarget
    return found


def _dispatch(log_id: str) -> None:
    from app.modules.ads.tasks import apply_copy_task

    apply_copy_task.delay(log_id)


# -- carrying out ----------------------------------------------------------------------


def apply_copy(db: Session, *, log_id: str) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    from app.modules.ads.actions.executor import Write, carry_out

    return carry_out(
        db,
        log_id=log_id,
        kind=Write(
            actions=COPIES,
            ready=_ready,
            check=_not_finished,
            write=_write,
            finish=_finish,
        ),
    )


def _ready(_db: Session, log: ActionLog, target: Any) -> str:
    wanted = {
        ActionType.COPY_CAMPAIGN: Campaign,
        ActionType.COPY_ADSET: AdSet,
        ActionType.COPY_AD: Ad,
    }[log.action]
    return "" if isinstance(target, wanted) else "gone"


@dataclass(frozen=True, slots=True)
class _Meta:
    token: str
    dry_run: bool


def _write(_db: Session, job: Any) -> ActionResult:
    asked = job.log.request_payload
    meta = _Meta(token=job.token, dry_run=job.dry_run)
    suffix = str(asked.get("suffix") or "")
    if job.log.action == ActionType.COPY_CAMPAIGN:
        applied = _campaign(job.target, suffix=suffix, meta=meta)
    elif job.log.action == ActionType.COPY_ADSET:
        made = _group(
            job.target,
            campaign=str(asked["campaign"]),
            status=PAUSED,
            suffix=suffix,
            meta=meta,
        )
        applied = {"adset": made}
    else:
        applied = _advert(
            job.target,
            into=str(asked["adset"]),
            status=asked["status"],
            suffix=suffix,
            meta=meta,
        )
    return ActionResult(ok=True, ref=job.ref, applied=applied, dry_run=job.dry_run)


def _campaign(source: Campaign, *, suffix: str, meta: _Meta) -> dict[str, Any]:
    made = copy_campaign(
        campaign_id=source.external_id,
        suffix=suffix,
        token=meta.token,
        dry_run=meta.dry_run,
    )
    groups = _kept(source.adsets)
    for group in groups:
        _group(group, campaign=made, status=INHERITED, suffix="", meta=meta)
    return {"campaign": made, "adsets": len(groups)}


def _group(
    source: AdSet, *, campaign: str, status: StatusOption, suffix: str, meta: _Meta
) -> str:
    """One group into ``campaign``: with its adverts in one call while Meta allows."""
    ads = _kept(source.ads)
    whole = len(ads) <= SYNC_DEEP_COPY_ADS
    made = copy_adset(
        adset_id=source.external_id,
        campaign_id=campaign,
        deep_copy=whole,
        status=status,
        suffix=suffix,
        token=meta.token,
        dry_run=meta.dry_run,
    )
    if not whole:
        for ad in ads:
            copy_ad(
                ad_id=ad.external_id,
                adset_id=made,
                status=INHERITED,
                token=meta.token,
                dry_run=meta.dry_run,
            )
    return made


def _advert(
    source: Ad, *, into: str, status: StatusOption, suffix: str, meta: _Meta
) -> dict[str, Any]:
    group = into
    if into == NEW_GROUP:
        group = copy_adset(
            adset_id=source.adset.external_id,
            deep_copy=False,
            status=PAUSED,
            suffix=COPY_SUFFIX,
            token=meta.token,
            dry_run=meta.dry_run,
        )
    made = copy_ad(
        ad_id=source.external_id,
        adset_id=group,
        status=status,
        suffix=suffix,
        token=meta.token,
        dry_run=meta.dry_run,
    )
    return {"ad": made, "adset": group, "status": status}


def _finish(db: Session, job: Any, result: ActionResult) -> None:
    """The copies reach the mirror with the next read, queued here."""
    _settled(db, job=job, result=result)


__all__ = [
    "COPIES",
    "COPY_SUFFIX",
    "NEW_GROUP",
    "apply_copy",
    "plan_copy",
    "plan_copy_ad",
    "plan_copy_adset",
    "plan_copy_campaign",
]
