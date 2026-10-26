"""A subscription ran out: switch what we built off, back on after a payment,
and delete it when nobody paid within the grace days."""

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.ads.constants import LAPSE_DELETE_AFTER, LAPSE_MARK
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    SyncAlreadyRunning,
    SyncFailed,
)
from app.modules.ads.models import LapseHold
from app.modules.ads.selectors import (
    LapseTarget,
    hold_stops,
    lapse_targets,
    stops_in_flight,
)
from app.modules.ads.services.manage import BY_SYSTEM, request_pause, request_resume
from app.modules.ads.services.mirror import sync_ad_account
from app.modules.ads.services.removal import request_lapse_removal
from app.modules.audit.constants import ActionStatus, ActionType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.integrations.models import AdAccount

logger = logging.getLogger(__name__)
STOP_REASON = (
    "Obuna muddati tugagani uchun to'xtatildi. To'lov qilinsa, o'zi qayta yoqiladi."
)
RESUME_REASON = "To'lov qilingani uchun qayta yoqildi."
REMOVE_REASON = "Obuna 3 kun ichida yangilanmagani uchun o'chirildi."


def _has_live(db: Session, owner: User) -> bool:
    from app.modules.billing.selectors import has_live_subscription

    return has_live_subscription(db, owner=owner)


def _mark(db: Session, *, log: ActionLog, hold: LapseHold) -> None:
    log.request_payload = {**log.request_payload, LAPSE_MARK: str(hold.id)}
    if log.action == ActionType.PAUSE:
        log.reason = STOP_REASON
    elif log.action == ActionType.RESUME:
        log.reason = RESUME_REASON
    else:
        log.reason = REMOVE_REASON
    db.flush()


def open_lapse_hold(db: Session, *, owner: User, now: datetime) -> LapseHold | None:
    from app.modules.billing.selectors import subscription_ended_at

    ended = subscription_ended_at(db, owner=owner)
    if ended is None:
        return None
    known = db.scalar(
        select(LapseHold.id).where(
            LapseHold.owner_id == owner.id, LapseHold.ended_at == ended
        )
    )
    if known is not None:
        return None
    _sync(db, targets=lapse_targets(db, owner=owner))
    targets = lapse_targets(db, owner=owner)
    hold = LapseHold(
        owner_id=owner.id,
        ended_at=ended,
        started_at=now,
        delete_after=now + LAPSE_DELETE_AFTER,
    )
    try:
        with db.begin_nested():
            db.add(hold)
    except IntegrityError:
        return None
    emit(
        db,
        owner_id=owner.id,
        name=EventName.ADS_LAPSE_HELD,
        aggregate_type="lapse_hold",
        aggregate_id=hold.id,
        payload={
            "ended_at": ended.isoformat(),
            "delete_after": hold.delete_after.isoformat(),
            "objects": len(targets),
        },
        occurred_at=now,
    )
    db.commit()
    if not targets:
        hold.deleted_at = now
        db.commit()
        return None
    stop_running(db, hold=hold, targets=targets)
    return hold


def stop_running(
    db: Session, *, hold: LapseHold, targets: list[LapseTarget] | None = None
) -> int:
    from app.modules.ads.selectors.lapse import unwritable_account_ids

    owner = hold.owner
    stopped = 0
    unwritable = unwritable_account_ids(db, owner=owner)
    for target in targets if targets is not None else lapse_targets(db, owner=owner):
        if not target.running or target.ad_account_id in unwritable:
            continue
        try:
            log = request_pause(
                db,
                user=owner,
                level=target.level,
                external_id=target.external_id,
                origin=BY_SYSTEM,
            )
            _mark(db, log=log, hold=hold)
            db.commit()
        except DomainError as exc:
            db.rollback()
            logger.info(
                "lapse_stop_refused",
                extra={"object": target.external_id, "why": type(exc).__name__},
            )
            continue
        stopped += 1
    return stopped


def _sync(db: Session, *, targets: list[LapseTarget]) -> None:
    ids = {target.ad_account_id for target in targets}
    if not ids:
        return
    for account in db.scalars(select(AdAccount).where(AdAccount.id.in_(ids))).all():
        try:
            sync_ad_account(db, ad_account=account)
        except (SyncAlreadyRunning, ConnectionUnusable, SyncFailed) as exc:
            db.rollback()
            logger.info(
                "lapse_sync_skipped",
                extra={"account": account.external_id, "why": type(exc).__name__},
            )


def settle_lapse(db: Session, *, hold: LapseHold, now: datetime) -> str:
    if not hold.is_open:
        return "done"
    if _has_live(db, hold.owner):
        return (
            "later" if resume_after_lapse(db, hold=hold, now=now) is None else "resumed"
        )
    if remove_after_lapse(db, hold=hold, now=now) is not None:
        return "removed"
    stop_running(db, hold=hold)
    return "held"


def resume_after_lapse(db: Session, *, hold: LapseHold, now: datetime) -> int | None:
    owner = hold.owner
    if not hold.is_open or not _has_live(db, owner):
        return None
    stops = hold_stops(db, hold=hold)
    if stops_in_flight(stops):
        return None
    started = 0
    for stop in stops:
        if stop.status != ActionStatus.APPLIED:
            continue
        try:
            log = request_resume(
                db,
                user=owner,
                level=stop.target_level,
                external_id=stop.target_external_id,
                origin=BY_SYSTEM,
            )
            _mark(db, log=log, hold=hold)
            db.commit()
        except DomainError as exc:
            db.rollback()
            logger.info(
                "lapse_resume_refused",
                extra={"object": stop.target_external_id, "why": type(exc).__name__},
            )
            continue
        started += 1
    _close(db, hold=hold, field="resumed_at", name=EventName.ADS_LAPSE_RESUMED, now=now)
    return started


def remove_after_lapse(db: Session, *, hold: LapseHold, now: datetime) -> int | None:
    owner = hold.owner
    if not hold.is_open or now < hold.delete_after:
        return None
    if _has_live(db, owner):
        return None
    removed = 0
    for target in lapse_targets(db, owner=owner):
        try:
            log = request_lapse_removal(
                db,
                user=owner,
                level=target.level,
                external_id=target.external_id,
                origin=BY_SYSTEM,
            )
            _mark(db, log=log, hold=hold)
            db.commit()
        except DomainError as exc:
            db.rollback()
            logger.info(
                "lapse_removal_refused",
                extra={"object": target.external_id, "why": type(exc).__name__},
            )
            continue
        removed += 1
    _close(db, hold=hold, field="deleted_at", name=EventName.ADS_LAPSE_REMOVED, now=now)
    return removed


def _close(
    db: Session, *, hold: LapseHold, field: str, name: str, now: datetime
) -> None:
    setattr(hold, field, now)
    emit(
        db,
        owner_id=hold.owner_id,
        name=name,
        aggregate_type="lapse_hold",
        aggregate_id=hold.id,
        payload={"ended_at": hold.ended_at.isoformat()},
        occurred_at=now,
    )
    db.commit()
