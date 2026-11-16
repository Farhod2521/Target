"""The office assistant in the owners' bot (@owners_tai_bot).

The owners there are Telegram ids from ``STAFF_BOT_ADMIN_IDS``, not logins,
but a question and its answer are rows of a person's thread. The person is
the office account whose staff bot is linked to that same Telegram id when
it holds the Owner role (or is a superuser), and otherwise the oldest active
superuser - the deployment's own. They see money: an owner does.

The turn is the site's turn; only the last step differs. Instead of a
stream, the finished answer is written over the "⏳" message, as Telegram
HTML, in pieces when it is long.
"""

import logging
import re
from datetime import datetime
from html import escape
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.backoffice.constants import Role
from app.modules.backoffice.permissions import has_role
from app.modules.officeai.constants import (
    OUT_KEY,
    TELEGRAM_CHANNEL,
    TELEGRAM_CHUNK_CHARS,
    TELEGRAM_THREAD_KEY,
    TELEGRAM_THREAD_TTL_SECONDS,
)
from app.modules.officeai.selectors.threads import thread_for
from app.modules.officeai.services.ask import Turn, start_turn, turn_payload

logger = logging.getLogger(__name__)

FAILED = "Javob olinmadi. Birozdan keyin qayta so'rab ko'ring."
MASKED = "<i>[?] - tekshirib bo'lmagan raqam.</i>"


def asker_for(db: Session, *, telegram_id: str) -> User | None:
    """The office account a Telegram owner asks as."""
    from app.modules.notifications.models import StaffChat

    linked = db.scalar(
        select(User)
        .join(StaffChat, StaffChat.owner_id == User.id)
        .where(StaffChat.chat_id == telegram_id, StaffChat.is_active.is_(True))
        .limit(1)
    )
    if linked is not None and has_role(db, linked, (Role.OWNER,)):
        return linked
    return db.scalar(
        select(User)
        .where(
            User.is_superuser.is_(True),
            User.is_staff.is_(True),
            User.is_active.is_(True),
        )
        .order_by(User.date_joined, User.id)
        .limit(1)
    )


def forget_thread(*, chat_id: str) -> None:
    cache.delete(TELEGRAM_THREAD_KEY.format(chat_id=chat_id))


def ask_from_telegram(
    db: Session, *, telegram_id: str, chat_id: str, question: str, now: datetime
) -> Turn | None:
    """The question on this chat's thread; None when nobody can ask."""
    staff = asker_for(db, telegram_id=telegram_id)
    if staff is None:
        return None
    key = TELEGRAM_THREAD_KEY.format(chat_id=chat_id)
    known = cache.get(key)
    thread = thread_for(db, staff=staff, pk=str(known)) if known else None
    turn = start_turn(
        db,
        staff=staff,
        question=question,
        thread=thread,
        sees_money=True,
        now=now,
        channel=TELEGRAM_CHANNEL,
    )
    cache.set(key, turn.thread_id, TELEGRAM_THREAD_TTL_SECONDS)
    return turn


def answer_in_telegram(
    db: Session, *, turn_id: str, chat_id: str, notice_id: int, now: datetime
) -> str:
    """Write the answer, then put it in the chat."""
    from app.modules.notifications.bot import owners_bot
    from app.modules.officeai.services.answer import answer_turn

    payload = turn_payload(turn_id=turn_id)
    if payload is None:
        return "gone"
    try:
        answer_turn(db, turn_id=turn_id, payload=payload, now=now)
    finally:
        state = cache.get(OUT_KEY.format(turn_id=turn_id))
        pieces = _pieces(state)
        with owners_bot() as client:
            _deliver(client, chat_id=chat_id, notice_id=notice_id, pieces=pieces)
    return "failed" if pieces == [FAILED] else "answered"


def _pieces(state: Any) -> list[str]:
    if not isinstance(state, dict) or state.get("error") or not state.get("text"):
        return [FAILED]
    pieces = split(telegram_html(str(state["text"])))
    if state.get("masked"):
        pieces[-1] = f"{pieces[-1]}\n\n{MASKED}"
    return pieces


def _deliver(client: Any, *, chat_id: str, notice_id: int, pieces: list[str]) -> None:
    from telegramkit import TelegramError

    first, *rest = pieces
    try:
        if notice_id:
            client.edit_message_text(chat_id=chat_id, message_id=notice_id, text=first)
        else:
            client.send_message(chat_id=chat_id, text=first)
    except TelegramError as exc:
        logger.info("office_ai_telegram_edit_failed", extra={"reason": str(exc)})
        client.send_message(chat_id=chat_id, text=first)
    for piece in rest:
        client.send_message(chat_id=chat_id, text=piece)


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`\n]+)`")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)


def telegram_html(text: str) -> str:
    """The model's markdown as the little HTML Telegram takes: escaped
    first, then bold, code, headings as bold lines and bullets as dots."""
    out = escape(text.strip(), quote=False)
    out = _HEADING.sub(r"<b>\1</b>", out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    out = _CODE.sub(r"<code>\1</code>", out)
    return _BULLET.sub(r"\1• ", out)


def split(text: str, size: int = TELEGRAM_CHUNK_CHARS) -> list[str]:
    """Pieces under Telegram's limit, cut at a blank line or a line end."""
    pieces: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n\n", 0, size)
        if cut <= 0:
            cut = text.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        pieces.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    pieces.append(text)
    return [piece for piece in pieces if piece] or [FAILED]


__all__ = [
    "answer_in_telegram",
    "ask_from_telegram",
    "asker_for",
    "forget_thread",
    "split",
    "telegram_html",
]
