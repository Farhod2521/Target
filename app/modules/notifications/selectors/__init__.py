"""Which chat to write to, and the deadline words notices quote."""

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.common.dates import date_format
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.notifications.constants import NOTICES_WITHOUT_SUBSCRIPTION, NoticeKind
from app.modules.notifications.models import InboxSeen, StaffChat, TelegramChat

logger = logging.getLogger(__name__)
FLAG_FOR: dict[str, str] = {
    NoticeKind.SUGGESTION: "notify_suggestions",
    NoticeKind.REPORT: "notify_report",
    NoticeKind.REJECTION: "notify_rejections",
    NoticeKind.ACTION_REQUIRED: "notify_rejections",
    NoticeKind.SPEND_GUARD: "notify_spend_guard",
    NoticeKind.DAILY_REPORT: "notify_daily_report",
    NoticeKind.FREQUENCY: "notify_suggestions",
}


def chat_for(db: Session, *, owner: User) -> TelegramChat | None:
    return db.scalars(
        select(TelegramChat)
        .where(TelegramChat.owner_id == owner.id, TelegramChat.is_active.is_(True))
        .limit(1)
    ).first()


def last_chat_for(db: Session, *, owner: User) -> TelegramChat | None:
    return db.scalars(
        select(TelegramChat)
        .where(TelegramChat.owner_id == owner.id)
        .order_by(TelegramChat.linked_at.desc())
        .limit(1)
    ).first()


def chat_by_id(db: Session, *, chat_id: str) -> TelegramChat | None:
    return db.scalars(
        select(TelegramChat)
        .where(TelegramChat.chat_id == str(chat_id))
        .order_by(TelegramChat.is_active.desc(), TelegramChat.updated_at.desc())
        .limit(1)
    ).first()


def chats_wanting(db: Session, *, kind: str) -> Select[Any]:
    from app.modules.billing.selectors import entitled_owner_ids

    query = select(TelegramChat).where(TelegramChat.is_active.is_(True))
    if kind in FLAG_FOR:
        query = query.where(getattr(TelegramChat, FLAG_FOR[kind]).is_(True))
    if kind not in NOTICES_WITHOUT_SUBSCRIPTION:
        query = query.where(
            TelegramChat.owner_id.in_(entitled_owner_ids(db, now=utcnow()))
        )
    return query.options(joinedload(TelegramChat.owner)).order_by(
        TelegramChat.linked_at
    )


def active_chats() -> Select[Any]:
    return (
        select(TelegramChat)
        .where(TelegramChat.is_active.is_(True))
        .options(joinedload(TelegramChat.owner))
        .order_by(TelegramChat.linked_at)
    )


def staff_chat_for(db: Session, *, owner: User) -> StaffChat | None:
    return db.scalars(
        select(StaffChat)
        .where(StaffChat.owner_id == owner.id, StaffChat.is_active.is_(True))
        .limit(1)
    ).first()


def staff_chat_by_id(db: Session, *, chat_id: str) -> StaffChat | None:
    return db.scalars(
        select(StaffChat)
        .where(StaffChat.chat_id == str(chat_id), StaffChat.is_active.is_(True))
        .limit(1)
    ).first()


def staff_chats_where(
    db: Session, *, allowed: Callable[[Any], bool]
) -> list[StaffChat]:
    chats = db.scalars(
        select(StaffChat)
        .join(User, User.id == StaffChat.owner_id)
        .where(StaffChat.is_active.is_(True), User.is_staff.is_(True))
    )
    return [chat for chat in chats if allowed(chat.owner)]


def deadline_text(db: Session, *, owner: User, moment: datetime) -> str:
    from app.modules.businesses.selectors import business_timezone

    zone = business_timezone(db, owner=owner)
    if zone:
        try:
            moment = moment.astimezone(ZoneInfo(zone))
        except (ZoneInfoNotFoundError, ValueError):
            logger.warning("unknown business timezone", extra={"zone": zone})
    return date_format(moment, "j F, H:i")


def undelivered_notices(db: Session, *, owner: User, now: datetime) -> int:
    from datetime import timedelta

    from sqlalchemy import func

    from app.modules.notifications.constants import NOTICE_TRIES, UNDELIVERED_DAYS
    from app.modules.notifications.models import TelegramNotice

    return (
        db.scalar(
            select(func.count(TelegramNotice.id)).where(
                TelegramNotice.owner_id == owner.id,
                TelegramNotice.sent_at.is_(None),
                TelegramNotice.attempts >= NOTICE_TRIES,
                TelegramNotice.created_at >= now - timedelta(days=UNDELIVERED_DAYS),
            )
        )
        or 0
    )


def seen_keys(db: Session, *, owner: User) -> frozenset[str]:
    return frozenset(
        db.scalars(select(InboxSeen.key).where(InboxSeen.owner_id == owner.id))
    )


def cached_inbox(db: Session, *, owner: User, now: datetime) -> tuple[Any, ...]:
    """The cabinet's waiting list, from the minute-long cache when it is warm."""
    from app.modules.notifications.selectors.bell import cached_inbox as held

    return held(db, owner=owner, now=now)


__all__ = [
    "FLAG_FOR",
    "active_chats",
    "cached_inbox",
    "chat_by_id",
    "chat_for",
    "chats_wanting",
    "deadline_text",
    "last_chat_for",
    "seen_keys",
    "staff_chat_by_id",
    "staff_chat_for",
    "staff_chats_where",
    "undelivered_notices",
]
