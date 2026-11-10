"""Leads posted to a Telegram group or channel by the customer bot.

The cabinet's button issues a token for one page and ad account pair and
opens the bot on ``/start lc_<token>``. The bot answers with two buttons:
one adds it to a group (``startgroup`` carries the token there), the other
makes it a channel's administrator (``startchannel`` carries nothing, so
the person who did it - ``my_chat_member``'s sender - finds the token they
opened last). Chats the owner already linked come as buttons too, since
several pairs may share one. A public group or channel is refused: a lead
carries a telephone number.

From then on every lead of the pair - the same leads the pair's CRM takes -
is posted there once, from the moment of linking. A lead is claimed in
``lead_deliveries`` before it is sent, so two workers never post it twice;
a send Telegram put off gives the claim back and tries again later, and a
sweep posts what a lost task left behind. The bot removed, its rights taken
or the chat gone stops the chat and tells the owner, in the bot and on the
page.
"""

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape

from sqlalchemy import ColumnElement, and_, delete, exists, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from telegramkit import (
    BotBlocked,
    BotClient,
    Button,
    ButtonPress,
    ChatMembership,
    ChatMigrated,
    ChatUnreachable,
    Command,
    TelegramAPIError,
    TelegramError,
    TelegramRateLimited,
    TelegramTemporaryError,
)

from app.common.cache import cache
from app.common.config import settings
from app.common.dates import localtime
from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.destinations.constants import (
    CHANNEL_CHAT_TYPE,
    GROUP_CHAT_TYPES,
    LEAD_CHAT_BROKEN_LABELS,
    LEAD_CHAT_CHECK_SECONDS,
    LEAD_CHAT_CHECKS_PER_RUN,
    LEAD_CHAT_KIND_LABELS,
    LEAD_CHAT_PAYLOAD,
    LEAD_CHAT_PRESS,
    LEAD_CHAT_TOKEN_BYTES,
    LEAD_CHAT_TOKEN_KEY,
    LEAD_CHAT_TOKEN_TTL_SECONDS,
    LEAD_CHAT_WAITING_KEY,
    LEAD_POST_ANSWER_CHARS,
    LEAD_POST_BACKOFF_SECONDS,
    LEAD_POST_MESSAGE_REFUSALS,
    LEAD_POST_QUESTION_CHARS,
    LEAD_POST_STALE_SECONDS,
    LEAD_POST_SWEEP_HOURS,
    LEAD_POST_SWEEP_LIMIT,
    LEAD_POST_TEXT_CHARS,
    Channel,
    DeliveryStatus,
    LeadChatBroken,
    LeadChatKind,
    LeadChatStatus,
)
from app.modules.destinations.exceptions import LeadChatPairUnknown, NoLeadChat
from app.modules.destinations.models import LeadChat, LeadChatPair, LeadDelivery
from app.modules.integrations.selectors import Pair, page_pairs
from app.modules.leads.models import Lead
from app.modules.notifications.bot import bot, deep_link, is_configured
from app.modules.notifications.exceptions import BotNotConfigured

logger = logging.getLogger(__name__)


def escaped(value: str) -> str:
    """Telegram HTML-safe text. Not imported from notifications.services: that
    package imports respond, which imports this module, and a worker that
    loads destinations first would stop on the cycle."""
    return escape(value, quote=False)


START_GROUP = "https://t.me/{username}?startgroup={payload}"
START_CHANNEL = "https://t.me/{username}?startchannel&admin=post_messages"
# A press names a linked chat by its row: "lc:" and 32 hex digits.
SHOWN_CHATS = 6


@dataclass(frozen=True, slots=True)
class Target:
    """The chat a lead is about to be linked to, as Telegram described it."""

    chat_id: str
    kind: str
    title: str
    public: bool
    can_post: bool


# -- the cabinet's side --------------------------------------------------


def find_pair(db: Session, *, owner: User, key: str) -> Pair:
    found = next((p for p in page_pairs(db, owner=owner) if p.key == key), None)
    if found is None:
        raise LeadChatPairUnknown
    return found


def issue_lead_chat_link(db: Session, *, owner: User, pair_key: str) -> str:
    """The bot link the cabinet's «Telegramga uzatish» opens."""
    if not is_configured():
        raise BotNotConfigured
    pair = find_pair(db, owner=owner, key=pair_key)
    token = secrets.token_urlsafe(LEAD_CHAT_TOKEN_BYTES)
    cache.set(
        LEAD_CHAT_TOKEN_KEY.format(token=token),
        f"{owner.id}|{pair.key}",
        LEAD_CHAT_TOKEN_TTL_SECONDS,
    )
    return deep_link(payload=LEAD_CHAT_PAYLOAD + token)


def unlink_pair(db: Session, *, owner: User, pair_key: str) -> None:
    """The pair's leads stop going to Telegram; the chat stays for others."""
    pair = find_pair(db, owner=owner, key=pair_key)
    db.execute(
        delete(LeadChatPair).where(
            LeadChatPair.owner_id == owner.id,
            LeadChatPair.page_id == pair.page.id,
            LeadChatPair.ad_account_id == pair.account.id,
        )
    )
    db.commit()


def drop_lead_chat(db: Session, *, owner: User, chat_pk: str) -> None:
    """Forget a chat and every pair sent there; the bot leaves it."""
    row = _owned_chat(db, owner=owner, chat_pk=chat_pk)
    if row is None:
        raise NoLeadChat
    chat_id = row.chat_id
    db.delete(row)
    db.commit()
    still_used = db.scalar(select(exists().where(LeadChat.chat_id == chat_id)))
    if still_used or not is_configured():
        return
    try:
        with bot() as client:
            client.leave_chat(chat_id=chat_id)
    except TelegramError as exc:
        logger.info("lead_chat_leave_failed", extra={"reason": str(exc)})


def _owned_chat(db: Session, *, owner: User, chat_pk: str) -> LeadChat | None:
    try:
        pk = uuid.UUID(chat_pk)
    except ValueError:
        return None
    return db.scalar(
        select(LeadChat).where(LeadChat.id == pk, LeadChat.owner_id == owner.id)
    )


# -- the bot's side ------------------------------------------------------


def is_lead_chat_start(argument: str) -> bool:
    return argument.startswith(LEAD_CHAT_PAYLOAD)


def is_lead_chat_press(data: str) -> bool:
    return data.startswith(LEAD_CHAT_PRESS)


def offer_lead_chat(db: Session, *, client: BotClient, command: Command) -> str:
    """``/start lc_<token>`` in a private chat: group or channel?"""
    token = command.argument.removeprefix(LEAD_CHAT_PAYLOAD)
    found = _read_token(db, token)
    if found is None:
        _say(client, command.chat_id, _EXPIRED)
        return "lead_chat_expired"
    owner, pair = found
    cache.set(
        LEAD_CHAT_WAITING_KEY.format(user=command.sender.id),
        token,
        LEAD_CHAT_TOKEN_TTL_SECONDS,
    )
    username = settings.telegram_bot_username
    buttons = [
        Button(
            text="Guruhga",
            url=START_GROUP.format(
                username=username, payload=LEAD_CHAT_PAYLOAD + token
            ),
        ),
        Button(text="Kanalga", url=START_CHANNEL.format(username=username)),
    ]
    linked = list(
        db.scalars(
            select(LeadChat)
            .where(
                LeadChat.owner_id == owner.id,
                LeadChat.status == LeadChatStatus.ACTIVE,
            )
            .order_by(LeadChat.linked_at.desc())
            .limit(SHOWN_CHATS)
        )
    )
    buttons += [
        Button(
            text=f"{LEAD_CHAT_KIND_LABELS.get(LeadChatKind(row.kind), '')}: {row.title}"[
                :60
            ],
            data=LEAD_CHAT_PRESS + row.id.hex,
            row="own",
        )
        for row in linked
    ]
    text = (
        f"<b>{escaped(_pair_label(pair))}</b> lidlari qayerga tushsin?\n\n"
        "Guruh yoki kanal yopiq (private) bo'lishi kerak: lidda telefon raqam bor."
    )
    if any(button.data for button in buttons):
        text += "\n\nYoki ulangan guruh/kanallardan birini tanlang."
    try:
        client.send_message(chat_id=command.chat_id, text=text, buttons=tuple(buttons))
    except TelegramError as exc:
        logger.info("lead_chat_offer_failed", extra={"reason": str(exc)})
    return "lead_chat_offered"


def lead_chat_group_start(
    db: Session, *, client: BotClient, command: Command, now: datetime
) -> str:
    """``/start lc_<token>`` inside a group: the group's ``startgroup`` link,
    also when the bot was in it already."""
    token = command.argument.removeprefix(LEAD_CHAT_PAYLOAD)
    try:
        info = client.get_chat(chat_id=command.chat_id)
    except TelegramError as exc:
        logger.info("lead_chat_get_chat_failed", extra={"reason": str(exc)})
        return "lead_chat_unreadable"
    target = Target(
        chat_id=command.chat_id,
        kind=LeadChatKind.GROUP,
        title=info.title,
        public=info.public,
        can_post=True,
    )
    return _link(
        db, client=client, token=token, target=target, adder=command.sender.id, now=now
    )


def handle_lead_chat_press(
    db: Session, *, client: BotClient, press: ButtonPress, now: datetime
) -> str:
    """A chat already linked, chosen for one more pair."""
    _answer(client, press.query_id)
    token = cache.get(LEAD_CHAT_WAITING_KEY.format(user=press.sender.id))
    found = _read_token(db, str(token or ""))
    if found is None:
        _say(client, press.chat_id, _EXPIRED)
        return "lead_chat_expired"
    owner, _pair = found
    row = _owned_chat(db, owner=owner, chat_pk=_hex_uuid(press.data))
    if row is None or row.status != LeadChatStatus.ACTIVE:
        _say(
            client,
            press.chat_id,
            "Bu guruh yoki kanal endi ulanmagan. Qaytadan tanlang.",
        )
        return "lead_chat_gone"
    try:
        info = client.get_chat(chat_id=row.chat_id)
    except TelegramError:
        _say(
            client,
            press.chat_id,
            "Bot bu guruh yoki kanalni ko'ra olmayapti. Qaytadan qo'shing.",
        )
        return "lead_chat_unreadable"
    target = Target(
        chat_id=row.chat_id,
        kind=row.kind,
        title=info.title or row.title,
        public=info.public,
        can_post=True,
    )
    return _link(
        db,
        client=client,
        token=str(token),
        target=target,
        adder=press.sender.id,
        now=now,
    )


def handle_membership(
    db: Session, *, client: BotClient, change: ChatMembership, now: datetime
) -> str:
    """The bot added to, changed in or removed from a group or a channel."""
    if change.chat_type in GROUP_CHAT_TYPES:
        kind, can_post = LeadChatKind.GROUP, change.present
    elif change.chat_type == CHANNEL_CHAT_TYPE:
        kind, can_post = LeadChatKind.CHANNEL, change.present and change.can_post
    else:
        return "ignored"
    if not change.present:
        return _break_everywhere(
            db,
            client=client,
            chat_id=change.chat_id,
            reason=LeadChatBroken.REMOVED,
            now=now,
        )
    token = cache.get(LEAD_CHAT_WAITING_KEY.format(user=change.sender.id))
    if token:
        target = Target(
            chat_id=change.chat_id,
            kind=kind,
            title=change.title,
            public=change.public,
            can_post=can_post,
        )
        return _link(
            db,
            client=client,
            token=str(token),
            target=target,
            adder=change.sender.id,
            now=now,
        )
    if not can_post:
        return _break_everywhere(
            db,
            client=client,
            chat_id=change.chat_id,
            reason=LeadChatBroken.RIGHTS,
            now=now,
        )
    if change.public:
        return _break_everywhere(
            db,
            client=client,
            chat_id=change.chat_id,
            reason=LeadChatBroken.PUBLIC,
            now=now,
        )
    return _mend_everywhere(
        db, client=client, chat_id=change.chat_id, title=change.title, now=now
    )


def _link(
    db: Session,
    *,
    client: BotClient,
    token: str,
    target: Target,
    adder: str,
    now: datetime,
) -> str:
    found = _read_token(db, token)
    if found is None:
        if target.kind != LeadChatKind.GROUP:
            _say(client, adder, _EXPIRED)
        return "lead_chat_expired"
    owner, pair = found
    if target.public:
        _say(
            client,
            adder,
            f"«{target.title}» ochiq (public). Lidlarda telefon raqam bor, shuning uchun "
            "faqat yopiq (private) guruh yoki kanal ulanadi. Bot u yerdan chiqdi.",
        )
        _leave(client, target.chat_id)
        # Anybody in an open group has read the link's token: it links nothing more.
        cache.delete(LEAD_CHAT_TOKEN_KEY.format(token=token))
        cache.delete(LEAD_CHAT_WAITING_KEY.format(user=adder))
        return "lead_chat_public"
    if not target.can_post:
        _say(
            client,
            adder,
            f"«{target.title}» kanalida botga «Xabar joylash» huquqini bering - "
            "shunda ulanadi.",
        )
        return "lead_chat_no_rights"
    row = db.scalar(
        select(LeadChat)
        .where(LeadChat.owner_id == owner.id, LeadChat.chat_id == target.chat_id)
        .with_for_update()
    )
    if row is None:
        row = LeadChat(
            owner_id=owner.id,
            chat_id=target.chat_id,
            kind=target.kind,
            status=LeadChatStatus.ACTIVE,
            linked_at=now,
        )
        db.add(row)
    row.kind = target.kind
    row.title = target.title[:255]
    if row.status != LeadChatStatus.ACTIVE:
        row.linked_at = now
    row.status = LeadChatStatus.ACTIVE
    row.broken_reason = ""
    row.broken_at = None
    row.last_error = ""
    row.checked_at = now
    db.flush()
    seat = db.scalar(
        select(LeadChatPair)
        .where(
            LeadChatPair.page_id == pair.page.id,
            LeadChatPair.ad_account_id == pair.account.id,
        )
        .with_for_update(of=LeadChatPair)
    )
    if seat is None:
        db.add(
            LeadChatPair(
                owner_id=owner.id,
                lead_chat_id=row.id,
                page_id=pair.page.id,
                ad_account_id=pair.account.id,
                linked_at=now,
            )
        )
    elif seat.lead_chat_id != row.id:
        seat.lead_chat_id = row.id
        seat.linked_at = now
    db.commit()
    cache.delete(LEAD_CHAT_TOKEN_KEY.format(token=token))
    cache.delete(LEAD_CHAT_WAITING_KEY.format(user=adder))
    label = _pair_label(pair)
    try:
        client.send_message(
            chat_id=target.chat_id,
            text=f"Bu yerga <b>{escaped(label)}</b> lidlari tushadi.",
        )
    except TelegramError as exc:
        logger.info("lead_chat_hello_failed", extra={"reason": str(exc)})
    _say(
        client,
        adder,
        f"Ulandi: «{target.title}». {label} lidlari endi shu yerga tushadi.",
    )
    return "lead_chat_linked"


def _break_everywhere(
    db: Session, *, client: BotClient | None, chat_id: str, reason: str, now: datetime
) -> str:
    rows = list(
        db.scalars(
            select(LeadChat).where(
                LeadChat.chat_id == chat_id,
                LeadChat.status == LeadChatStatus.ACTIVE,
            )
        )
    )
    for row in rows:
        _break(db, row=row, reason=reason, error="", now=now)
    db.commit()
    for row in rows:
        _tell_owner_broken(db, client=client, row=row, now=now)
    return "lead_chat_broken" if rows else "ignored"


def _mend_everywhere(
    db: Session, *, client: BotClient, chat_id: str, title: str, now: datetime
) -> str:
    """The bot back in a chat it was removed from: posting starts again."""
    rows = list(
        db.scalars(
            select(LeadChat).where(
                LeadChat.chat_id == chat_id,
                LeadChat.status == LeadChatStatus.BROKEN,
            )
        )
    )
    for row in rows:
        row.status = LeadChatStatus.ACTIVE
        row.broken_reason = ""
        row.broken_at = None
        row.last_error = ""
        row.title = (title or row.title)[:255]
    db.commit()
    return "lead_chat_mended" if rows else "ignored"


def _break(
    db: Session, *, row: LeadChat, reason: str, error: str, now: datetime
) -> None:
    row.status = LeadChatStatus.BROKEN
    row.broken_reason = reason
    row.broken_at = now
    row.last_error = error[:255]


def _tell_owner_broken(
    db: Session, *, client: BotClient | None, row: LeadChat, now: datetime
) -> None:
    """In the owner's own chat with the bot, when there is one."""
    from app.modules.notifications.selectors import chat_for
    from app.modules.notifications.services.send import send_to

    chat = chat_for(db, owner=row.owner)
    if chat is None:
        return
    reason = LEAD_CHAT_BROKEN_LABELS.get(LeadChatBroken(row.broken_reason), "")
    text = escaped(
        f"Lidlar «{row.title}» ga tushmay qoldi: {reason}. Kabinetda "
        "«Telegramga uzatish» orqali qaytadan ulang."
    )
    try:
        if client is not None:
            send_to(db, client=client, chat=chat, text=text, now=now)
        else:
            with bot() as opened:
                send_to(db, client=opened, chat=chat, text=text, now=now)
        db.commit()
    except (BotNotConfigured, TelegramError) as exc:
        logger.info("lead_chat_notice_failed", extra={"reason": str(exc)})


def _read_token(db: Session, token: str) -> tuple[User, Pair] | None:
    if not token:
        return None
    stored = cache.get(LEAD_CHAT_TOKEN_KEY.format(token=token))
    if not stored:
        return None
    owner_id, _, key = str(stored).partition("|")
    try:
        owner = db.get(User, uuid.UUID(owner_id))
    except ValueError:
        return None
    if owner is None:
        return None
    pair = next((p for p in page_pairs(db, owner=owner) if p.key == key), None)
    return (owner, pair) if pair is not None else None


def _pair_label(pair: Pair) -> str:
    return f"{pair.page.name or pair.page.external_id} · {pair.account.name or pair.account.external_id}"


def _hex_uuid(data: str) -> str:
    return data.removeprefix(LEAD_CHAT_PRESS)


def _say(client: BotClient, chat_id: str, text: str) -> None:
    try:
        client.send_message(chat_id=chat_id, text=escaped(text))
    except TelegramError as exc:
        logger.info("lead_chat_reply_failed", extra={"reason": str(exc)})


def _answer(client: BotClient, query_id: str) -> None:
    try:
        client.answer_callback_query(query_id=query_id)
    except TelegramError as exc:
        logger.info("lead_chat_answer_failed", extra={"reason": str(exc)})


def _leave(client: BotClient, chat_id: str) -> None:
    try:
        client.leave_chat(chat_id=chat_id)
    except TelegramError as exc:
        logger.info("lead_chat_leave_failed", extra={"reason": str(exc)})


_EXPIRED = "Havola eskirgan. Kabinetda «Telegramga uzatish» tugmasini qaytadan bosing."


# -- posting ---------------------------------------------------------------


def queue_lead_post(db: Session, *, lead_id: str) -> None:
    from app.modules.destinations.tasks import post_lead_task

    on_commit(db, lambda: post_lead_task.delay(lead_id))


def post_lead(db: Session, *, lead_id: str, now: datetime) -> str | int:
    """Post one lead to its pair's chat. Returns a word for the task log,
    or the seconds to wait before trying again."""
    from app.modules.crm.selectors import pair_of_lead

    try:
        lead = db.get(Lead, uuid.UUID(lead_id))
    except ValueError:
        return "skipped"
    if lead is None or lead.is_test or lead.is_organic or not is_configured():
        return "skipped"
    owner = db.get(User, lead.owner_id)
    if owner is None:
        return "skipped"
    pair = pair_of_lead(db, owner=owner, lead_id=lead.id)
    if pair is None:
        return "skipped"
    seat = db.scalar(
        select(LeadChatPair).where(
            LeadChatPair.page_id == pair.page.id,
            LeadChatPair.ad_account_id == pair.account.id,
        )
    )
    if seat is None or seat.lead_chat.status != LeadChatStatus.ACTIVE:
        return "skipped"
    if lead.received_at < seat.linked_at:
        return "skipped"
    if not _claim(db, owner_id=owner.id, lead_id=lead.id, now=now):
        return "already"
    chat = seat.lead_chat
    try:
        text, buttons = compose_lead(db, lead=lead, pair=pair)
        with bot() as client:
            client.send_message(chat_id=chat.chat_id, text=text, buttons=buttons)
    except ChatMigrated as exc:
        _release(db, lead_id=lead.id)
        _migrate(db, old=chat.chat_id, new=exc.migrate_to_chat_id, now=now)
        return 0
    except TelegramRateLimited as exc:
        _release(db, lead_id=lead.id)
        return int(exc.retry_after or LEAD_POST_BACKOFF_SECONDS)
    except TelegramTemporaryError:
        _release(db, lead_id=lead.id)
        return LEAD_POST_BACKOFF_SECONDS
    except (BotBlocked, ChatUnreachable, TelegramAPIError) as exc:
        if _refuses_the_message(exc):
            _set_delivery(db, lead_id=lead.id, status=DeliveryStatus.FAILED, now=now)
            logger.warning("lead %s not posted to %s: %s", lead.id, chat.chat_id, exc)
            return "failed"
        _release(db, lead_id=lead.id)
        reason = _reason(exc)
        rows = list(
            db.scalars(
                select(LeadChat).where(
                    LeadChat.chat_id == chat.chat_id,
                    LeadChat.status == LeadChatStatus.ACTIVE,
                )
            )
        )
        for row in rows:
            _break(db, row=row, reason=reason, error=str(exc), now=now)
        db.commit()
        for row in rows:
            _tell_owner_broken(db, client=None, row=row, now=now)
        return "broken"
    except Exception:
        db.rollback()
        _release(db, lead_id=lead.id)
        raise
    _set_delivery(db, lead_id=lead.id, status=DeliveryStatus.DELIVERED, now=now)
    return "posted"


def _refuses_the_message(exc: TelegramError) -> bool:
    """Telegram refused this message, not the chat: the next lead still goes."""
    if isinstance(exc, (BotBlocked, ChatUnreachable)):
        return False
    lowered = str(exc).lower()
    return any(words in lowered for words in LEAD_POST_MESSAGE_REFUSALS)


def _set_delivery(
    db: Session, *, lead_id: uuid.UUID, status: str, now: datetime
) -> None:
    delivered = now if status == DeliveryStatus.DELIVERED else None
    db.execute(
        update(LeadDelivery)
        .where(_telegram_delivery(lead_id))
        .values(status=status, delivered_at=delivered, updated_at=now)
    )
    db.commit()


def _migrate(db: Session, *, old: str, new: str, now: datetime) -> None:
    """A group became a supergroup: its rows follow it to the new id. An
    owner who already linked the supergroup keeps that row, and the pairs
    of the old one move onto it."""
    for row in list(db.scalars(select(LeadChat).where(LeadChat.chat_id == old))):
        kept = db.scalar(
            select(LeadChat).where(
                LeadChat.owner_id == row.owner_id, LeadChat.chat_id == new
            )
        )
        if kept is None:
            row.chat_id = new
            row.updated_at = now
            continue
        db.execute(
            update(LeadChatPair)
            .where(LeadChatPair.lead_chat_id == row.id)
            .values(lead_chat_id=kept.id)
        )
        db.delete(row)
    db.commit()


def _reason(exc: TelegramError) -> str:
    if isinstance(exc, ChatUnreachable):
        return LeadChatBroken.GONE
    if isinstance(exc, BotBlocked):
        return LeadChatBroken.REMOVED
    lowered = str(exc).lower()
    if "rights" in lowered or "not a member" in lowered or "administrator" in lowered:
        return LeadChatBroken.RIGHTS
    return LeadChatBroken.REFUSED


def _telegram_delivery(lead_id: uuid.UUID) -> ColumnElement[bool]:
    return and_(
        LeadDelivery.lead_id == lead_id, LeadDelivery.channel == Channel.TELEGRAM
    )


def _claim(
    db: Session, *, owner_id: uuid.UUID, lead_id: uuid.UUID, now: datetime
) -> bool:
    """The lead is ours to send: nobody else will, now or after a crash.
    A claim left half-way (the worker died mid-send) is taken over."""
    db.execute(
        delete(LeadDelivery).where(
            _telegram_delivery(lead_id),
            LeadDelivery.status == DeliveryStatus.SENDING,
            LeadDelivery.sent_at < now - timedelta(seconds=LEAD_POST_STALE_SECONDS),
        )
    )
    claimed = db.scalar(
        insert(LeadDelivery)
        .values(
            id=uuid.uuid4(),
            created_at=now,
            updated_at=now,
            owner_id=owner_id,
            lead_id=lead_id,
            channel=Channel.TELEGRAM,
            status=DeliveryStatus.SENDING,
            sent_at=now,
        )
        .on_conflict_do_nothing(constraint="uniq_delivery_per_lead_channel")
        .returning(LeadDelivery.id)
    )
    db.commit()
    return claimed is not None


def _release(db: Session, *, lead_id: uuid.UUID) -> None:
    """It did not go: the next try, or the sweep, sends it."""
    db.execute(
        delete(LeadDelivery).where(
            _telegram_delivery(lead_id), LeadDelivery.status == DeliveryStatus.SENDING
        )
    )
    db.commit()


def compose_lead(
    db: Session, *, lead: Lead, pair: Pair
) -> tuple[str, tuple[Button, ...]]:
    """The lead as one message: who, how to reach them, what they answered,
    and where they came from."""
    from app.modules.ads.models import Ad
    from app.modules.leads.selectors import extra_answers

    lines = ["<b>Yangi lid</b>", ""]
    if lead.full_name:
        lines.append(f"Ism: {escaped(lead.full_name)}")
    if lead.phone_e164:
        lines.append(f"Telefon: {escaped(lead.phone_e164)}")
    if lead.email:
        lines.append(f"Email: {escaped(lead.email)}")
    if lead.city:
        lines.append(f"Shahar: {escaped(lead.city)}")
    answered = [
        f"{escaped(question[:LEAD_POST_QUESTION_CHARS])}: "
        f"{escaped(answer[:LEAD_POST_ANSWER_CHARS])}"
        for question, answer in extra_answers(lead).items()
    ]
    tail = [""]
    ad_name = (
        db.scalar(select(Ad.name).where(Ad.external_id == lead.ad_external_id))
        if lead.ad_external_id
        else None
    )
    if ad_name:
        tail.append(f"Reklama: {escaped(ad_name)}")
    if lead.form is not None and lead.form.name:
        tail.append(f"Forma: {escaped(lead.form.name)}")
    tail.append(f"Sahifa: {escaped(_pair_label(pair))}")
    tail.append(f"Vaqt: {localtime(lead.submitted_at):%d.%m.%Y %H:%M}")
    # Telegram takes no longer message: the last answers give way, never who and where.
    shown = list(answered)
    while (
        shown
        and len("\n".join([*lines, "", *shown, "…", *tail])) > LEAD_POST_TEXT_CHARS
    ):
        shown.pop()
    if shown:
        lines += ["", *shown]
    if len(shown) < len(answered):
        lines.append("…")
    lines += tail
    site = settings.site_url.rstrip("/")
    buttons: tuple[Button, ...] = ()
    if site.startswith("https://"):
        buttons = (Button(text="Kabinetda ochish", url=f"{site}/app/leads/{lead.id}/"),)
    return "\n".join(lines), buttons


def check_lead_chats(db: Session, *, now: datetime) -> int:
    """Look at the linked chats not looked at for an hour. Telegram says
    nothing when a group or a channel is made public, so this is how a chat
    that would show its leads' telephones to anybody stops; a chat gone or
    the bot no longer in it stops here too, before a lead finds out."""
    due = list(
        db.scalars(
            select(LeadChat)
            .where(
                LeadChat.status == LeadChatStatus.ACTIVE,
                or_(
                    LeadChat.checked_at.is_(None),
                    LeadChat.checked_at
                    < now - timedelta(seconds=LEAD_CHAT_CHECK_SECONDS),
                ),
            )
            .order_by(LeadChat.checked_at.asc().nulls_first())
            .limit(LEAD_CHAT_CHECKS_PER_RUN)
        )
    )
    if not due or not is_configured():
        return 0
    broken: list[LeadChat] = []
    with bot() as client:
        for row in due:
            reason = ""
            try:
                info = client.get_chat(chat_id=row.chat_id)
            except ChatMigrated as exc:
                _migrate(db, old=row.chat_id, new=exc.migrate_to_chat_id, now=now)
                continue
            except TelegramTemporaryError:
                break
            except (BotBlocked, ChatUnreachable, TelegramAPIError) as exc:
                reason = _reason(exc)
            else:
                reason = LeadChatBroken.PUBLIC if info.public else ""
                row.title = (info.title or row.title)[:255]
            row.checked_at = now
            if reason:
                _break(db, row=row, reason=reason, error="", now=now)
                broken.append(row)
        db.commit()
        for row in broken:
            _tell_owner_broken(db, client=client, row=row, now=now)
    return len(due)


def sweep_lead_posts(db: Session, *, now: datetime) -> int:
    """Queue every lead of the last day a linked pair should have posted
    and has not: a task lost, Telegram away for longer than the retries."""
    from app.modules.crm.selectors import pair_conditions
    from app.modules.destinations.tasks import post_lead_task
    from app.modules.leads.selectors import subscribed_lead_scope

    floor = now - timedelta(hours=LEAD_POST_SWEEP_HOURS)
    # Two minutes for the task queued as the lead arrived to run first.
    ceiling = now - timedelta(minutes=2)
    stale = now - timedelta(seconds=LEAD_POST_STALE_SECONDS)
    owner_ids = list(
        db.scalars(
            select(LeadChatPair.owner_id)
            .join(LeadChat, LeadChat.id == LeadChatPair.lead_chat_id)
            .where(LeadChat.status == LeadChatStatus.ACTIVE)
            .distinct()
        )
    )
    queued = 0
    for owner_id in owner_ids:
        owner = db.get(User, owner_id)
        if owner is None:
            continue
        seats = {
            (seat.page_id, seat.ad_account_id): seat
            for seat in db.scalars(
                select(LeadChatPair).where(LeadChatPair.owner_id == owner.id)
            )
            if seat.lead_chat.status == LeadChatStatus.ACTIVE
        }
        pairs = [
            p for p in page_pairs(db, owner=owner) if (p.page.id, p.account.id) in seats
        ]
        conditions = pair_conditions(db, owner=owner, pairs=pairs)
        paid = subscribed_lead_scope(db, owner=owner)
        for pair in pairs:
            condition = conditions.get(pair.key)
            if condition is None:
                continue
            since = max(floor, seats[pair.page.id, pair.account.id].linked_at)
            missing = db.scalars(
                select(Lead.id)
                .where(
                    Lead.owner_id == owner.id,
                    Lead.is_test.is_(False),
                    Lead.is_organic.is_(False),
                    Lead.received_at >= since,
                    Lead.received_at <= ceiling,
                    condition,
                    paid,
                    ~exists().where(
                        LeadDelivery.lead_id == Lead.id,
                        LeadDelivery.channel == Channel.TELEGRAM,
                        or_(
                            LeadDelivery.status != DeliveryStatus.SENDING,
                            LeadDelivery.sent_at >= stale,
                        ),
                    ),
                )
                .order_by(Lead.received_at)
                .limit(LEAD_POST_SWEEP_LIMIT)
            )
            for lead_id in missing:
                post_lead_task.delay(str(lead_id))
                queued += 1
    return queued


__all__ = [
    "check_lead_chats",
    "compose_lead",
    "drop_lead_chat",
    "find_pair",
    "handle_lead_chat_press",
    "handle_membership",
    "is_lead_chat_press",
    "is_lead_chat_start",
    "issue_lead_chat_link",
    "lead_chat_group_start",
    "offer_lead_chat",
    "post_lead",
    "queue_lead_post",
    "sweep_lead_posts",
    "unlink_pair",
]
