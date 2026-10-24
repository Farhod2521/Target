import math
import uuid
from collections.abc import Collection
from datetime import datetime, timedelta

from metaads import PROVIDER
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.billing.constants import (
    LAPSED_SWEEP_DAYS,
    LIVE_SUBSCRIPTION_STATUSES,
    SubscriptionStatus,
)
from app.modules.billing.models import Subscription
from app.modules.integrations.models import AdAccount


def live_subscription(db: Session, *, owner: User) -> Subscription | None:
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > utcnow(),
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
    )


def trial_in_progress(db: Session, *, owner: User) -> Subscription | None:
    live = live_subscription(db, owner=owner)
    if live is None or live.status != SubscriptionStatus.TRIAL:
        return None
    return live


def has_live_subscription(db: Session, *, owner: User) -> bool:
    return live_subscription(db, owner=owner) is not None


def days_left(*, subscription: Subscription | None, now: datetime) -> int | None:
    if subscription is None:
        return None
    remaining = (subscription.expires_at - now).total_seconds()
    return max(0, math.ceil(remaining / 86_400))


def subscription_ended_at(db: Session, *, owner: User) -> datetime | None:
    if live_subscription(db, owner=owner) is not None:
        return None
    return db.scalar(
        select(Subscription.expires_at)
        .where(Subscription.owner_id == owner.id)
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )


def live_subscription_for_account(
    db: Session, *, ad_account: AdAccount
) -> Subscription | None:
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == ad_account.owner_id,
            Subscription.ad_account_id == ad_account.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > utcnow(),
        )
        .limit(1)
    )


def latest_subscription(db: Session, *, owner: User) -> Subscription | None:
    live = db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
    )
    return live or db.scalar(
        select(Subscription)
        .where(Subscription.owner_id == owner.id)
        .order_by(Subscription.started_at.desc())
        .limit(1)
    )


def has_ever_subscribed(db: Session, *, owner: User) -> bool:
    return (
        db.scalar(
            select(Subscription.id).where(Subscription.owner_id == owner.id).limit(1)
        )
        is not None
    )


def may_prepare(db: Session, *, owner: User) -> bool:
    return has_live_subscription(db, owner=owner)


def chosen_account(db: Session, *, owner: User) -> AdAccount | None:
    return db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == PROVIDER,
            AdAccount.is_active.is_(True),
            AdAccount.is_current.is_(True),
        )
    )


def prepared_account(db: Session, *, owner: User) -> AdAccount | None:
    if owner.prepared_at is None:
        return None
    return chosen_account(db, owner=owner)


def bound_subscription(db: Session, *, owner: User) -> Subscription | None:
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id, Subscription.ad_account_id.is_not(None)
        )
        .order_by(Subscription.started_at.desc())
        .limit(1)
    )


def bound_account(db: Session, *, owner: User) -> AdAccount | None:
    subscription = bound_subscription(db, owner=owner)
    return subscription.ad_account if subscription is not None else None


def setup_locked(db: Session, *, owner: User) -> bool:
    subscription = bound_subscription(db, owner=owner)
    if subscription is None:
        return owner.prepared_at is not None
    if subscription.setup_completed_at is not None:
        return True
    return live_subscription(db, owner=owner) is None


def setup_pending(db: Session, *, owner: User) -> bool:
    live = live_subscription(db, owner=owner)
    return live is not None and live.setup_completed_at is None


def subscribed_account_ids(
    db: Session | None = None,
) -> Select[tuple[uuid.UUID | None]]:
    return select(Subscription.ad_account_id).where(
        Subscription.ad_account_id.is_not(None)
    )


def subscribed_owner_ids(db: Session | None = None) -> Select[tuple[uuid.UUID]]:
    return select(Subscription.owner_id)


def recently_entitled_owner_ids(
    db: Session | None = None, *, now: datetime
) -> Select[tuple[uuid.UUID]]:
    return select(Subscription.owner_id).where(
        Subscription.expires_at > now - timedelta(days=LAPSED_SWEEP_DAYS)
    )


def entitled_owner_ids(
    db: Session | None = None, *, now: datetime
) -> Select[tuple[uuid.UUID]]:
    return select(Subscription.owner_id).where(
        Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
        Subscription.expires_at > now,
    )


def lapsed_deadlines(
    db: Session, *, owner_ids: Collection[uuid.UUID], now: datetime
) -> dict[uuid.UUID, datetime]:
    rows = db.execute(
        select(Subscription.owner_id, func.max(Subscription.expires_at))
        .where(
            Subscription.owner_id.in_(list(owner_ids)),
            Subscription.owner_id.not_in(entitled_owner_ids(now=now)),
        )
        .group_by(Subscription.owner_id)
    )
    return {owner: end for owner, end in rows}


def expiring_subscriptions(
    db: Session, *, start: datetime, end: datetime
) -> list[Subscription]:
    return list(
        db.scalars(
            select(Subscription)
            .where(
                Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
                Subscription.expires_at >= start,
                Subscription.expires_at < end,
            )
            .order_by(Subscription.expires_at)
        )
    )


def running_subscription(
    db: Session, *, owner: User, now: datetime
) -> Subscription | None:
    return db.scalar(
        select(Subscription)
        .where(
            Subscription.owner_id == owner.id,
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
        )
        .limit(1)
    )
