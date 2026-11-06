"""Reading broadcasts: the office's list, who the bot would reach, the
site's news and what of it is unread."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, exists, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session

from app.modules.accounts.models import User
from app.modules.broadcasts.constants import PAGE_SIZE, Audience, DeliveryStatus
from app.modules.broadcasts.models import (
    Broadcast,
    BroadcastDelivery,
    BroadcastSeen,
    BroadcastTarget,
)
from app.modules.notifications.models import TelegramChat


@dataclass(frozen=True, slots=True)
class BroadcastPage:
    rows: list[Broadcast]
    total: int
    offset: int
    has_more: bool

    @property
    def next_offset(self) -> int | None:
        return self.offset + len(self.rows) if self.has_more else None


def _page(
    db: Session,
    query: Select[Any],
    *,
    offset: int,
    order: InstrumentedAttribute[Any],
) -> BroadcastPage:
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(order.desc(), Broadcast.id)
            .offset(offset)
            .limit(PAGE_SIZE + 1)
        )
    )
    return BroadcastPage(
        rows=rows[:PAGE_SIZE],
        total=total,
        offset=offset,
        has_more=len(rows) > PAGE_SIZE,
    )


def office_page(db: Session, *, status: str = "", offset: int = 0) -> BroadcastPage:
    """Newest first, drafts and sent alike."""
    query = select(Broadcast)
    if status:
        query = query.where(Broadcast.status == status)
    return _page(db, query, offset=offset, order=Broadcast.created_at)


def _published() -> Select[Any]:
    return select(Broadcast).where(
        Broadcast.to_site.is_(True), Broadcast.started_at.is_not(None)
    )


def _visible(user: User) -> Select[Any]:
    """Published, and for everyone or for this reader."""
    chosen = select(BroadcastTarget.id).where(
        BroadcastTarget.broadcast_id == Broadcast.id,
        BroadcastTarget.owner_id == user.id,
    )
    return _published().where(or_(Broadcast.audience == Audience.ALL, exists(chosen)))


def site_page(db: Session, *, user: User, offset: int = 0) -> BroadcastPage:
    """What the site shows this reader: ticked for it and sent, newest first."""
    return _page(db, _visible(user), offset=offset, order=Broadcast.started_at)


def site_broadcast(
    db: Session, broadcast_id: uuid.UUID, *, user: User | None = None
) -> Broadcast | None:
    """Published; for ``user`` when given. The picture's link, already
    issued to a reader who may see it, asks without one."""
    query = _visible(user) if user is not None else _published()
    return db.scalars(query.where(Broadcast.id == broadcast_id)).first()


def broadcast_by_id(db: Session, broadcast_id: uuid.UUID) -> Broadcast | None:
    return db.get(Broadcast, broadcast_id)


def target_users(db: Session, broadcast_id: uuid.UUID) -> list[User]:
    return list(
        db.scalars(
            select(User)
            .join(BroadcastTarget, BroadcastTarget.owner_id == User.id)
            .where(BroadcastTarget.broadcast_id == broadcast_id)
            .order_by(User.email)
        )
    )


def known_users(db: Session, ids: list[uuid.UUID]) -> list[User]:
    """Of these, the accounts that exist and are customers, not the office."""
    if not ids:
        return []
    return list(
        db.scalars(select(User).where(User.id.in_(ids), User.is_staff.is_(False)))
    )


def recipients(
    db: Session, row: Broadcast | None = None
) -> list[tuple[uuid.UUID, str]]:
    """Each bot chat a broadcast starting now goes to, as (owner, chat):
    linked, not switched off, news not turned off, the account not blocked,
    and one of the chosen when it is for the chosen. A chat shared by two
    accounts is reached once. Without ``row``, everyone's."""
    query = (
        select(TelegramChat.owner_id, TelegramChat.chat_id)
        .join(User, User.id == TelegramChat.owner_id)
        .where(
            TelegramChat.is_active.is_(True),
            TelegramChat.notify_news.is_(True),
            TelegramChat.chat_id != "",
            User.is_active.is_(True),
        )
        .order_by(TelegramChat.linked_at)
    )
    if row is not None and row.audience == Audience.SELECTED:
        query = query.where(
            TelegramChat.owner_id.in_(
                select(BroadcastTarget.owner_id).where(
                    BroadcastTarget.broadcast_id == row.id
                )
            )
        )
    seen: set[str] = set()
    found: list[tuple[uuid.UUID, str]] = []
    for owner_id, chat_id in db.execute(query).all():
        if chat_id not in seen:
            seen.add(chat_id)
            found.append((owner_id, chat_id))
    return found


def delivery_counts(
    db: Session, broadcast_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """Per broadcast, how many bot chats are at each delivery status."""
    counts: dict[uuid.UUID, dict[str, int]] = {
        key: {str(status): 0 for status in DeliveryStatus} for key in broadcast_ids
    }
    if not broadcast_ids:
        return counts
    rows = db.execute(
        select(
            BroadcastDelivery.broadcast_id,
            BroadcastDelivery.status,
            func.count(),
        )
        .where(BroadcastDelivery.broadcast_id.in_(broadcast_ids))
        .group_by(BroadcastDelivery.broadcast_id, BroadcastDelivery.status)
    ).all()
    for broadcast_id, status, count in rows:
        counts[broadcast_id][status] = int(count)
    return counts


def seen_at(db: Session, *, user: User) -> datetime:
    """When this reader last opened the news; a new account starts read."""
    stamp = db.scalar(
        select(BroadcastSeen.seen_at).where(BroadcastSeen.owner_id == user.id)
    )
    return stamp or user.date_joined


def unread_count(db: Session, *, user: User) -> int:
    since = seen_at(db, user=user)
    return int(
        db.scalar(
            select(func.count()).select_from(
                _visible(user).where(Broadcast.started_at > since).subquery()
            )
        )
        or 0
    )
