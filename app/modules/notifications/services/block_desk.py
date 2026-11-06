"""Telling Support, in the staff bot, that the system asks for a block.

The system refuses (one Facebook or Google account in a second cabinet) and
blocks nobody; whoever may block hears of it once, when the suggestion is
new, and decides in the office.
"""

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session
from telegramkit import TelegramError

from app.common.hooks import on
from app.common.routes import reverse
from app.modules.accounts.models import BlockSuggestion, User
from app.modules.accounts.services import BLOCK_SUGGESTED
from app.modules.backoffice.constants import BLOCK_ROLES
from app.modules.backoffice.permissions import has_role
from app.modules.notifications.bot import staff_bot, staff_bot_configured
from app.modules.notifications.selectors import staff_chats_where
from app.modules.notifications.services.compose import block_suggestion_message

logger = logging.getLogger(__name__)


@on(BLOCK_SUGGESTED)
def queue_block_suggestion(*, suggestion_id: Any, **_: Any) -> None:
    """Send from a worker; the hook fires after the suggestion's commit."""
    from app.modules.notifications.tasks import deliver_block_suggestion_task

    try:
        deliver_block_suggestion_task.delay(str(suggestion_id))
    except Exception:
        logger.warning("block suggestion not queued", exc_info=True)


def announce_block_suggestion(db: Session, *, suggestion_id: str) -> int:
    """Send it to everybody who may block with the staff bot linked; returns
    how many went out. A suggestion already decided is not announced."""
    try:
        suggestion = db.get(BlockSuggestion, uuid.UUID(suggestion_id))
    except ValueError:
        return 0
    if (
        suggestion is None
        or suggestion.resolved_at is not None
        or not staff_bot_configured()
    ):
        return 0
    chats = staff_chats_where(db, allowed=lambda user: has_role(db, user, BLOCK_ROLES))
    if not chats:
        return 0
    owner = suggestion.owner
    held = str((suggestion.detail or {}).get("held_by") or "")
    holder = _user(db, held)
    text = block_suggestion_message(
        client=f"{owner.full_name or owner.email} · {owner.email}",
        reason=suggestion.reason.name,
        held_by=holder.email if holder is not None else "",
        office_path=reverse("backoffice:customer", [owner.id]),
    ).text
    sent = 0
    with staff_bot() as client:
        for chat in chats:
            try:
                client.send_message(chat_id=chat.chat_id, text=text)
                sent += 1
            except TelegramError:
                logger.warning("block suggestion not sent to %s", chat.chat_id)
    logger.info(
        "block suggestion announced",
        extra={"suggestion_id": suggestion_id, "copies": sent},
    )
    return sent


def _user(db: Session, value: str) -> User | None:
    try:
        return db.get(User, uuid.UUID(value)) if value else None
    except ValueError:
        return None
