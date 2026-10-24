import uuid
from typing import Any

from googleadskit import PROVIDER as GOOGLE
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, ProviderConnection
from app.modules.integrations.selectors.slots import Slots


def google_ads_on(*, user: Any) -> bool:
    if not settings.google_oauth_client_id:
        return False
    if settings.google_ads_enabled:
        return True
    email = str(getattr(user, "email", "") or "").casefold()
    return bool(email) and email in settings.google_ads_users


def google_connection(db: Session, *, owner: User) -> ProviderConnection | None:
    return db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.owner_id == owner.id,
            ProviderConnection.provider == GOOGLE,
        )
    )


def google_accounts(db: Session, *, owner: User) -> list[AdAccount]:
    return list(
        db.scalars(
            select(AdAccount)
            .where(AdAccount.owner_id == owner.id, AdAccount.provider == GOOGLE)
            .order_by(
                AdAccount.is_active.desc(),
                AdAccount.is_current.desc(),
                AdAccount.may_advertise.desc().nulls_last(),
                AdAccount.name,
            )
        )
    )


def subscribed_google_accounts(db: Session, *, owner: User) -> list[AdAccount]:
    return list(
        db.scalars(
            select(AdAccount)
            .where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == GOOGLE,
                AdAccount.is_active.is_(True),
            )
            .order_by(AdAccount.is_current.desc(), AdAccount.name)
        )
    )


def current_google_account(db: Session, *, owner: User) -> AdAccount | None:
    found = subscribed_google_accounts(db, owner=owner)
    return found[0] if found else None


def subscribed_google_account(
    db: Session, *, owner: User, account_id: object
) -> AdAccount | None:
    try:
        key = uuid.UUID(str(account_id))
    except ValueError:
        return None
    return db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == GOOGLE,
            AdAccount.is_active.is_(True),
            AdAccount.id == key,
        )
    )


def google_slots(db: Session, *, owner: User) -> Slots:
    from app.modules.billing.selectors import capacity

    used = db.scalar(
        select(func.count())
        .select_from(AdAccount)
        .where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == GOOGLE,
            AdAccount.is_active.is_(True),
        )
    )
    return Slots(allowed=capacity(db, owner=owner).google_accounts, used=int(used or 0))
