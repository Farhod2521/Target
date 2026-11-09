"""What the support bot does when somebody writes to it.

The clients' bot for Support, beside the cabinet's chat: an owner's words
land in their support chat as if typed there (``source="support_bot"``),
files and voice notes included, and the office's replies come back here
(``support_bot_out``). Somebody the bot cannot tie to an owner writes into
a guest chat, words only.

Who an owner is, in this order: the chat this bot already tied to them; the
same Telegram linked to the main bot, or signing in with Telegram - a
private chat's id is the person's own, the same in every bot; and
``/start <code>`` from the cabinet's «Telegramda yozish». Owners only: a
CRM manager, or an account that is switched off, is a guest here.
"""

import io
import logging
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import UploadFile
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from starlette.datastructures import Headers
from telegramkit import (
    DOWNLOAD_MAX_BYTES,
    BotClient,
    ButtonPress,
    ChatMembership,
    Command,
    MediaMessage,
    OtherMessage,
    TelegramError,
    TextMessage,
    read_media,
    read_update,
)

from app.common.cache import cache
from app.common.exceptions import DomainError
from app.modules.accounts.constants import SocialProvider
from app.modules.accounts.models import SocialIdentity, User
from app.modules.notifications.bot import (
    support_bot,
    support_bot_configured,
    support_deep_link,
)
from app.modules.notifications.constants import (
    COMMAND_HELP,
    COMMAND_START,
    COMMAND_STOP,
    LINK_TOKEN_BYTES,
    LINK_TOKEN_TTL_SECONDS,
    PRIVATE_CHAT,
    SUPPORT_BOT_ACK_AFTER_SECONDS,
    SUPPORT_BOT_LINK_KEY,
    SUPPORT_BOT_SEEN_KEY,
    SUPPORT_BOT_SEEN_TTL_SECONDS,
)
from app.modules.notifications.exceptions import BotNotConfigured
from app.modules.notifications.models import SupportBotChat
from app.modules.notifications.selectors import chat_by_id, support_bot_chat_by_id
from app.modules.notifications.services.compose import escaped
from app.modules.notifications.services.send import answer
from app.modules.supportchat.constants import (
    STICKERS,
    MessageSource,
    RelayBot,
)
from app.modules.supportchat.drafts import Draft, Voice
from app.modules.supportchat.exceptions import GuestChatMoved
from app.modules.supportchat.models import SupportConversation
from app.modules.supportchat.selectors import relay_for
from app.modules.supportchat.services import (
    guest_writes,
    move_guest_chat,
    record_relay,
    start_bot_guest_chat,
    write_from_telegram,
)

logger = logging.getLogger(__name__)

# Telegram's own word for a file, and what the stored copy is called when
# Telegram sends no name of its own.
_FALLBACK_NAMES = {
    "photo": "rasm_{id}.jpg",
    "video": "video_{id}.mp4",
    "video_note": "video_{id}.mp4",
    "animation": "animatsiya_{id}.mp4",
    "voice": "ovoz_{id}.ogg",
    "audio": "audio_{id}.mp3",
    "document": "fayl_{id}",
}
_STICKER_CODES = {emoji: code for code, emoji, _name in STICKERS}


# -- the cabinet's link -------------------------------------------------------


def issue_support_link_token(*, owner: User) -> str:
    """A one-time code tying the Telegram that opens it to this owner."""
    if not support_bot_configured():
        raise BotNotConfigured
    token = secrets.token_urlsafe(LINK_TOKEN_BYTES)
    cache.set(
        SUPPORT_BOT_LINK_KEY.format(token=token), str(owner.id), LINK_TOKEN_TTL_SECONDS
    )
    return token


def support_link_url(*, owner: User) -> str:
    return support_deep_link(payload=issue_support_link_token(owner=owner))


def may_use_support_bot(user: User) -> bool:
    """The bot speaks to business owners: not a CRM manager, not an
    account that is switched off."""
    return user.is_active and user.crm_owner_id is None


# -- one delivery ---------------------------------------------------------------


def handle_support_update(
    db: Session, *, payload: dict[str, Any], now: datetime
) -> str:
    """One delivery from Telegram, acted on. Returns a word for the task log."""
    update_ = read_update(payload)
    if update_ is None or isinstance(update_, ChatMembership):
        return "ignored"
    # A private chat's id is the person's own; anything else is a group.
    if update_.chat_id != update_.sender.id:
        return "ignored"
    with support_bot() as client:
        if isinstance(update_, ButtonPress):
            answer(client=client, query_id=update_.query_id, text="Tushunarsiz tugma.")
            return "press"
        if isinstance(update_, Command):
            return _command(db, client=client, command=update_, now=now)
        if update_.chat_type != PRIVATE_CHAT:
            return "ignored"
        if not cache.add(
            SUPPORT_BOT_SEEN_KEY.format(
                chat_id=update_.chat_id, message_id=update_.message_id
            ),
            1,
            SUPPORT_BOT_SEEN_TTL_SECONDS,
        ):
            return "duplicate"
        row = _row(
            db,
            chat_id=update_.chat_id,
            username=update_.sender.username,
            name=update_.sender.name,
            now=now,
        )
        # Kept whatever the message meets: a refused one rolls back alone.
        db.commit()
        if isinstance(update_, TextMessage):
            return _text(db, client=client, row=row, message=update_, now=now)
        media = read_media(payload)
        if media is not None:
            return _media(db, client=client, row=row, media=media, now=now)
        return _unknown(client=client, message=update_)


def _command(db: Session, *, client: BotClient, command: Command, now: datetime) -> str:
    if command.name == COMMAND_STOP:
        row = support_bot_chat_by_id(db, chat_id=command.chat_id)
        if row is not None and row.is_active:
            row.is_active = False
            db.commit()
        _say(
            client=client,
            chat_id=command.chat_id,
            text=(
                "To'xtatildi. Javoblar endi faqat saytdagi chatda bo'ladi. "
                "Shu yerga yana yozsangiz, bot qayta ishlaydi."
            ),
        )
        return "stopped"
    if command.name == COMMAND_START and command.argument:
        return _link(db, client=client, command=command, now=now)
    row = _row(
        db,
        chat_id=command.chat_id,
        username=command.sender.username,
        name=command.sender.name,
        now=now,
    )
    db.commit()
    if command.name == COMMAND_HELP:
        _say(client=client, chat_id=command.chat_id, text=_help(row))
        return "help"
    _say(client=client, chat_id=command.chat_id, text=_hello(row))
    return "hello"


def _link(db: Session, *, client: BotClient, command: Command, now: datetime) -> str:
    """``/start <code>``: the cabinet vouches for this Telegram."""
    key = SUPPORT_BOT_LINK_KEY.format(token=command.argument)
    owner_id = cache.get(key)
    owner = _user(db, owner_id)
    if owner is None or not may_use_support_bot(owner):
        _say(
            client=client,
            chat_id=command.chat_id,
            text="Havola eskirgan. Kabinetdagi «Telegramda yozish» tugmasini qayta bosing.",
        )
        return "refused"
    cache.delete(key)
    row = _row(
        db,
        chat_id=command.chat_id,
        username=command.sender.username,
        name=command.sender.name,
        now=now,
        vouched=owner,
    )
    db.commit()
    _say(client=client, chat_id=command.chat_id, text=_hello(row))
    return "linked"


# -- who is writing -------------------------------------------------------------


def _row(
    db: Session,
    *,
    chat_id: str,
    username: str,
    name: str,
    now: datetime,
    vouched: User | None = None,
) -> SupportBotChat:
    """This Telegram chat's row, written now if new, tied to its owner when
    one is known. ``vouched`` is the owner a cabinet code named."""
    row = support_bot_chat_by_id(db, chat_id=chat_id)
    if row is None:
        row = SupportBotChat(chat_id=chat_id, is_active=False)
        db.add(row)
    was_live = row.is_active
    current = row.owner if row.owner_id else None
    if current is not None and not may_use_support_bot(current):
        # The relationship too: sessions keep objects across commits here,
        # and a stale one would go on writing as the switched-off account.
        row.owner_id = None
        row.owner = None
        current = None
    owner = vouched or current or _recognised(db, chat_id=chat_id)
    # Coming back after /stop counts as tying again: the owner may have
    # linked another Telegram since, and only one of them gets replies.
    if owner is not None and (
        owner.id != row.owner_id or row.linked_at is None or not was_live
    ):
        _tie(db, row=row, owner=owner, now=now)
    row.username = username[:64]
    row.name = name[:120]
    row.is_active = True
    row.last_error = ""
    row.last_error_at = None
    db.flush()
    return row


def _recognised(db: Session, *, chat_id: str) -> User | None:
    """The owner this Telegram already proved itself as elsewhere."""
    linked = chat_by_id(db, chat_id=chat_id)
    if linked is not None and linked.is_active and may_use_support_bot(linked.owner):
        return linked.owner
    identity = db.scalar(
        select(SocialIdentity).where(
            SocialIdentity.provider == SocialProvider.TELEGRAM,
            SocialIdentity.subject == chat_id,
        )
    )
    if identity is None:
        return None
    user = db.get(User, identity.owner_id)
    return user if user is not None and may_use_support_bot(user) else None


def _tie(db: Session, *, row: SupportBotChat, owner: User, now: datetime) -> None:
    """The row writes as ``owner`` from now on; any other Telegram of theirs
    stops getting replies, and a guest chat opened here moves into theirs."""
    db.execute(
        update(SupportBotChat)
        .where(
            SupportBotChat.owner_id == owner.id,
            SupportBotChat.is_active.is_(True),
            SupportBotChat.chat_id != row.chat_id,
        )
        .values(is_active=False, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    row.owner_id = owner.id
    row.owner = owner
    row.linked_at = now
    db.flush()
    guest = row.guest_chat
    if guest is not None and guest.claimed_at is None:
        move_guest_chat(db, chat=guest, user=owner, now=now)
    logger.info(
        "support_bot_linked", extra={"owner": str(owner.id), "chat": row.chat_id}
    )


def _user(db: Session, owner_id: object) -> User | None:
    if not owner_id:
        return None
    try:
        return db.get(User, uuid.UUID(str(owner_id)))
    except ValueError:
        return None


# -- words and files --------------------------------------------------------------


def _text(
    db: Session,
    *,
    client: BotClient,
    row: SupportBotChat,
    message: TextMessage,
    now: datetime,
) -> str:
    if row.owner is None:
        return _guest_text(db, client=client, row=row, body=message.text, now=now)
    draft = Draft(
        body=message.text,
        reply_to=_answered(db, row=row, telegram_id=message.reply_to_message_id),
        source=MessageSource.SUPPORT_BOT,
    )
    return _store(
        db, client=client, row=row, draft=draft, message_id=message.message_id, now=now
    )


def _media(
    db: Session,
    *,
    client: BotClient,
    row: SupportBotChat,
    media: MediaMessage,
    now: datetime,
) -> str:
    if row.owner is None:
        if media.caption:
            return _guest_text(db, client=client, row=row, body=media.caption, now=now)
        _say(
            client=client,
            chat_id=row.chat_id,
            text=(
                "Fayl yuborish uchun hisobingizni ulang: kabinetdagi Yordam "
                "oynasida «Telegramda yozish» tugmasini bosing. Hozircha "
                "savolingizni matn bilan yozing."
            ),
            reply_to=media.message_id,
        )
        return "guest_file"
    reply_to = _answered(db, row=row, telegram_id=media.reply_to_message_id)
    if media.kind == "sticker":
        code = _STICKER_CODES.get(media.emoji, "")
        draft = (
            Draft(sticker=code, reply_to=reply_to, source=MessageSource.SUPPORT_BOT)
            if code
            else Draft(
                body=media.emoji or "🙂",
                reply_to=reply_to,
                source=MessageSource.SUPPORT_BOT,
            )
        )
        return _store(
            db,
            client=client,
            row=row,
            draft=draft,
            message_id=media.message_id,
            now=now,
        )
    if media.size > DOWNLOAD_MAX_BYTES:
        _say(
            client=client,
            chat_id=row.chat_id,
            text=(
                "Fayl 20 MB dan katta - Telegram uni botga bermaydi. Saytdagi "
                "chatdan yuboring yoki havolasini yozing."
            ),
            reply_to=media.message_id,
        )
        return "too_large"
    upload = _download(client=client, media=media)
    if upload is None:
        _say(
            client=client,
            chat_id=row.chat_id,
            text="Faylni ololmadim. Birozdan keyin qayta yuboring.",
            reply_to=media.message_id,
        )
        return "download_failed"
    if media.kind in ("voice", "audio"):
        draft = Draft(
            voice=Voice(upload=upload, seconds=max(1, media.seconds)),
            reply_to=reply_to,
            source=MessageSource.SUPPORT_BOT,
        )
        stored = _store(
            db,
            client=client,
            row=row,
            draft=draft,
            message_id=media.message_id,
            now=now,
        )
        # A voice note stands alone; words under it go as a message of their own.
        if media.caption and stored == "sent":
            _store(
                db,
                client=client,
                row=row,
                draft=Draft(body=media.caption, source=MessageSource.SUPPORT_BOT),
                message_id=media.message_id,
                now=now,
                quiet=True,
            )
        return stored
    draft = Draft(
        body=media.caption,
        files=(upload,),
        reply_to=reply_to,
        source=MessageSource.SUPPORT_BOT,
    )
    return _store(
        db, client=client, row=row, draft=draft, message_id=media.message_id, now=now
    )


def _download(*, client: BotClient, media: MediaMessage) -> UploadFile | None:
    """The file, as the cabinet's upload would have carried it."""
    try:
        found = client.get_file(file_id=media.file_id)
        content = client.download_file(path=found.path) if found.path else b""
    except TelegramError as exc:
        logger.warning("support_bot_download_failed", extra={"reason": str(exc)})
        return None
    if not content:
        return None
    name = media.file_name or _FALLBACK_NAMES.get(media.kind, "fayl_{id}").format(
        id=media.message_id
    )
    if "." not in name and media.mime == "application/pdf":
        name += ".pdf"
    headers = Headers({"content-type": media.mime}) if media.mime else None
    return UploadFile(
        file=io.BytesIO(content),
        filename=name[:255],
        size=len(content),
        headers=headers,
    )


def _store(
    db: Session,
    *,
    client: BotClient,
    row: SupportBotChat,
    draft: Draft,
    message_id: int,
    now: datetime,
    quiet: bool = False,
) -> str:
    """Into the owner's chat as the owner, tied to the Telegram message so a
    reply quoting it finds it. A refusal is said in its own words."""
    owner = row.owner
    if owner is None:  # pragma: no cover - callers route guests elsewhere
        return "guest"
    before = db.scalar(
        select(SupportConversation).where(SupportConversation.owner_id == owner.id)
    )
    quiet_since = _quiet_since(before, now=now)
    try:
        stored = write_from_telegram(db, owner=owner, draft=draft, now=now)
    except DomainError as exc:
        db.rollback()
        _say(client=client, chat_id=row.chat_id, text=exc.message, reply_to=message_id)
        return "refused"
    record_relay(
        db,
        message=stored,
        chat_id=row.chat_id,
        telegram_message_id=message_id,
        bot=RelayBot.SUPPORT,
    )
    if quiet_since and not quiet:
        _say(
            client=client,
            chat_id=row.chat_id,
            text=(
                "Qabul qilindi. Yordam xizmati javobini shu yerga yozadi - "
                "saytdagi chatda ham ko'rinadi."
            ),
            reply_to=message_id,
        )
    return "sent"


def _quiet_since(conversation: SupportConversation | None, *, now: datetime) -> bool:
    """Whether the client's last word here is old, or there is none: the
    first words of a new question are told they arrived, the rest are not."""
    if conversation is None or conversation.last_client_at is None:
        return True
    return now - conversation.last_client_at > timedelta(
        seconds=SUPPORT_BOT_ACK_AFTER_SECONDS
    )


def _answered(db: Session, *, row: SupportBotChat, telegram_id: int) -> str:
    """The support message a Telegram reply quotes, when it is one this
    owner's chat holds and still shows; otherwise nothing is quoted."""
    if not telegram_id or row.owner_id is None:
        return ""
    relay = relay_for(
        db, chat_id=row.chat_id, telegram_message_id=telegram_id, bot=RelayBot.SUPPORT
    )
    if relay is None or relay.owner_id != row.owner_id:
        return ""
    if relay.message.deleted_at is not None:
        return ""
    return str(relay.message_id)


def _guest_text(
    db: Session, *, client: BotClient, row: SupportBotChat, body: str, now: datetime
) -> str:
    """A stranger's words, into the guest chat this Telegram opened."""
    first = row.guest_chat is None or row.guest_chat.claimed_at is not None
    try:
        if not first:
            guest_writes(db, chat=row.guest_chat, body=body, now=now)
        else:
            chat = start_bot_guest_chat(
                db, name=row.name or row.username, body=body, now=now
            )
            row.guest_chat_id = chat.id
            row.guest_chat = chat
            db.commit()
    except GuestChatMoved:
        db.rollback()
        chat = start_bot_guest_chat(
            db, name=row.name or row.username, body=body, now=now
        )
        row.guest_chat_id = chat.id
        row.guest_chat = chat
        db.commit()
        first = True
    except DomainError as exc:
        db.rollback()
        _say(client=client, chat_id=row.chat_id, text=exc.message)
        return "refused"
    if first:
        _say(
            client=client,
            chat_id=row.chat_id,
            text=(
                "Xabaringiz yordam xizmatiga yuborildi, javob shu yerga keladi. "
                "TargetologAI kabinetingiz bo'lsa, uni ulang: kabinetdagi Yordam "
                "oynasida «Telegramda yozish» tugmasini bosing."
            ),
        )
    return "guest_sent"


def _unknown(*, client: BotClient, message: OtherMessage | TextMessage) -> str:
    _say(
        client=client,
        chat_id=message.chat_id,
        text="Bu turdagi xabarni yubora olmayman. Matn, rasm, fayl yoki ovozli xabar yuboring.",
        reply_to=message.message_id,
    )
    return "unknown"


# -- words of the bot's own ------------------------------------------------------


def _hello(row: SupportBotChat) -> str:
    if row.owner is not None:
        name = row.owner.full_name or row.name
        greeting = f"Salom, {name}!" if name else "Salom!"
        return (
            f"{greeting} Bu TargetologAI yordam xizmati. Savolingizni yozing - "
            "matn, rasm, fayl yoki ovozli xabar. Javob shu yerga keladi va "
            "saytdagi chatda ham ko'rinadi."
        )
    return (
        "Salom! Bu TargetologAI yordam xizmati. Savolingizni yozing - javob "
        "shu yerga keladi.\n\nKabinetingiz bo'lsa, uni ulang: kabinetdagi "
        "Yordam oynasida «Telegramda yozish» tugmasini bosing. Shunda rasm va "
        "fayl ham yubora olasiz."
    )


def _help(row: SupportBotChat) -> str:
    linked = (
        "Hisobingiz ulangan: xabarlaringiz saytdagi chatingizga tushadi."
        if row.owner is not None
        else "Hisob ulanmagan: hozircha faqat matn yuboriladi."
    )
    return (
        f"{linked}\n\nSavolingizni yozing - yordam xizmati shu yerda javob "
        "beradi. Javobga javob yozish uchun uning ustiga «Reply» qiling.\n"
        "/stop - javoblarni botga yubormaslik."
    )


def _say(*, client: BotClient, chat_id: str, text: str, reply_to: int = 0) -> None:
    try:
        client.send_message(chat_id=chat_id, text=escaped(text), reply_to=reply_to)
    except TelegramError as exc:
        logger.info("support_bot_say_failed", extra={"reason": str(exc)})


__all__ = [
    "handle_support_update",
    "issue_support_link_token",
    "may_use_support_bot",
    "support_link_url",
]
