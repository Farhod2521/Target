"""Writing broadcasts in the office: the draft, the test, the start, the stop.

A broadcast is edited only as a draft. Starting it writes one delivery for
every bot chat it will reach and queues the sending; the site shows it
from that moment. A stop is final: the chats still pending stay unsent.
"""

import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session
from telegramkit import TelegramError, message_units

from app.common import storage
from app.common.config import settings
from app.common.db import on_commit, utcnow
from app.common.deletion import delete_rows
from app.common.exceptions import Conflict, InputRefused
from app.common.images import read_size
from app.modules.accounts.models import User
from app.modules.broadcasts.constants import (
    BODY_MAX,
    IMAGE_DIR,
    IMAGE_TYPES,
    MAX_IMAGE_MB,
    TITLE_MAX,
    BroadcastStatus,
    DeliveryStatus,
)
from app.modules.broadcasts.delivery import message_text, post
from app.modules.broadcasts.exceptions import BroadcastLocked
from app.modules.broadcasts.models import Broadcast, BroadcastDelivery
from app.modules.broadcasts.selectors import recipients
from app.modules.notifications import bot as telegram
from app.modules.notifications.selectors import chat_for

logger = logging.getLogger(__name__)
_MB = 1024 * 1024
_HEADER_BYTES = 64 * 1024


def channel_ready() -> bool:
    return telegram.is_configured() and bool(settings.telegram_channel_id)


def networks() -> dict[str, bool]:
    """Which of the three this server can send to now."""
    return {
        "bot": telegram.is_configured(),
        "channel": channel_ready(),
        "site": True,
    }


# -- the draft -------------------------------------------------------------------------


@dataclass(slots=True)
class BroadcastIn:
    title: str
    body: str
    to_bot: bool
    to_channel: bool
    to_site: bool
    image: Any = None
    remove_image: bool = False


@dataclass(slots=True)
class Saved:
    """The row, and the files to delete once the commit has or has not held."""

    row: Broadcast
    stale: list[str] = field(default_factory=list)
    fresh: list[str] = field(default_factory=list)


def _suffix(name: str) -> str:
    return PurePosixPath(name).suffix.lower().lstrip(".")


def _image_problem(image: Any) -> str:
    if _suffix(image.filename or "") not in IMAGE_TYPES:
        return "Faqat " + ", ".join(IMAGE_TYPES).upper() + " rasm yuklang."
    if (image.size or 0) > MAX_IMAGE_MB * _MB:
        return f"Rasm {MAX_IMAGE_MB} MB dan oshmasin."
    head = image.file.read(_HEADER_BYTES)
    image.file.seek(0)
    if read_size(head) is None:
        return "Rasmni o'qib bo'lmadi. Boshqa rasm tanlang."
    return ""


def _problems(body: BroadcastIn) -> dict[str, str]:
    problems: dict[str, str] = {}
    title = body.title.strip()
    if not title:
        problems["title"] = "Sarlavhani yozing."
    elif len(title) > TITLE_MAX:
        problems["title"] = f"Sarlavha {TITLE_MAX} belgidan oshmasin."
    if not body.body.strip():
        problems["body"] = "Matnni yozing."
    elif len(body.body.strip()) > BODY_MAX:
        problems["body"] = f"Matn {BODY_MAX} belgidan oshmasin."
    elif message_units(message_text(Broadcast(title=title, body=body.body))) > 4096:
        problems["body"] = "Matn Telegram xabariga sig'maydi. Qisqartiring."
    if body.image is not None and (problem := _image_problem(body.image)):
        problems["image"] = problem
    return problems


def save_broadcast(
    db: Session, *, body: BroadcastIn, row: Broadcast | None, actor: User
) -> Saved:
    """Create a draft, or rewrite one. The networks are ticked here and
    checked again at the start, when they are used."""
    if row is not None and row.status != BroadcastStatus.DRAFT:
        raise BroadcastLocked
    problems = _problems(body)
    if problems:
        raise InputRefused(problems)
    if row is None:
        row = Broadcast(created_by_id=actor.id, status=BroadcastStatus.DRAFT)
        db.add(row)
    saved = Saved(row=row)
    row.title = body.title.strip()
    row.body = body.body.strip()
    row.to_bot = body.to_bot
    row.to_channel = body.to_channel
    row.to_site = body.to_site
    if body.image is not None or body.remove_image:
        saved.stale.append(row.image)
        row.image = ""
        row.photo_id = ""
    if body.image is not None:
        row.image = storage.save(
            body.image.file,
            folder=storage.dated(IMAGE_DIR, now=utcnow()),
            filename=body.image.filename or "image.jpg",
        )
        saved.fresh.append(row.image)
    db.flush()
    saved.stale = [name for name in saved.stale if name]
    logger.info("broadcast %s saved by %s", row.id, actor.id)
    return saved


def delete_broadcast(db: Session, *, row: Broadcast) -> list[str]:
    """Delete it and its deliveries; it leaves the site. What the bot and
    the channel already got stays there. Returns the files to delete after
    the commit."""
    if row.status == BroadcastStatus.SENDING:
        raise Conflict("Avval rassilkani to'xtating.")
    files = [row.image] if row.image else []
    delete_rows(db, Broadcast.__table__, Broadcast.id == row.id)
    db.expunge(row)
    return files


# -- the test, the start, the stop -----------------------------------------------------


def send_test(db: Session, *, row: Broadcast, actor: User) -> None:
    """The bot's message, to the one sending it, as everyone will get it."""
    if not telegram.is_configured():
        raise Conflict("Bot sozlanmagan.")
    chat = chat_for(db, owner=actor)
    if chat is None:
        raise Conflict("Avval o'z akkauntingizni kabinetdan botga ulang.")
    try:
        with telegram.bot() as client:
            post(db, client=client, row=row, chat_id=chat.chat_id)
    except TelegramError as exc:
        raise Conflict(f"Telegram rad etdi: {exc}") from exc


def _start_problems(row: Broadcast) -> dict[str, str]:
    problems: dict[str, str] = {}
    if not (row.to_bot or row.to_channel or row.to_site):
        problems["networks"] = "Kamida bittasini tanlang: bot, kanal yoki sayt."
    if row.to_bot and not telegram.is_configured():
        problems["to_bot"] = "Bot sozlanmagan."
    if row.to_channel and not channel_ready():
        problems["to_channel"] = "Kanal sozlanmagan: TELEGRAM_CHANNEL_ID bo'sh."
    if row.image and not storage.media_path(row.image).is_file():
        problems["image"] = "Rasm topilmadi. Qaytadan yuklang."
    return problems


def start(db: Session, *, row: Broadcast) -> int:
    """Send it. Returns how many bot chats it will go to."""
    if row.status != BroadcastStatus.DRAFT:
        raise BroadcastLocked("Bu rassilka allaqachon yuborilgan.")
    problems = _start_problems(row)
    if problems:
        raise InputRefused(problems)
    now = utcnow()
    chats = recipients(db) if row.to_bot else []
    if chats:
        db.execute(
            insert(BroadcastDelivery),
            [
                {
                    "broadcast_id": row.id,
                    "owner_id": owner_id,
                    "chat_id": chat_id,
                    "status": DeliveryStatus.PENDING,
                    "created_at": now,
                    "updated_at": now,
                }
                for owner_id, chat_id in chats
            ],
        )
    row.status = BroadcastStatus.SENDING
    row.started_at = now
    if not (row.to_bot or row.to_channel):
        row.status = BroadcastStatus.SENT
        row.finished_at = now
    db.flush()
    if row.status == BroadcastStatus.SENDING:
        from app.modules.broadcasts.tasks import deliver_broadcast_task

        broadcast_id = str(row.id)
        on_commit(db, lambda: deliver_broadcast_task.apply_async((broadcast_id,)))
    return len(chats)


def stop(db: Session, *, row: Broadcast) -> None:
    if row.status != BroadcastStatus.SENDING:
        raise Conflict("Faqat yuborilayotgan rassilkani to'xtatish mumkin.")
    row.status = BroadcastStatus.STOPPED
    row.finished_at = utcnow()
    db.flush()
