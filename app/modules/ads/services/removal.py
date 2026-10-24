"""Deleting a campaign, an ad set or an ad, and the empty campaign it can leave."""

import logging
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final

from adskit import ExternalRef, registry
from adskit.dto import ActionResult
from adskit.errors import NotFound, ProviderError, RateLimited, TemporaryFailure
from adskit.refs import ProviderName
from metaads.writing import is_dry_run_id
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import ConnectionUnusable, NoAdAccount
from app.modules.ads.models import Ad, Campaign, GoalCampaign
from app.modules.ads.selectors import managed_target
from app.modules.ads.services.access import target_account_and_token, token_for
from app.modules.ads.services.manage import (
    BY_HAND,
    BY_SYSTEM,
    REMOVAL,
    Origin,
    close_log,
    fail_log,
    open_change,
    open_log,
    state_payload,
    target_for,
)
from app.modules.audit.constants import ActionStatus, ActionType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.integrations.models import AdAccount

logger = logging.getLogger(__name__)
AGGREGATE = "ad_object"
DELETIONS: dict[str, str] = {
    ActionType.DELETE_CAMPAIGN: EventName.CAMPAIGN_DELETED,
    ActionType.DELETE_ADSET: EventName.ADSET_DELETED,
    ActionType.DELETE_AD: EventName.AD_DELETED,
}

# -- one launch at a time per goal campaign -------------------------------------------

LOCK_SECONDS: Final = 5 * 60
LOCK_PREFIX: Final = "goal-campaign:"
WAIT_SECONDS: Final = 90
POLL_SECONDS: Final = 1.0


@contextmanager
def goal_lock(*, account_id: str, page_id: str, goal: str) -> Iterator[None]:
    key = f"{LOCK_PREFIX}{account_id}:{page_id}:{goal}"
    waited = 0.0
    while not cache.add(key, "1", LOCK_SECONDS):
        if waited >= WAIT_SECONDS:
            raise TemporaryFailure("another launch is placing its ad group")
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
    try:
        yield
    finally:
        cache.delete(key)


# -- asking ---------------------------------------------------------------------------


def _live(db: Session, user: User) -> None:
    from app.modules.billing.services import require_live_subscription

    require_live_subscription(db, owner=user)


def _dispatch(log_id: str) -> None:
    from app.modules.ads.tasks import apply_delete_task

    apply_delete_task.delay(log_id)


def _delete(
    db: Session, *, user: User, level: str, external_id: str, action: str, origin: Origin
) -> ActionLog:
    target = target_for(db, user=user, level=level, external_id=external_id, aspect=REMOVAL)
    return open_change(
        db,
        user=user,
        target=target,
        level=level,
        external_id=external_id,
        action=action,
        requested={"status": "deleted"},
        origin=origin,
        dispatch=_dispatch,
    )


def request_delete(
    db: Session, *, user: User, external_id: str, origin: Origin = BY_HAND
) -> ActionLog:
    _live(db, user)
    return _delete(
        db,
        user=user,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.DELETE_CAMPAIGN,
        origin=origin,
    )


def request_adset_delete(
    db: Session, *, user: User, external_id: str, origin: Origin = BY_HAND
) -> ActionLog:
    _live(db, user)
    return _delete(
        db,
        user=user,
        level=ManagedLevel.ADSET,
        external_id=external_id,
        action=ActionType.DELETE_ADSET,
        origin=origin,
    )


def request_lapse_removal(
    db: Session, *, user: User, level: str, external_id: str, origin: Origin
) -> ActionLog:
    if level == ManagedLevel.ADSET:
        return _delete(
            db,
            user=user,
            level=ManagedLevel.ADSET,
            external_id=external_id,
            action=ActionType.DELETE_ADSET,
            origin=origin,
        )
    return _delete(
        db,
        user=user,
        level=ManagedLevel.CAMPAIGN,
        external_id=external_id,
        action=ActionType.DELETE_CAMPAIGN,
        origin=origin,
    )


def request_ad_delete(
    db: Session, *, user: User, external_id: str, origin: Origin = BY_HAND
) -> ActionLog:
    """An ad - or, when it is its group's last, the whole group."""
    _live(db, user)
    target = target_for(
        db, user=user, level=ManagedLevel.AD, external_id=external_id, aspect=REMOVAL
    )
    siblings = db.scalar(
        select(Ad.id)
        .where(Ad.owner_id == user.id, Ad.adset_id == target.adset_id, Ad.id != target.id)
        .limit(1)
    )
    if siblings is None:
        return _delete(
            db,
            user=user,
            level=ManagedLevel.ADSET,
            external_id=str(target.adset.external_id),
            action=ActionType.DELETE_ADSET,
            origin=origin,
        )
    return open_change(
        db,
        user=user,
        target=target,
        level=ManagedLevel.AD,
        external_id=external_id,
        action=ActionType.DELETE_AD,
        requested={"status": "deleted"},
        origin=origin,
        dispatch=_dispatch,
    )


# -- the worker -----------------------------------------------------------------------


def apply_delete(db: Session, *, log_id: str) -> str:
    log = db.get(ActionLog, uuid.UUID(str(log_id)))
    if log is None:
        return "gone"
    if log.status != ActionStatus.PENDING:
        return "done"
    if log.action not in DELETIONS:
        fail_log(db, log=log, code="unknown", message=f"no delete for {log.action}")
        return "unknown"
    target = managed_target(
        db, owner=log.owner, level=log.target_level, external_id=log.target_external_id
    )
    if target is None:
        fail_log(db, log=log, code="gone", message="object is no longer in the mirror")
        return "gone"
    try:
        _account, token = target_account_and_token(target=target, level=log.target_level)
    except (NoAdAccount, ConnectionUnusable) as exc:
        fail_log(db, log=log, code="connection", message=exc.message)
        return "unusable"
    ref = ExternalRef(
        provider=log.target_provider, level=log.target_level, id=log.target_external_id
    )
    try:
        result = registry.get(log.target_provider).campaigns.delete(
            ref=ref, token=token, dry_run=bool(settings.ads_dry_run)
        )
    except ProviderError as exc:
        fail_log(db, log=log, code=exc.code or "write", message=str(exc))
        return "failed"
    previous = state_payload(target) | {"name": target.name}
    if log.action == ActionType.DELETE_ADSET:
        previous["campaign_id"] = target.campaign.external_id
    close_log(db, log=log, result=result, previous=previous)
    if not result.dry_run:
        db.delete(target)
        if log.action == ActionType.DELETE_ADSET:
            from app.modules.ads.tasks import drop_empty_campaign_task

            sweep_id = str(log.id)
            on_commit(db, lambda: drop_empty_campaign_task.delay(sweep_id))
    _deleted_event(db, log=log, dry_run=result.dry_run)
    db.commit()
    logger.info("%s %s deleted (dry run: %s)", log.target_level, ref.id, result.dry_run)
    return "applied"


def _deleted_event(db: Session, *, log: ActionLog, dry_run: bool, reason: str = "") -> None:
    payload: dict[str, Any] = {
        "level": log.target_level,
        "provider": log.target_provider,
        "action": log.action,
        "name": log.previous_state.get("name", ""),
        "dry_run": dry_run,
    }
    if reason:
        payload["reason"] = reason
    emit(
        db,
        owner_id=log.owner_id,
        name=DELETIONS[log.action],
        aggregate_type=AGGREGATE,
        aggregate_id=log.target_external_id,
        payload=payload,
    )


# -- the campaign a deleted group left empty -------------------------------------------


def drop_empty_campaign(db: Session, *, log_id: str) -> str:
    log = db.get(ActionLog, uuid.UUID(str(log_id)))
    if log is None or log.action != ActionType.DELETE_ADSET:
        return "skip"
    if log.status != ActionStatus.APPLIED or log.dry_run:
        return "skip"
    campaign_id = str(log.previous_state.get("campaign_id") or "")
    if not campaign_id or is_dry_run_id(campaign_id):
        return "skip"
    owner = log.owner
    row = db.scalars(
        select(GoalCampaign).where(
            GoalCampaign.owner_id == owner.id,
            GoalCampaign.external_id == campaign_id,
            GoalCampaign.retired_at.is_(None),
        )
    ).first()
    if row is None:
        mirror = db.scalars(
            select(Campaign).where(
                Campaign.owner_id == owner.id, Campaign.external_id == campaign_id
            )
        ).first()
        if mirror is None:
            return "not mirrored"
        return _drop_if_empty(
            db,
            owner=owner,
            campaign_id=campaign_id,
            provider=mirror.provider,
            account=mirror.ad_account,
            row=None,
        )
    with goal_lock(account_id=str(row.ad_account_id), page_id=str(row.page_id), goal=row.goal):
        return _drop_if_empty(
            db,
            owner=owner,
            campaign_id=row.external_id,
            provider=row.provider,
            account=row.ad_account,
            row=row,
        )


def _drop_if_empty(
    db: Session,
    *,
    owner: User,
    campaign_id: str,
    provider: str,
    account: AdAccount,
    row: GoalCampaign | None,
) -> str:
    ref = ExternalRef(provider=ProviderName(provider), level="campaign", id=campaign_id)
    try:
        token = token_for(ad_account=account)
        port = registry.get(provider).campaigns
        held = port.count_adsets(campaign=ref, token=token)
    except NotFound:
        _forget(db, owner=owner, campaign_id=campaign_id, row=row)
        db.commit()
        return "gone"
    except (TemporaryFailure, RateLimited):
        raise
    except (ConnectionUnusable, ProviderError) as exc:
        logger.warning("campaign %s not counted: %s", campaign_id, exc)
        return "unusable"
    if held:
        return "kept"
    mirror = managed_target(db, owner=owner, level=ManagedLevel.CAMPAIGN, external_id=ref.id)
    dry_run = bool(settings.ads_dry_run)
    log = open_log(
        db,
        owner=owner,
        action=ActionType.DELETE_CAMPAIGN,
        provider=ref.provider,
        level=ManagedLevel.CAMPAIGN,
        external_id=ref.id,
        requested={"status": "deleted", "reason": "empty"},
        previous=(
            state_payload(mirror) | {"name": mirror.name}
            if mirror is not None
            else {"from_mirror": False, "name": ""}
        ),
        dry_run=dry_run,
        origin=BY_SYSTEM,
    )
    db.commit()
    try:
        result: ActionResult = port.delete(ref=ref, token=token, dry_run=dry_run)
    except ProviderError as exc:
        fail_log(db, log=log, code=exc.code or "write", message=str(exc))
        return "failed"
    close_log(db, log=log, result=result, previous=log.previous_state)
    if not result.dry_run:
        _forget(db, owner=owner, campaign_id=log.target_external_id, row=row)
    _deleted_event(db, log=log, dry_run=result.dry_run, reason="empty")
    db.commit()
    logger.info("empty campaign %s deleted (dry run: %s)", ref.id, result.dry_run)
    return "deleted"


def _forget(db: Session, *, owner: User, campaign_id: str, row: GoalCampaign | None) -> None:
    if row is not None:
        row.retired_at = utcnow()
    db.execute(
        delete(Campaign)
        .where(Campaign.owner_id == owner.id, Campaign.external_id == campaign_id)
        .execution_options(synchronize_session=False)
    )
