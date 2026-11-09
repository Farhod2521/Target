"""Which chat to write to, and the deadline words notices quote."""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, joinedload

from app.common.dates import date_format
from app.common.db import utcnow
from app.common.env import BASE_DIR
from app.modules.accounts.models import User
from app.modules.ads.constants import LaunchStatus
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.trace import TRACE_DIR
from app.modules.notifications.constants import NOTICES_WITHOUT_SUBSCRIPTION, NoticeKind
from app.modules.notifications.models import (
    InboxSeen,
    StaffChat,
    SupportBotChat,
    TelegramChat,
)
from core.inbox import LEFT_DAYS, LEFT_PREFIX

logger = logging.getLogger(__name__)
FAILED_LAUNCH_STATUSES = (LaunchStatus.FAILED, LaunchStatus.ROLLED_BACK)
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
    """The live chat first: coming back to an earlier phone keeps its old
    ``linked_at``, so the newest stamp can belong to a chat switched off since."""
    return db.scalars(
        select(TelegramChat)
        .where(TelegramChat.owner_id == owner.id)
        .order_by(TelegramChat.is_active.desc(), TelegramChat.linked_at.desc())
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


def support_bot_chat_by_id(db: Session, *, chat_id: str) -> SupportBotChat | None:
    """The support bot's row for one Telegram chat, live or stopped."""
    return db.scalar(
        select(SupportBotChat).where(SupportBotChat.chat_id == str(chat_id))
    )


def support_bot_chat_for(db: Session, *, owner: User) -> SupportBotChat | None:
    """The owner's live support-bot chat: where the office's replies go."""
    return db.scalars(
        select(SupportBotChat)
        .where(SupportBotChat.owner_id == owner.id, SupportBotChat.is_active.is_(True))
        .limit(1)
    ).first()


def last_support_bot_chat_for(db: Session, *, owner: User) -> SupportBotChat | None:
    """The owner's support-bot chat for the office: the live one, else the
    one that stopped last, with why."""
    return db.scalars(
        select(SupportBotChat)
        .where(SupportBotChat.owner_id == owner.id)
        .order_by(SupportBotChat.is_active.desc(), SupportBotChat.updated_at.desc())
        .limit(1)
    ).first()


def support_bot_usernames(
    db: Session, *, guest_chat_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Each bot guest chat's Telegram handle, for the office's guest list."""
    if not guest_chat_ids:
        return {}
    rows = db.execute(
        select(SupportBotChat.guest_chat_id, SupportBotChat.username).where(
            SupportBotChat.guest_chat_id.in_(guest_chat_ids)
        )
    ).all()
    return {guest_id: username for guest_id, username in rows if guest_id}


def support_bot_chat_for_guest(
    db: Session, *, guest_chat_id: uuid.UUID
) -> SupportBotChat | None:
    """The support-bot chat a guest chat was opened from, if it was."""
    return db.scalars(
        select(SupportBotChat)
        .where(SupportBotChat.guest_chat_id == guest_chat_id)
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


def failed_launch(db: Session, *, launch_id: str) -> CampaignLaunch | None:
    """A launch somebody has already retried into another state is not reported."""
    launch = db.get(CampaignLaunch, uuid.UUID(str(launch_id)))
    if launch is None or launch.status not in FAILED_LAUNCH_STATUSES:
        return None
    return launch


def launch_trace(*, launch_id: str) -> Path | None:
    """The newest trace of this launch: a file's stamp sorts by time."""
    matches = sorted((Path(BASE_DIR) / TRACE_DIR).glob(f"*_{launch_id[:8]}.md"))
    return matches[-1] if matches else None


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


def left_rows(db: Session, *, owner: User, now: datetime) -> list[InboxSeen]:
    """The lines this owner left as they are, while that still holds, newest first."""
    return list(
        db.scalars(
            select(InboxSeen)
            .where(
                InboxSeen.owner_id == owner.id,
                InboxSeen.key.startswith(LEFT_PREFIX),
                InboxSeen.created_at >= now - timedelta(days=LEFT_DAYS),
            )
            .order_by(InboxSeen.created_at.desc())
        )
    )


def left_keys(db: Session, *, owner: User, now: datetime) -> frozenset[str]:
    return frozenset(row.key for row in left_rows(db, owner=owner, now=now))


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
    "failed_launch",
    "last_chat_for",
    "last_support_bot_chat_for",
    "launch_trace",
    "left_keys",
    "left_rows",
    "seen_keys",
    "staff_chat_by_id",
    "staff_chat_for",
    "staff_chats_where",
    "support_bot_chat_by_id",
    "support_bot_chat_for",
    "support_bot_chat_for_guest",
    "support_bot_usernames",
    "undelivered_notices",
]
