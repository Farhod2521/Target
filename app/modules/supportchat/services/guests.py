"""The sign-in page's chat: somebody not signed in writes to the office.

The guest gives a name, a phone and an email, and gets a token - the only
proof the chat is theirs, kept by their browser. Words only, both ways.

A stranger writing to the support bot gets a guest chat too
(``channel="support_bot"``): named by Telegram, with no phone or email,
and moved into an account's chat when that Telegram links one.
Signing in moves the words into the account's own chat, but only into the
account the guest named: its email or its phone, so a shared computer does
not hand one person's words to the next one signing in.
"""

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.common.exceptions import Conflict, DomainError, InputRefused
from app.common.hooks import fire
from app.common.throttle import hit
from app.modules.accounts.models import User
from app.modules.accounts.phone import clean_phone, normalize_email
from app.modules.supportchat.constants import (
    GUEST_FIRST_WORDS,
    GUEST_START_BUCKET,
    GUEST_STARTS_PER_HOUR,
    GUEST_STARTS_PER_HOUR_ALL,
    MAX_BODY_CHARS,
    MESSAGE_BUCKET,
    MESSAGES_PER_MINUTE,
    MessageKind,
    MessageSource,
)
from app.modules.supportchat.exceptions import (
    EmptyMessage,
    GuestChatMoved,
    MessageTooLong,
    TooManyGuestChats,
    TooManyMessages,
)
from app.modules.supportchat.models import (
    SupportConversation,
    SupportGuestChat,
    SupportGuestMessage,
    SupportMessage,
)
from app.modules.supportchat.services._store import MESSAGE_STORED, tell_inside
from app.modules.supportchat.services._tx import atomic
from app.modules.supportchat.services.send_to_support import chat_of_client

logger = logging.getLogger(__name__)

# The guest wrote: tell every member of Support in the staff bot. Takes
# ``message_id``.
GUEST_POSTED: Final = "supportchat.guest_posted"
# The office answered a guest: a support-bot guest gets it in Telegram.
# Takes ``message_id``.
GUEST_ANSWERED: Final = "supportchat.guest_answered"

_EMAIL = TypeAdapter(EmailStr)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Started:
    chat: SupportGuestChat
    token: str


def start_guest_chat(
    db: Session,
    *,
    name: str,
    phone: str,
    email: str,
    body: str,
    address: str,
    now: datetime,
    email_required: bool = True,
) -> Started:
    """The chat and its first message, together, and the token to come back
    with. Refused field by field before anything is written.

    ``email_required=False`` is the AI chat handing a visitor over: it asks
    only a name and a phone, and an email given there is still checked."""
    fields = _checked_guest(
        name=name, phone=phone, email=email, email_required=email_required
    )
    text = _checked_body(body or GUEST_FIRST_WORDS)
    if not hit(
        bucket=GUEST_START_BUCKET,
        key=address or "-",
        limit=GUEST_STARTS_PER_HOUR,
        window_seconds=3600,
    ) or not hit(
        bucket=GUEST_START_BUCKET,
        key="*",
        limit=GUEST_STARTS_PER_HOUR_ALL,
        window_seconds=3600,
    ):
        raise TooManyGuestChats
    token = secrets.token_urlsafe(32)

    def run() -> SupportGuestChat:
        chat = SupportGuestChat(id=uuid.uuid4(), token_hash=token_hash(token), **fields)
        db.add(chat)
        db.flush()
        _append(db, chat=chat, sender=None, text=text, now=now)
        return chat

    chat = atomic(db, run)
    logger.info("support guest chat started", extra={"chat_id": str(chat.id)})
    return Started(chat=chat, token=token)


def start_bot_guest_chat(
    db: Session, *, name: str, body: str, now: datetime
) -> SupportGuestChat:
    """A stranger's first words in the support bot, with the chat they open.

    Telegram vouches for nobody's phone or email, so neither is asked; the
    name is the one Telegram shows. No token leaves: the bot's own row is
    what ties the Telegram chat to this one. The rate limit is the
    message one, keyed by the Telegram chat, like every message after.
    """
    text = _checked_body(body)
    token = secrets.token_urlsafe(32)

    def run() -> SupportGuestChat:
        chat = SupportGuestChat(
            id=uuid.uuid4(),
            token_hash=token_hash(token),
            name=(" ".join(name.split()) or "Telegram")[:120],
            channel=MessageSource.SUPPORT_BOT,
        )
        db.add(chat)
        db.flush()
        _append(db, chat=chat, sender=None, text=text, now=now)
        return chat

    chat = atomic(db, run)
    logger.info("support bot guest chat started", extra={"chat_id": str(chat.id)})
    return chat


def guest_writes(
    db: Session, *, chat: SupportGuestChat, body: str, now: datetime
) -> SupportGuestMessage:
    """One more message from the guest, while the chat is still theirs."""
    text = _checked_body(body)
    if not hit(
        bucket=MESSAGE_BUCKET,
        key=f"guest:{chat.id}",
        limit=MESSAGES_PER_MINUTE,
        window_seconds=60,
    ):
        raise TooManyMessages

    def run() -> SupportGuestMessage:
        locked = _locked(db, chat.id)
        if locked.claimed_at is not None:
            raise GuestChatMoved
        return _append(db, chat=locked, sender=None, text=text, now=now)

    return atomic(db, run)


def office_answers_guest(
    db: Session, *, chat: SupportGuestChat, sender: User, body: str, now: datetime
) -> SupportGuestMessage:
    """A reply from Support. The caller has checked the role."""
    text = _checked_body(body)

    def run() -> SupportGuestMessage:
        locked = _locked(db, chat.id)
        if locked.claimed_at is not None:
            raise Conflict(
                "Suhbat mijozning kabinetiga ko'chirilgan. Mijoz chatidan yozing."
            )
        return _append(db, chat=locked, sender=sender, text=text, now=now)

    return atomic(db, run)


def settle_guest(db: Session, *, chat: SupportGuestChat, now: datetime) -> None:
    """Out of the queue until the guest writes again."""

    def run() -> None:
        _locked(db, chat.id).settled_at = now

    atomic(db, run)


def mark_guest_read(
    db: Session, *, chat: SupportGuestChat, by_guest: bool, now: datetime
) -> bool:
    """The other side's ticks. False when there was nothing new to read."""
    last = chat.last_office_at if by_guest else chat.last_guest_at
    seen = chat.guest_read_at if by_guest else chat.office_read_at
    if last is None or (seen is not None and seen >= last):
        return False

    def run() -> None:
        locked = _locked(db, chat.id)
        if by_guest:
            locked.guest_read_at = now
        else:
            locked.office_read_at = now

    atomic(db, run)
    return True


def claim_guest_chat(db: Session, *, token: str, user: User, now: datetime) -> int:
    """Move the guest's words into this account's chat, if the guest named
    this account. Returns how many messages moved; 0 for a token that names
    nothing, a chat already moved, or somebody else's account."""
    chat = db.scalar(
        select(SupportGuestChat).where(SupportGuestChat.token_hash == token_hash(token))
    )
    if chat is None or chat.claimed_at is not None or not names_account(chat, user):
        return 0
    return move_guest_chat(db, chat=chat, user=user, now=now)


def move_guest_chat(
    db: Session, *, chat: SupportGuestChat, user: User, now: datetime
) -> int:
    """Move every word of this guest chat into the account's chat. The
    caller has proved the two are the same person. Returns how many moved;
    0 when the chat had moved already."""

    def run() -> int:
        locked = _locked(db, chat.id)
        if locked.claimed_at is not None:
            return 0
        source = (
            MessageSource.SUPPORT_BOT
            if locked.channel == MessageSource.SUPPORT_BOT
            else MessageSource.SITE
        )
        conversation = chat_of_client(db, owner=user, now=now)
        words = list(
            db.scalars(
                select(SupportGuestMessage)
                .where(SupportGuestMessage.chat_id == locked.id)
                .order_by(SupportGuestMessage.created_at, SupportGuestMessage.id)
            )
        )
        moved_rows: list[SupportMessage] = []
        for word in words:
            moved_rows.append(
                SupportMessage(
                    id=uuid.uuid4(),
                    created_at=word.created_at,
                    updated_at=now,
                    owner_id=user.id,
                    conversation_id=conversation.id,
                    # An office reply keeps its author; an erased one reads
                    # as the office all the same.
                    sender_id=user.id if word.from_guest else word.sender_id,
                    kind=MessageKind.TEXT,
                    body=word.body,
                    source=source if word.from_guest else MessageSource.SITE,
                )
            )
        db.add_all(moved_rows)
        _merge_moments(conversation, locked)
        locked.claimed_by_id = user.id
        locked.claimed_at = now
        db.flush()
        for row in moved_rows:
            tell_inside(db, MESSAGE_STORED, message=row)
        return len(words)

    moved = atomic(db, run)
    logger.info(
        "support guest chat claimed",
        extra={"chat_id": str(chat.id), "owner_id": str(user.id), "moved": moved},
    )
    return moved


def names_account(chat: SupportGuestChat, user: User) -> bool:
    """The guest wrote this account's email or phone."""
    if chat.email and chat.email.lower() == (user.email or "").strip().lower():
        return True
    return bool(chat.phone) and chat.phone == (user.phone or "").strip()


def account_for_guest(db: Session, *, chat: SupportGuestChat) -> User | None:
    """The account behind the email the guest wrote, if there is one."""
    if not chat.email:
        return None
    return db.scalar(
        select(User).where(func.lower(User.email) == chat.email.lower()).limit(1)
    )


def _checked_guest(
    *, name: str, phone: str, email: str, email_required: bool = True
) -> dict[str, str]:
    problems: dict[str, str] = {}
    clean_name = " ".join(name.split())
    if len(clean_name) < 2:
        problems["name"] = "Ismingizni yozing."
    elif len(clean_name) > 120:
        problems["name"] = "Ism juda uzun."
    clean = ""
    try:
        clean = clean_phone(phone)
    except DomainError as exc:
        problems["phone"] = exc.message
    address = normalize_email(email)
    try:
        if address or email_required:
            _EMAIL.validate_python(address)
    except ValidationError:
        problems["email"] = (
            "Email manzilingizni yozing." if not address else "Email noto'g'ri."
        )
    if problems:
        raise InputRefused(problems)
    return {"name": clean_name, "phone": clean, "email": address}


def _checked_body(body: str) -> str:
    text = (body or "").strip()
    if not text:
        raise EmptyMessage
    if len(text) > MAX_BODY_CHARS:
        raise MessageTooLong(MAX_BODY_CHARS)
    return text


def _locked(db: Session, chat_id: uuid.UUID) -> SupportGuestChat:
    locked = db.scalar(
        select(SupportGuestChat)
        .where(SupportGuestChat.id == chat_id)
        .with_for_update(of=SupportGuestChat)
        .execution_options(populate_existing=True)
    )
    if locked is None:
        raise LookupError("support guest chat not found")
    return locked


def _append(
    db: Session,
    *,
    chat: SupportGuestChat,
    sender: User | None,
    text: str,
    now: datetime,
) -> SupportGuestMessage:
    by_guest = sender is None
    message = SupportGuestMessage(
        id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        chat_id=chat.id,
        from_guest=by_guest,
        sender_id=None if by_guest else sender.id,
        body=text,
    )
    db.add(message)
    chat.last_message_at = now
    if by_guest:
        chat.last_guest_at = now
        chat.guest_read_at = now
        on_commit(db, lambda: fire(GUEST_POSTED, message_id=message.id))
    else:
        chat.last_office_at = now
        chat.office_read_at = now
        on_commit(db, lambda: fire(GUEST_ANSWERED, message_id=message.id))
    db.flush()
    return message


def _later(a: datetime | None, b: datetime | None) -> datetime | None:
    return max(a, b) if a is not None and b is not None else a or b


def _merge_moments(conversation: SupportConversation, chat: SupportGuestChat) -> None:
    """The account's chat as if the guest's words had been written in it."""
    conversation.last_message_at = _later(
        conversation.last_message_at, chat.last_message_at
    )
    conversation.last_client_at = _later(
        conversation.last_client_at, chat.last_guest_at
    )
    conversation.last_office_at = _later(
        conversation.last_office_at, chat.last_office_at
    )
    conversation.client_read_at = _later(
        conversation.client_read_at, chat.guest_read_at
    )
    conversation.office_read_at = _later(
        conversation.office_read_at, chat.office_read_at
    )
    conversation.settled_at = _later(conversation.settled_at, chat.settled_at)
