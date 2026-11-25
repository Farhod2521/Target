"""A subscription the office freezes: it serves nothing, and its days are kept.

While ``frozen_at`` is set every selector a customer is served by reads the
subscription as not running (``live_subscription``, ``entitled_owner_ids``,
``recently_entitled_owner_ids``): the cabinet is read only, the AI, the bot's
reports and the sync stop, no lead is fetched, and what we built is stopped
at Meta. On release the frozen time is added to ``expires_at`` - not a minute
of the plan is spent - and the adverts switch back on.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit
from app.modules.billing.constants import (
    LIVE_SUBSCRIPTION_STATUSES,
    MAX_FREEZE_DAYS,
    HistoryKind,
)
from app.modules.billing.exceptions import (
    FreezeUntilOutOfRange,
    NotFrozen,
    NothingToFreeze,
    ReasonRequired,
)
from app.modules.billing.models import Subscription, SubscriptionChange
from app.modules.billing.services.entitlement import record_change

logger = logging.getLogger(__name__)
SUBSCRIPTION = "subscription"


def _locked_live(db: Session, *, owner: User, now: datetime) -> Subscription | None:
    """The running subscription, frozen or not, locked for the write."""
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
        .with_for_update()
    )


def _locked_frozen(db: Session, *, owner: User) -> Subscription | None:
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.frozen_at.is_not(None),
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
        .with_for_update()
    )


def freeze_subscription(
    db: Session,
    *,
    owner: User,
    until: datetime,
    reason: str,
    actor: User,
    now: datetime,
) -> Subscription:
    """Freeze the running subscription until ``until``.

    Asked again of a frozen one it only moves the release and the reason: the
    freeze keeps counting from when it began.
    """
    reason = reason.strip()
    if not reason:
        raise ReasonRequired
    if until <= now or until > now + timedelta(days=MAX_FREEZE_DAYS):
        raise FreezeUntilOutOfRange(limit=MAX_FREEZE_DAYS)
    subscription = _locked_frozen(db, owner=owner)
    again = subscription is not None
    if subscription is None:
        subscription = _locked_live(db, owner=owner, now=now)
    if subscription is None:
        raise NothingToFreeze
    if not again:
        subscription.frozen_at = now
    subscription.frozen_until = until
    subscription.frozen_reason = reason
    subscription.frozen_by_id = actor.id
    subscription.note = _note(
        subscription.note,
        f"{now:%d.%m.%Y} · muzlatildi {until:%d.%m.%Y %H:%M} gacha · "
        f"{actor.email} · {reason}",
    )
    db.flush()
    if not again:
        record_change(
            db,
            subscription=subscription,
            kind=HistoryKind.FROZEN,
            from_plan=subscription.plan,
            move=None,
            days=0,
            expires_before=subscription.expires_at,
            now=now,
            actor=actor,
            reason=reason,
        )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.SUBSCRIPTION_FROZEN,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "until": until.isoformat(),
            "reason": reason,
            "again": again,
            "actor_id": str(actor.id),
        },
        occurred_at=now,
    )
    if not again:
        owner_id = str(owner.id)
        on_commit(db, lambda: _hold(owner_id))
    return subscription


def release_subscription(
    db: Session, *, owner: User, actor: User | None, now: datetime
) -> Subscription:
    """End the freeze now: the frozen time goes back on ``expires_at``, the
    adverts switch back on and the owner is told, in the bot and the cabinet."""
    subscription = _locked_frozen(db, owner=owner)
    if subscription is None or subscription.frozen_at is None:
        raise NotFrozen
    return _release(db, subscription=subscription, actor=actor, now=now)


def release_due(db: Session, *, now: datetime) -> int:
    """Release every freeze whose time has come. Freezes released."""
    from app.modules.billing.selectors import due_releases

    released = 0
    for pk in due_releases(db, now=now):
        subscription = db.scalar(
            select(Subscription)
            .where(Subscription.id == pk, Subscription.frozen_at.is_not(None))
            .with_for_update(skip_locked=True)
        )
        if subscription is None:
            db.rollback()
            continue
        try:
            _release(db, subscription=subscription, actor=None, now=now)
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("freeze release for %s failed", pk)
            continue
        released += 1
    return released


def _release(
    db: Session, *, subscription: Subscription, actor: User | None, now: datetime
) -> Subscription:
    frozen_at = subscription.frozen_at
    assert frozen_at is not None
    kept = max(now - frozen_at, timedelta(0))
    before = subscription.expires_at
    subscription.expires_at = before + kept
    subscription.frozen_at = None
    subscription.frozen_until = None
    subscription.frozen_reason = ""
    subscription.frozen_by_id = None
    who = actor.email if actor is not None else "vaqti keldi"
    subscription.note = _note(
        subscription.note,
        f"{now:%d.%m.%Y} · muzlatishdan chiqdi · +{_days(kept)} kun qaytdi · {who}",
    )
    db.flush()
    change = record_change(
        db,
        subscription=subscription,
        kind=HistoryKind.UNFROZEN,
        from_plan=subscription.plan,
        move=None,
        days=_days(kept),
        expires_before=before,
        now=now,
        actor=actor,
    )
    emit(
        db,
        owner_id=subscription.owner_id,
        name=EventName.SUBSCRIPTION_UNFROZEN,
        aggregate_type=SUBSCRIPTION,
        aggregate_id=subscription.id,
        payload={
            "frozen_at": frozen_at.isoformat(),
            "from": before.isoformat(),
            "to": subscription.expires_at.isoformat(),
            "actor_id": str(actor.id) if actor is not None else "",
        },
        occurred_at=now,
    )
    owner_id = str(subscription.owner_id)
    change_id = str(change.id)
    on_commit(db, lambda: _released_tasks(owner_id=owner_id, change_id=change_id))
    return subscription


def last_release(
    db: Session, *, owner: User, since: datetime
) -> SubscriptionChange | None:
    """The owner's latest release after ``since``: the cabinet shows it."""
    return db.scalar(
        select(SubscriptionChange)
        .where(
            SubscriptionChange.owner_id == owner.id,
            SubscriptionChange.kind == HistoryKind.UNFROZEN,
            SubscriptionChange.occurred_at >= since,
        )
        .order_by(SubscriptionChange.occurred_at.desc())
        .limit(1)
    )


def _days(kept: timedelta) -> int:
    """Whole days given back, as the history shows them (the exact time is kept)."""
    return round(kept.total_seconds() / 86_400)


def _note(existing: str, line: str) -> str:
    return f"{existing}\n{line}".strip()


def _hold(owner_id: str) -> None:
    from app.modules.ads.tasks import hold_frozen_owner_task

    hold_frozen_owner_task.delay(owner_id)


def _released_tasks(*, owner_id: str, change_id: str) -> None:
    from app.modules.ads.tasks import resume_after_payment_task
    from app.modules.leads.tasks import reread_unpaid_leads_task
    from app.modules.notifications.tasks import announce_unfrozen_task

    resume_after_payment_task.delay(owner_id)
    reread_unpaid_leads_task.delay(owner_id)
    announce_unfrozen_task.delay(change_id)


__all__ = [
    "freeze_subscription",
    "last_release",
    "release_due",
    "release_subscription",
]
