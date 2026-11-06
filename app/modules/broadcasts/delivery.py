"""Sending a broadcast: one post to the channel, then the bot's chats one by
one, at Telegram's pace.

**Claim, send, stamp, commit - per chat.** A delivery is marked claimed
and committed before its message goes out, so a worker that dies mid-send
leaves a claim and not a duplicate. A run sends at most ``BATCH_SIZE`` and
says whether there is more; the task queues the next run, so a stop
pressed in the office is heard within one message and a restarted worker
goes on from the first chat still pending.
"""

import html
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from telegramkit import (
    CAPTION_MAX_CHARS,
    BotBlocked,
    BotClient,
    ChatUnreachable,
    SentMessage,
    TelegramError,
    TelegramRateLimited,
    message_units,
)

from app.common import storage
from app.common.config import settings
from app.modules.broadcasts.constants import (
    BATCH_SIZE,
    MAX_INLINE_WAIT_SECONDS,
    SENDS_PER_SECOND,
    BroadcastStatus,
    DeliveryStatus,
)
from app.modules.broadcasts.models import Broadcast, BroadcastDelivery
from app.modules.notifications.constants import ERROR_BLOCKED, ERROR_UNREACHABLE
from app.modules.notifications.models import TelegramChat

logger = logging.getLogger(__name__)


def message_text(row: Broadcast) -> str:
    """The title in bold over the info, as Telegram's HTML."""
    title = html.escape(row.title.strip(), quote=False)
    body = html.escape(row.body.strip(), quote=False)
    return f"<b>{title}</b>\n\n{body}" if body else f"<b>{title}</b>"


def post(db: Session, *, client: BotClient, row: Broadcast, chat_id: str) -> int:
    """Post the broadcast to one chat and return the last message's id.

    With a picture and a text that fits under it, one message; a longer
    text goes on its own after the picture. The picture is uploaded once
    and sent by Telegram's id after that. Raises what Telegram refused.
    """
    text = message_text(row)
    if not row.image:
        return client.send_message(chat_id=chat_id, text=text).message_id
    caption = text if message_units(text) <= CAPTION_MAX_CHARS else ""
    sent = _photo(db, client=client, row=row, chat_id=chat_id, caption=caption)
    if caption:
        return sent.message_id
    return client.send_message(chat_id=chat_id, text=text).message_id


def _photo(
    db: Session, *, client: BotClient, row: Broadcast, chat_id: str, caption: str
) -> SentMessage:
    if row.photo_id:
        return client.send_photo_id(
            chat_id=chat_id, photo_id=row.photo_id, caption=caption
        )
    path = storage.media_path(row.image)
    sent = client.send_photo(
        chat_id=chat_id, filename=path.name, content=path.read_bytes(), caption=caption
    )
    if sent.photo_id:
        row.photo_id = sent.photo_id
        db.flush()
    return sent


def _channel(db: Session, *, client: BotClient, row: Broadcast) -> None:
    """The channel's one post, tried once: a refusal is kept, not retried."""
    try:
        row.channel_message_id = post(
            db, client=client, row=row, chat_id=settings.telegram_channel_id
        )
    except TelegramError as exc:
        row.channel_error = str(exc)[:255] or "Telegram rad etdi."
        logger.warning("broadcast_channel_refused", extra={"broadcast": str(row.id)})
    db.commit()


@dataclass(frozen=True, slots=True)
class Run:
    """What one run left: ``more`` asks for another, ``wait`` seconds on."""

    more: bool
    wait: int = 0


def _claim(db: Session, broadcast_id: uuid.UUID) -> BroadcastDelivery | None:
    delivery = db.scalars(
        select(BroadcastDelivery)
        .where(
            BroadcastDelivery.broadcast_id == broadcast_id,
            BroadcastDelivery.status == DeliveryStatus.PENDING,
        )
        .order_by(BroadcastDelivery.created_at, BroadcastDelivery.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).first()
    if delivery is None:
        return None
    delivery.status = DeliveryStatus.CLAIMED
    db.commit()
    return delivery


def _switch_off(db: Session, *, chat_id: str, reason: str, now: datetime) -> None:
    db.execute(
        update(TelegramChat)
        .where(TelegramChat.chat_id == chat_id, TelegramChat.is_active.is_(True))
        .values(is_active=False, last_error=reason, last_error_at=now)
    )


def _stopped(db: Session, row: Broadcast) -> bool:
    db.refresh(row, attribute_names=["status"])
    return row.status != BroadcastStatus.SENDING


def _finish(db: Session, row: Broadcast, *, now: datetime) -> None:
    db.execute(
        update(Broadcast)
        .where(Broadcast.id == row.id, Broadcast.status == BroadcastStatus.SENDING)
        .values(status=BroadcastStatus.SENT, finished_at=now)
    )
    db.commit()


def run(
    db: Session,
    *,
    client: BotClient,
    broadcast_id: uuid.UUID,
    now: Callable[[], datetime],
    sleep: Callable[[float], None] = time.sleep,
) -> Run:
    """One run of a broadcast that is sending. Returns whether to go on."""
    row = db.get(Broadcast, broadcast_id)
    if row is None or row.status != BroadcastStatus.SENDING:
        return Run(more=False)
    if row.to_channel and not row.channel_message_id and not row.channel_error:
        _channel(db, client=client, row=row)
    if not row.to_bot:
        _finish(db, row, now=now())
        return Run(more=False)
    for _ in range(BATCH_SIZE):
        if _stopped(db, row):
            return Run(more=False)
        delivery = _claim(db, row.id)
        if delivery is None:
            _finish(db, row, now=now())
            return Run(more=False)
        try:
            delivery.message_id = post(
                db, client=client, row=row, chat_id=delivery.chat_id
            )
            delivery.status = DeliveryStatus.SENT
        except TelegramRateLimited as exc:
            delivery.status = DeliveryStatus.PENDING
            db.commit()
            wait = max(int(exc.retry_after or 1), 1)
            if wait > MAX_INLINE_WAIT_SECONDS:
                return Run(more=True, wait=wait)
            sleep(wait)
            continue
        except (BotBlocked, ChatUnreachable) as exc:
            delivery.status = DeliveryStatus.BLOCKED
            delivery.error = str(exc)[:255]
            reason = ERROR_BLOCKED if isinstance(exc, BotBlocked) else ERROR_UNREACHABLE
            _switch_off(db, chat_id=delivery.chat_id, reason=reason, now=now())
        except TelegramError as exc:
            delivery.status = DeliveryStatus.FAILED
            delivery.error = str(exc)[:255]
        except OSError as exc:
            # The picture is gone from disk: every chat would fail the same.
            delivery.status = DeliveryStatus.FAILED
            delivery.error = str(exc)[:255]
        db.commit()
        sleep(1 / SENDS_PER_SECOND)
    return Run(more=True)


__all__ = ["Run", "message_text", "post", "run"]
