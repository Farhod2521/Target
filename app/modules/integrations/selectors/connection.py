import uuid

from metaads import PROVIDER
from metaads.oauth import INSTAGRAM_SCOPE, holds, missing
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.integrations.constants import USABLE_CONNECTION_STATUSES
from app.modules.integrations.models import (
    AdAccount,
    PageAccount,
    PixelAccount,
    ProviderConnection,
)
from app.modules.integrations.selectors.slots import page_shown


def meta_connection(db: Session, *, owner: User) -> ProviderConnection | None:
    return db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.owner_id == owner.id,
            ProviderConnection.provider == PROVIDER,
        )
    )


def owner_of_meta_user(db: Session, *, external_user_id: str) -> User | None:
    if not external_user_id:
        return None
    connection = db.scalar(
        select(ProviderConnection).where(
            ProviderConnection.provider == PROVIDER,
            ProviderConnection.external_user_id == external_user_id,
        )
    )
    return connection.owner if connection is not None else None


def is_connected(db: Session, *, owner: User) -> bool:
    connection = meta_connection(db, owner=owner)
    return connection is not None and connection.status in USABLE_CONNECTION_STATUSES


def broken_meta_connection(db: Session, *, owner: User) -> ProviderConnection | None:
    return broken_of(connection=meta_connection(db, owner=owner))


def broken_of(*, connection: ProviderConnection | None) -> ProviderConnection | None:
    if connection is None or connection.status in USABLE_CONNECTION_STATUSES:
        return None
    return connection if connection.token_fingerprint else None


def broken_meta_connections(db: Session) -> list[ProviderConnection]:
    return list(
        db.scalars(
            select(ProviderConnection)
            .where(
                ProviderConnection.provider == PROVIDER,
                ProviderConnection.status.not_in(USABLE_CONNECTION_STATUSES),
                ProviderConnection.token_fingerprint != "",
            )
            .order_by(ProviderConnection.updated_at)
        )
    )


def ad_accounts_query(*, owner: User) -> Select[tuple[AdAccount]]:
    return (
        select(AdAccount)
        .where(AdAccount.owner_id == owner.id, AdAccount.provider == PROVIDER)
        .order_by(
            AdAccount.is_current.desc(),
            AdAccount.is_active.desc(),
            AdAccount.may_advertise.desc().nulls_first(),
            AdAccount.name,
        )
    )


def ad_accounts(db: Session, *, owner: User) -> list[AdAccount]:
    return list(db.scalars(ad_accounts_query(owner=owner)))


def pages(db: Session, *, owner: User) -> list[PageAccount]:
    return list(
        db.scalars(
            select(PageAccount)
            .where(PageAccount.owner_id == owner.id, PageAccount.provider == PROVIDER)
            .order_by(
                PageAccount.is_current.desc(),
                PageAccount.is_active.desc(),
                PageAccount.name,
            )
        )
    )


def page_by_id(db: Session, *, owner: User, page_id: object) -> PageAccount | None:
    try:
        key = page_id if isinstance(page_id, uuid.UUID) else uuid.UUID(str(page_id))
    except ValueError:
        return None
    return db.scalar(
        select(PageAccount).where(
            PageAccount.owner_id == owner.id,
            PageAccount.provider == PROVIDER,
            PageAccount.id == key,
        )
    )


def spare_pages(db: Session, *, owner: User) -> list[PageAccount]:
    return list(
        db.scalars(
            select(PageAccount)
            .where(
                PageAccount.owner_id == owner.id,
                PageAccount.provider == PROVIDER,
                PageAccount.is_active.is_(False),
            )
            .order_by(PageAccount.name)
        )
    )


def ad_accounts_held_elsewhere(
    db: Session, *, owner: User
) -> tuple[dict[str, str], ...]:
    connection = meta_connection(db, owner=owner)
    if connection is None:
        return ()
    return tuple(connection.ad_accounts_taken or ())


def active_ad_account(db: Session, *, owner: User) -> AdAccount | None:
    return db.scalar(
        select(AdAccount).where(
            AdAccount.owner_id == owner.id,
            AdAccount.provider == PROVIDER,
            AdAccount.is_current.is_(True),
        )
    )


def page_ad_account(db: Session, *, owner: User, page: PageAccount) -> AdAccount | None:
    from app.modules.integrations.selectors.pairs import page_pairs

    pairs = page_pairs(db, owner=owner, pages=[page])
    if not pairs:
        return None
    return next(
        (pair.account for pair in pairs if pair.account.is_current), pairs[0].account
    )


def pixels(db: Session, *, owner: User) -> list[PixelAccount]:
    account = active_ad_account(db, owner=owner)
    if account is None:
        return []
    return list(
        db.scalars(
            select(PixelAccount)
            .where(
                PixelAccount.owner_id == owner.id,
                PixelAccount.provider == PROVIDER,
                PixelAccount.ad_account_id == account.id,
            )
            .order_by(PixelAccount.is_active.desc(), PixelAccount.name)
        )
    )


def active_pixel(db: Session, *, owner: User) -> PixelAccount | None:
    account = active_ad_account(db, owner=owner)
    if account is None:
        return None
    return db.scalar(
        select(PixelAccount).where(
            PixelAccount.owner_id == owner.id,
            PixelAccount.provider == PROVIDER,
            PixelAccount.ad_account_id == account.id,
            PixelAccount.is_active.is_(True),
        )
    )


def active_page(db: Session, *, owner: User) -> PageAccount | None:
    found = list(
        db.scalars(
            select(PageAccount)
            .where(
                PageAccount.owner_id == owner.id,
                PageAccount.provider == PROVIDER,
                PageAccount.is_active.is_(True),
            )
            .order_by(PageAccount.is_current.desc(), PageAccount.name)
            .limit(2)
        )
    )
    return page_shown(found)


def missing_scopes(db: Session, *, owner: User) -> tuple[str, ...]:
    connection = meta_connection(db, owner=owner)
    if connection is None:
        return ()
    return missing(connection.scopes)


def instagram_permission_missing(db: Session, *, owner: User) -> bool:
    connection = meta_connection(db, owner=owner)
    if connection is None or not connection.scopes:
        return False
    return not holds(connection.scopes, INSTAGRAM_SCOPE)
