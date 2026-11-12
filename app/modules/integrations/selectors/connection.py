import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime

from metaads import PROVIDER
from metaads.oauth import INSTAGRAM_SCOPE, holds, missing
from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

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
            .options(joinedload(ProviderConnection.owner))
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


# -- what stands behind a connection that no longer works --------------------------------


@dataclass(frozen=True, slots=True)
class Disconnected:
    """A connection the shown accounts hang on that cannot be read with.

    Everything mirrored from those accounts is as old as ``last_synced_at``:
    a campaign drawn as running may have been stopped, or be spending, since.
    """

    provider: str
    status: str
    code: str
    lost_at: datetime | None
    last_synced_at: datetime | None


def frozen_accounts(
    db: Session, *, account_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, datetime | None]:
    """The accounts among these whose connection is down, with the last
    moment each was read."""
    wanted = set(account_ids)
    if not wanted:
        return {}
    rows = db.execute(
        select(AdAccount.id, AdAccount.synced_at)
        .join(ProviderConnection, ProviderConnection.id == AdAccount.connection_id)
        .where(
            AdAccount.id.in_(wanted),
            ProviderConnection.status.not_in(
                [str(s) for s in USABLE_CONNECTION_STATUSES]
            ),
        )
    )
    return {account_id: synced_at for account_id, synced_at in rows}


def disconnected_of(
    db: Session, *, accounts: Sequence[AdAccount]
) -> Disconnected | None:
    """The first dead connection among these accounts' own, or nothing.

    ``lost_at`` is the last time it fell or was taken away, as the events
    say; a connection that fell before those were written has none, and the
    caller still has ``last_synced_at`` to say how old the picture is.
    """
    from app.modules.audit.constants import EventName
    from app.modules.audit.models import Event

    by_connection: dict[uuid.UUID, list[AdAccount]] = {}
    for account in accounts:
        by_connection.setdefault(account.connection_id, []).append(account)
    if not by_connection:
        return None
    connection = db.scalars(
        select(ProviderConnection)
        .where(
            ProviderConnection.id.in_(list(by_connection)),
            ProviderConnection.status.not_in(
                [str(s) for s in USABLE_CONNECTION_STATUSES]
            ),
        )
        .order_by(ProviderConnection.created_at)
    ).first()
    if connection is None:
        return None
    lost_at = db.scalar(
        select(Event.occurred_at)
        .where(
            Event.owner_id == connection.owner_id,
            Event.aggregate_type == "connection",
            Event.aggregate_id == str(connection.id),
            Event.name.in_(
                [str(EventName.CONNECTION_LOST), str(EventName.CONNECTION_REMOVED)]
            ),
        )
        .order_by(Event.occurred_at.desc())
        .limit(1)
    )
    stamps = [account.synced_at for account in by_connection[connection.id]]
    read = [stamp for stamp in stamps if stamp is not None]
    return Disconnected(
        provider=connection.provider,
        status=str(connection.status),
        code=connection.last_error_code,
        lost_at=lost_at,
        last_synced_at=min(read) if read else None,
    )
