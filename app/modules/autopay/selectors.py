from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.autopay.constants import CHARGE_GRACE, CHARGE_LEAD, CardStatus
from app.modules.autopay.models import SavedCard
from app.modules.billing.constants import SubscriptionStatus
from app.modules.billing.models import Plan, Subscription


def active_card(db: Session, *, owner: User) -> SavedCard | None:
    return db.scalar(
        select(SavedCard).where(
            SavedCard.owner_id == owner.id, SavedCard.status == CardStatus.ACTIVE
        )
    )


def pending_card(db: Session, *, owner: User, session_id: str) -> SavedCard | None:
    return db.scalar(
        select(SavedCard).where(
            SavedCard.owner_id == owner.id,
            SavedCard.session_id == session_id,
        )
    )


def card_by_session(db: Session, *, session_id: str) -> SavedCard | None:
    return db.scalar(select(SavedCard).where(SavedCard.session_id == session_id))


def renewing_subscription(
    db: Session, *, owner_id: object, now: datetime
) -> Subscription | None:
    """The paid plan this owner's card renews, if it is due within the window."""
    return db.scalar(
        select(Subscription)
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(
            Subscription.owner_id == owner_id,
            Subscription.status == SubscriptionStatus.ACTIVE,
            Subscription.canceled_at.is_(None),
            Subscription.expires_at <= now + CHARGE_LEAD,
            Subscription.expires_at > now - CHARGE_GRACE,
            Plan.price > 0,
            Plan.is_active.is_(True),
            Plan.is_one_time.is_(False),
        )
        .order_by(Subscription.expires_at.desc())
        .limit(1)
    )


def due_card_ids(db: Session, *, now: datetime) -> list[object]:
    """Cards whose owner's paid plan runs out within the charging window."""
    return list(
        db.scalars(
            select(SavedCard.id)
            .join(Subscription, Subscription.owner_id == SavedCard.owner_id)
            .join(Plan, Plan.id == Subscription.plan_id)
            .where(
                SavedCard.status == CardStatus.ACTIVE,
                SavedCard.autopay.is_(True),
                Subscription.status == SubscriptionStatus.ACTIVE,
                Subscription.canceled_at.is_(None),
                Subscription.expires_at <= now + CHARGE_LEAD,
                Subscription.expires_at > now - CHARGE_GRACE,
                Plan.price > 0,
                Plan.is_active.is_(True),
                Plan.is_one_time.is_(False),
            )
            .distinct()
        )
    )


__all__ = [
    "active_card",
    "card_by_session",
    "due_card_ids",
    "pending_card",
    "renewing_subscription",
]
