"""Reads the workers make: clocks, refusals, watched accounts, stale mirrors."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from zoneinfo import ZoneInfo

from metaads import PROVIDER as META
from metaads.accounts import manager_url
from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.models import Event
from app.modules.integrations.constants import (
    MIRROR_NIGHTLY_STALE_MINUTES,
    MIRROR_STALE_MINUTES,
    STALE_SAMPLE,
    USABLE_CONNECTION_STATUSES,
)
from app.modules.integrations.models import AdAccount, PixelAccount, ProviderConnection
from app.modules.integrations.selectors.connection import (
    active_ad_account,
    meta_connection,
)
from core.targeting import event_for_snippet

UTC = ZoneInfo("UTC")
OBSERVE_DAYS: Final = 45


def owner_clocks(db: Session, *, owner_ids: Iterable[object]) -> dict[str, ZoneInfo]:
    wanted = {str(owner_id) for owner_id in owner_ids}
    clocks: dict[str, ZoneInfo] = {}
    rows = db.scalars(
        select(AdAccount)
        .where(
            AdAccount.owner_id.in_([_uuid(o) for o in wanted]),
            AdAccount.provider == META,
            AdAccount.is_active.is_(True),
        )
        .order_by(AdAccount.owner_id, AdAccount.is_current.desc(), AdAccount.name)
    )
    for account in rows:
        clocks.setdefault(str(account.owner_id), account.tzinfo())
    return {owner_id: clocks.get(owner_id, UTC) for owner_id in wanted}


def local_hours(
    db: Session, *, owner_ids: Iterable[object], now: datetime
) -> dict[str, int]:
    return {
        owner_id: now.astimezone(clock).hour
        for owner_id, clock in owner_clocks(db, owner_ids=owner_ids).items()
    }


def owners_at_hour(
    db: Session, *, owner_ids: Iterable[object], now: datetime, hour: int
) -> set[str]:
    return {
        owner_id
        for owner_id, local in local_hours(db, owner_ids=owner_ids, now=now).items()
        if local == hour
    }


def _uuid(value: object) -> object:
    import uuid

    try:
        return uuid.UUID(str(value))
    except ValueError:
        return value


def identity_refusals(db: Session, *, owner: User) -> int:
    acted_at = db.scalar(
        select(Event.occurred_at)
        .where(Event.owner_id == owner.id, Event.name == EventName.USER_BLOCKED)
        .order_by(Event.occurred_at.desc())
        .limit(1)
    )
    query = (
        select(func.count())
        .select_from(Event)
        .where(
            Event.owner_id == owner.id,
            Event.name == EventName.CONNECTION_REFUSED_DUPLICATE,
        )
    )
    if acted_at is not None:
        query = query.where(Event.occurred_at > acted_at)
    return int(db.scalar(query) or 0)


@dataclass(frozen=True, slots=True)
class ActionRequired:
    person: str
    manager_url: str
    repeated: bool


def meta_action_required(db: Session, *, owner: User) -> ActionRequired | None:
    return action_required_of(
        db, connection=meta_connection(db, owner=owner), owner=owner
    )


def action_required_of(
    db: Session, *, connection: ProviderConnection | None, owner: User
) -> ActionRequired | None:
    if (
        connection is None
        or connection.action_required_at is None
        or connection.status not in USABLE_CONNECTION_STATUSES
    ):
        return None
    account = active_ad_account(db, owner=owner)
    return ActionRequired(
        person=connection.external_user_name,
        manager_url=manager_url(account.external_id if account else ""),
        repeated=connection.action_refusals > 1,
    )


def action_required_connections(db: Session) -> list[ProviderConnection]:
    return list(
        db.scalars(
            select(ProviderConnection)
            .where(
                ProviderConnection.provider == META,
                ProviderConnection.action_required_at.is_not(None),
                ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
                ProviderConnection.token_fingerprint != "",
            )
            .order_by(ProviderConnection.action_required_at)
        )
    )


def observed() -> ColumnElement[bool]:
    return and_(AdAccount.is_active.is_(False), AdAccount.leads_seen_at.is_not(None))


def watched_accounts(db: Session, *, owner: User) -> list[AdAccount]:
    return list(
        db.scalars(
            select(AdAccount)
            .where(AdAccount.owner_id == owner.id, observed())
            .order_by(AdAccount.leads_seen_at.desc().nulls_last(), AdAccount.name)
        )
    )


def observed_accounts(db: Session, *, now: datetime) -> list[AdAccount]:
    from app.modules.billing.selectors import subscribed_owner_ids

    return list(
        db.scalars(
            select(AdAccount)
            .join(ProviderConnection, ProviderConnection.id == AdAccount.connection_id)
            .where(
                observed(),
                AdAccount.leads_seen_at >= now - timedelta(days=OBSERVE_DAYS),
                AdAccount.owner_id.in_(subscribed_owner_ids(db)),
                ProviderConnection.status.in_(USABLE_CONNECTION_STATUSES),
            )
        )
    )


def fired_events(*, owner: User, pixel: PixelAccount | None) -> tuple[str, ...]:
    if pixel is None or pixel.owner_id != owner.id:
        return ()
    rows = pixel.recent_events if isinstance(pixel.recent_events, list) else []
    counted: list[tuple[int, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        found = event_for_snippet(
            provider=pixel.provider, name=str(row.get("event", ""))
        )
        if found is None:
            continue
        counted.append((_count(row.get("count")), found.key))
    counted.sort(key=lambda pair: -pair[0])
    seen: list[str] = []
    for _times, key in counted:
        if key not in seen:
            seen.append(key)
    return tuple(seen)


def _count(value: object) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 1


@dataclass(frozen=True, slots=True)
class MirrorAge:
    stale: int
    watched: int
    awake: int
    oldest_minutes: int
    external_ids: tuple[str, ...]
    outcomes: dict[str, str]


def mirror_age(db: Session, *, now: datetime) -> MirrorAge:
    from app.modules.ads.constants import MIRROR_SWEEP
    from app.modules.ads.selectors import (
        frequently_swept_accounts,
        last_sync_outcomes,
        nightly_swept_accounts,
    )

    watched = [
        account
        for account in nightly_swept_accounts(db)
        if account.connection is not None
        and account.connection.provider == META
        and account.connection.status in USABLE_CONNECTION_STATUSES
    ]
    awake = {account.id for account in frequently_swept_accounts(db, now=now)}

    def last_seen(account: AdAccount) -> datetime:
        return account.synced_at or account.created_at

    fresh = now - timedelta(minutes=MIRROR_STALE_MINUTES)
    nightly = now - timedelta(minutes=MIRROR_NIGHTLY_STALE_MINUTES)
    stale = sorted(
        (
            account
            for account in watched
            if last_seen(account) < (fresh if account.id in awake else nightly)
        ),
        key=last_seen,
    )
    named = [(account.id, account.external_id) for account in stale[:STALE_SAMPLE]]
    said = last_sync_outcomes(
        db, sweep=MIRROR_SWEEP, ad_account_ids=[str(pk) for pk, _ in named]
    )
    return MirrorAge(
        stale=len(stale),
        watched=len(watched),
        awake=sum(1 for account in watched if account.id in awake),
        oldest_minutes=(
            int((now - last_seen(stale[0])).total_seconds() // 60) if stale else 0
        ),
        external_ids=tuple(external_id for _, external_id in named),
        outcomes={
            external_id: said.get(str(pk), "unknown") for pk, external_id in named
        },
    )
