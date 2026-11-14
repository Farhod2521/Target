"""A subscription ran out: switch what we built off, back on after a payment,
and delete it when nobody paid within the grace days."""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    BLOCK_DELETE_AFTER,
    LAPSE_DELETE_AFTER,
    LAPSE_MARK,
    ManagedLevel,
)
from app.modules.ads.exceptions import (
    ChangeInFlight,
    ConnectionUnusable,
    SyncAlreadyRunning,
    SyncFailed,
)
from app.modules.ads.models import LapseHold
from app.modules.ads.selectors import (
    LapseTarget,
    hold_stops,
    hold_writes,
    lapse_targets,
    open_hold,
    stops_in_flight,
)
from app.modules.ads.services.manage import BY_SYSTEM
from app.modules.ads.services.mirror import sync_ad_account
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
PAGE_STOP_REASON = "Sahifa obunadan uzilgani uchun to'xtatildi."
PAGE_REMOVE_REASON = "Sahifa uzilganiga 3 kun bo'lgani uchun o'chirildi."
BLOCK_STOP_REASON = "Akkaunt bloklangani uchun to'xtatildi."
BLOCK_REMOVE_REASON = "Akkaunt bloklanganiga 24 soat bo'lgani uchun o'chirildi."
# A write the worker lost (Meta busy, no worker in time) says nothing about
# the advert: the same one may pass on the next sweep.
PASSING_CODES: Final = frozenset({"temporary", "stalled"})
# How often one object is asked again, and for how long past the first ask a
# hold waits for its writes before it closes with what it has.
MAX_ASKS: Final = 4
SETTLE_FOR: Final = timedelta(hours=24)
DELETES: Final = (ActionType.DELETE_CAMPAIGN, ActionType.DELETE_ADSET)


def _has_live(db: Session, owner: User) -> bool:
    from app.modules.billing.selectors import has_live_subscription

    return has_live_subscription(db, owner=owner)


def _mark(db: Session, *, log: ActionLog, hold: LapseHold) -> None:
    log.request_payload = {**log.request_payload, LAPSE_MARK: str(hold.id)}
    page = hold.page_id is not None
    blocked = not page and not hold.owner.is_active
    if log.action == ActionType.PAUSE:
        log.reason = (
            PAGE_STOP_REASON if page else BLOCK_STOP_REASON if blocked else STOP_REASON
        )
    elif log.action == ActionType.RESUME:
        log.reason = RESUME_REASON
    else:
        log.reason = (
            PAGE_REMOVE_REASON
            if page
            else BLOCK_REMOVE_REASON
            if blocked
            else REMOVE_REASON
        )
    db.flush()


def open_lapse_hold(db: Session, *, owner: User, now: datetime) -> LapseHold | None:
    from app.modules.billing.selectors import subscription_ended_at

    ended = subscription_ended_at(db, owner=owner)
    if ended is None:
        return None
    known = db.scalar(
        select(LapseHold.id).where(
            LapseHold.owner_id == owner.id,
            LapseHold.ended_at == ended,
            LapseHold.page_id.is_(None),
        )
    )
    if known is not None or open_hold(db, owner=owner) is not None:
        # One hold at a time: a blocked owner's, or an older deadline's still
        # being settled, already holds the same adverts.
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


def hold_blocked_owner(db: Session, *, owner: User, now: datetime) -> LapseHold | None:
    """A blocked account's adverts stop now and are deleted a day later.

    An unpaid owner's hold already open is the same hold: its deletion only
    comes sooner. Unblocking in time gives the adverts back (``settle_lapse``).
    """
    if owner.is_active:
        return None
    soon = now + BLOCK_DELETE_AFTER
    hold = open_hold(db, owner=owner)
    if hold is not None:
        hold.delete_after = min(hold.delete_after, soon)
        db.commit()
        stop_running(db, hold=hold)
        return hold
    _sync(db, targets=lapse_targets(db, owner=owner))
    targets = lapse_targets(db, owner=owner)
    if not targets:
        return None
    hold = LapseHold(owner_id=owner.id, ended_at=now, started_at=now, delete_after=soon)
    db.add(hold)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.ADS_LAPSE_HELD,
        aggregate_type="lapse_hold",
        aggregate_id=hold.id,
        payload={
            "blocked": True,
            "delete_after": soon.isoformat(),
            "objects": len(targets),
        },
        occurred_at=now,
    )
    db.commit()
    stop_running(db, hold=hold, targets=targets)
    return hold


def release_unblocked_owner(db: Session, *, owner: User, now: datetime) -> str:
    """The account is open again: a paid one gets its adverts back at once, an
    unpaid one the usual grace days from now."""
    hold = open_hold(db, owner=owner)
    if hold is None or not owner.is_active:
        return "nothing"
    if not _has_live(db, owner):
        hold.delete_after = max(hold.delete_after, now + LAPSE_DELETE_AFTER)
        db.commit()
    return settle_lapse(db, hold=hold, now=now)


def hold_released_page(
    db: Session, *, owner: User, page_id: uuid.UUID, now: datetime
) -> LapseHold:
    """Hold the adverts of a page a paid renewal let go: stopped by
    ``stop_page_hold_task`` once this commits, deleted after the grace days
    unless the page comes back first."""
    hold = LapseHold(
        owner_id=owner.id,
        page_id=page_id,
        ended_at=now,
        started_at=now,
        delete_after=now + LAPSE_DELETE_AFTER,
    )
    db.add(hold)
    db.flush()
    emit(
        db,
        owner_id=owner.id,
        name=EventName.ADS_LAPSE_HELD,
        aggregate_type="lapse_hold",
        aggregate_id=hold.id,
        payload={
            "page_id": str(page_id),
            "delete_after": hold.delete_after.isoformat(),
        },
        occurred_at=now,
    )
    return hold


def stop_page_hold(db: Session, *, hold: LapseHold) -> int:
    """Stop what runs on a let-go page, after reading its accounts afresh."""
    if not hold.is_open or hold.page_id is None:
        return 0
    _sync(db, targets=_targets(db, hold=hold))
    return stop_running(db, hold=hold)


def _targets(db: Session, *, hold: LapseHold) -> list[LapseTarget]:
    return lapse_targets(db, owner=hold.owner, page_id=hold.page_id)


def _page_back(db: Session, *, hold: LapseHold) -> bool:
    from app.modules.integrations.models import PageAccount

    page = db.get(PageAccount, hold.page_id) if hold.page_id else None
    return page is not None and page.is_active


def stop_running(
    db: Session, *, hold: LapseHold, targets: list[LapseTarget] | None = None
) -> int:
    from app.modules.ads import actions
    from app.modules.ads.selectors.lapse import unwritable_account_ids

    owner = hold.owner
    stopped = 0
    unwritable = unwritable_account_ids(db, owner=owner)
    for target in targets if targets is not None else _targets(db, hold=hold):
        if not target.running or target.ad_account_id in unwritable:
            continue
        try:
            log = actions.request(
                db,
                user=owner,
                ask=actions.Pause(level=target.level, external_id=target.external_id),
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
    if hold.page_id is not None:
        return _settle_page(db, hold=hold, now=now)
    if hold.owner.is_active and _has_live(db, hold.owner):
        return (
            "later" if resume_after_lapse(db, hold=hold, now=now) is None else "resumed"
        )
    if remove_after_lapse(db, hold=hold, now=now) is not None:
        return "removed"
    stop_running(db, hold=hold)
    return "held"


def _settle_page(db: Session, *, hold: LapseHold, now: datetime) -> str:
    """A let-go page connected again keeps its adverts, stopped: the owner
    starts them. Otherwise they stay stopped until the grace days end."""
    if _page_back(db, hold=hold):
        _close(
            db, hold=hold, field="resumed_at", name=EventName.ADS_LAPSE_RESUMED, now=now
        )
        return "kept"
    if remove_after_lapse(db, hold=hold, now=now) is not None:
        return "removed"
    stop_running(db, hold=hold)
    return "held"


def _ask_each(
    db: Session,
    *,
    hold: LapseHold,
    objects: list[tuple[str, str]],
    actions: tuple[str, ...],
    ask: Callable[[str, str], Any],
    refused: str,
) -> tuple[int, bool, datetime | None]:
    """Ask the write for every object still without one that settled.

    Returns how many were asked now, whether anything is still open (a write
    in flight, or one lost for a passing reason and asked again), and when the
    hold first asked. An object whose write was applied, was refused for a
    reason of its own, or was asked ``MAX_ASKS`` times is left as it is.
    """
    from app.modules.ads import actions as writes

    owner = hold.owner
    asked_before = hold_writes(db, hold=hold, actions=actions)
    first = min(
        (log.created_at for logs in asked_before.values() for log in logs),
        default=None,
    )
    asked, waiting = 0, False
    for level, external_id in objects:
        logs = asked_before.get(external_id, [])
        last = logs[0] if logs else None
        if last is not None and last.status == ActionStatus.PENDING:
            waiting = True
            continue
        if last is not None and last.status == ActionStatus.APPLIED:
            continue
        if last is not None and (
            last.error_code not in PASSING_CODES or len(logs) >= MAX_ASKS
        ):
            continue
        try:
            log = writes.request(
                db, user=owner, ask=ask(level, external_id), origin=BY_SYSTEM
            )
            _mark(db, log=log, hold=hold)
            db.commit()
        except ChangeInFlight:
            db.rollback()
            waiting = True
            continue
        except DomainError as exc:
            db.rollback()
            logger.info(
                refused, extra={"object": external_id, "why": type(exc).__name__}
            )
            continue
        asked += 1
        waiting = True
    return asked, waiting, first


def resume_after_lapse(db: Session, *, hold: LapseHold, now: datetime) -> int | None:
    """Switch back on what this hold switched off. ``None`` while it is not
    done: a stop or a resume still in flight, or one Meta dropped and that is
    asked again. The hold closes only when every resume has settled, so a
    paid owner's adverts are not left off behind a closed hold."""
    from app.modules.ads import actions

    owner = hold.owner
    if not hold.is_open or not owner.is_active or not _has_live(db, owner):
        return None
    stops = hold_stops(db, hold=hold)
    if stops_in_flight(stops):
        return None
    objects = list(
        dict.fromkeys(
            (stop.target_level, stop.target_external_id)
            for stop in stops
            if stop.status == ActionStatus.APPLIED
        )
    )
    started, waiting, first = _ask_each(
        db,
        hold=hold,
        objects=objects,
        actions=(ActionType.RESUME,),
        ask=lambda level, external_id: actions.Resume(
            level=level, external_id=external_id
        ),
        refused="lapse_resume_refused",
    )
    if waiting and now < (first or now) + SETTLE_FOR:
        return None
    _close(db, hold=hold, field="resumed_at", name=EventName.ADS_LAPSE_RESUMED, now=now)
    return started


def remove_after_lapse(db: Session, *, hold: LapseHold, now: datetime) -> int | None:
    """Delete what the hold kept off, once its days are over. ``None`` before
    then, and while a delete is still in flight or asked again: a hold closed
    over a delete Meta dropped would leave the advert neither deleted nor
    ever switched back on."""
    from app.modules.ads import actions

    owner = hold.owner
    if not hold.is_open or now < hold.delete_after:
        return None
    if hold.page_id is None and owner.is_active and _has_live(db, owner):
        return None
    if hold.page_id is not None and _page_back(db, hold=hold):
        return None
    removed, waiting, _first = _ask_each(
        db,
        hold=hold,
        objects=[
            (_removed_level(target.level), target.external_id)
            for target in _targets(db, hold=hold)
        ],
        actions=DELETES,
        ask=lambda level, external_id: actions.Delete(
            level=level, external_id=external_id, unpaid=True
        ),
        refused="lapse_removal_refused",
    )
    if waiting and now < hold.delete_after + SETTLE_FOR:
        return None
    _close(db, hold=hold, field="deleted_at", name=EventName.ADS_LAPSE_REMOVED, now=now)
    return removed


def _removed_level(level: str) -> str:
    """What the sweep deletes: the group it named, or else the whole campaign."""
    return ManagedLevel.ADSET if level == ManagedLevel.ADSET else ManagedLevel.CAMPAIGN


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
        payload={"ended_at": hold.ended_at.isoformat()}
        | ({"page_id": str(hold.page_id)} if hold.page_id else {}),
        occurred_at=now,
    )
    db.commit()
