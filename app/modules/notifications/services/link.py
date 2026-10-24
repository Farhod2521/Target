"""Tying a Telegram chat to a cabinet, and to an office account."""

import logging
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.notifications.bot import (
    is_configured,
    staff_bot_configured,
    staff_deep_link,
)
from app.modules.notifications.constants import (
    LINK_TOKEN_BYTES,
    LINK_TOKEN_KEY,
    LINK_TOKEN_TTL_SECONDS,
    OUTCOME_NOTICE_HOURS,
    STAFF_LINK_TOKEN_KEY,
    NoticeKind,
)
from app.modules.notifications.exceptions import (
    BotNotConfigured,
    ChatTakenByAnother,
    LinkTokenInvalid,
    NotLinked,
    StaffChatTaken,
    StaffLinkInvalid,
)
from app.modules.notifications.keys import outcome_subject, rejection_subject
from app.modules.notifications.models import StaffChat, TelegramChat
from app.modules.notifications.selectors import (
    chat_by_id,
    chat_for,
    staff_chat_by_id,
    staff_chat_for,
)
from app.modules.notifications.services.journal import settle

logger = logging.getLogger(__name__)


def issue_link_token(*, owner: User) -> str:
    if not is_configured():
        raise BotNotConfigured
    token = secrets.token_urlsafe(LINK_TOKEN_BYTES)
    cache.set(LINK_TOKEN_KEY.format(token=token), str(owner.id), LINK_TOKEN_TTL_SECONDS)
    return token


def link_chat(
    db: Session, *, token: str, chat_id: str, username: str, now: datetime
) -> TelegramChat:
    owner = _spend(db, LINK_TOKEN_KEY, token, refused=LinkTokenInvalid)
    existing = chat_by_id(db, chat_id=chat_id)
    if existing is not None and existing.is_active and existing.owner_id != owner.id:
        raise ChatTakenByAnother
    db.execute(
        update(TelegramChat)
        .where(
            TelegramChat.owner_id == owner.id,
            TelegramChat.is_active.is_(True),
            TelegramChat.chat_id != chat_id,
        )
        .values(is_active=False, last_error="", last_error_at=None, updated_at=now)
    )
    chat = db.scalars(
        select(TelegramChat).where(
            TelegramChat.owner_id == owner.id, TelegramChat.chat_id == chat_id
        )
    ).first()
    if chat is None:
        chat = TelegramChat(owner_id=owner.id, chat_id=chat_id, linked_at=now)
        db.add(chat)
    chat.username = username
    chat.is_active = True
    chat.last_error = ""
    chat.last_error_at = None
    db.flush()
    _claim_history(db, chat=chat, now=now)
    logger.info("telegram_linked", extra={"owner": str(owner.id)})
    return chat


def unlink_chat(db: Session, *, owner: User) -> TelegramChat:
    chat = chat_for(db, owner=owner)
    if chat is None:
        raise NotLinked
    return _switch_off(db, chat=chat, reason="", now=None)


def stop_chat(db: Session, *, chat_id: str) -> TelegramChat | None:
    chat = chat_by_id(db, chat_id=chat_id)
    if chat is None or not chat.is_active:
        return chat
    return _switch_off(db, chat=chat, reason="", now=None)


def deactivate(
    db: Session, *, chat: TelegramChat, reason: str, now: datetime
) -> TelegramChat:
    logger.info("telegram_deactivated", extra={"reason": reason})
    return _switch_off(db, chat=chat, reason=reason, now=now)


def _switch_off(
    db: Session, *, chat: TelegramChat, reason: str, now: datetime | None
) -> TelegramChat:
    chat.is_active = False
    chat.last_error = reason
    chat.last_error_at = now if reason else None
    db.flush()
    return chat


def _spend(db: Session, template: str, token: str, *, refused: type[Exception]) -> User:
    key = template.format(token=token)
    owner_id = cache.get(key)
    if not owner_id:
        raise refused
    cache.delete(key)
    import uuid

    owner = db.get(User, uuid.UUID(str(owner_id)))
    if owner is None:
        raise refused
    return owner


def _claim_history(db: Session, *, chat: TelegramChat, now: datetime) -> None:
    """Mark what the cabinet already shows as told, so linking is not a flood."""
    from app.modules.ads.models import Ad
    from app.modules.agent.selectors import recently_assessed, waiting

    owner = chat.owner
    subjects = [
        (NoticeKind.SUGGESTION, str(row.id))
        for row in waiting(db, owner=owner, now=now)
    ]
    subjects += [
        (NoticeKind.SUGGESTION, outcome_subject(pk=row.id))
        for row in recently_assessed(
            db,
            owner=owner,
            since=now - timedelta(hours=OUTCOME_NOTICE_HOURS),
            limit=None,
        )
    ]
    refused = db.scalars(select(Ad).where(Ad.owner_id == owner.id))
    subjects += [
        (
            NoticeKind.REJECTION,
            rejection_subject(external_id=ad.external_id, feedback=ad.review_feedback),
        )
        for ad in refused
        if ad.review_feedback
    ]
    for kind, subject in subjects:
        settle(db, chat=chat, kind=kind, subject=subject, now=now)


# -- the office's bot -----------------------------------------------------------


def issue_staff_link_token(db: Session, *, owner: User) -> str:
    from app.modules.backoffice.services import holds_any_role

    if not staff_bot_configured():
        raise BotNotConfigured
    if not holds_any_role(db, user=owner):
        raise StaffLinkInvalid
    token = secrets.token_urlsafe(LINK_TOKEN_BYTES)
    cache.set(
        STAFF_LINK_TOKEN_KEY.format(token=token), str(owner.id), LINK_TOKEN_TTL_SECONDS
    )
    return token


def staff_link_url(db: Session, *, owner: User) -> str:
    return staff_deep_link(payload=issue_staff_link_token(db, owner=owner))


def staff_link_of(db: Session, *, owner: User) -> StaffChat | None:
    return staff_chat_for(db, owner=owner)


def link_staff_chat(
    db: Session, *, token: str, chat_id: str, username: str, now: datetime
) -> StaffChat:
    from app.modules.backoffice.services import holds_any_role

    owner = _spend(db, STAFF_LINK_TOKEN_KEY, token, refused=StaffLinkInvalid)
    if not holds_any_role(db, user=owner):
        raise StaffLinkInvalid
    existing = staff_chat_by_id(db, chat_id=chat_id)
    if existing is not None and existing.owner_id != owner.id:
        raise StaffChatTaken
    db.execute(
        update(StaffChat)
        .where(
            StaffChat.owner_id == owner.id,
            StaffChat.is_active.is_(True),
            StaffChat.chat_id != chat_id,
        )
        .values(is_active=False, updated_at=now)
    )
    chat = db.scalars(
        select(StaffChat).where(
            StaffChat.owner_id == owner.id, StaffChat.chat_id == chat_id
        )
    ).first()
    if chat is None:
        chat = StaffChat(owner_id=owner.id, chat_id=chat_id)
        db.add(chat)
    chat.username = username
    chat.is_active = True
    chat.linked_at = now
    db.flush()
    logger.info("staff_telegram_linked", extra={"owner": str(owner.id)})
    return chat


def unlink_staff_chat(db: Session, *, owner: User) -> StaffChat:
    chat = staff_chat_for(db, owner=owner)
    if chat is None:
        raise NotLinked
    chat.is_active = False
    db.flush()
    return chat


def stop_staff_chat(db: Session, *, chat_id: str) -> StaffChat | None:
    chat = staff_chat_by_id(db, chat_id=chat_id)
    if chat is not None:
        chat.is_active = False
        db.flush()
    return chat


__all__ = [
    "deactivate",
    "issue_link_token",
    "issue_staff_link_token",
    "link_chat",
    "link_staff_chat",
    "staff_link_of",
    "staff_link_url",
    "stop_chat",
    "stop_staff_chat",
    "unlink_chat",
    "unlink_staff_chat",
]
