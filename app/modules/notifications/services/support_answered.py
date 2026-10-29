"""Marking the office's Telegram copies of a client's messages as answered.

Whoever answers - from Telegram or the console - every copy of what the
client asked is rewritten with "answered, by whom, when" under it, so the
next person to open the bot sees there is nothing left to do.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.hooks import on
from app.modules.notifications.bot import staff_bot, staff_bot_configured
from app.modules.notifications.services.compose import support_answered_message
from app.modules.notifications.services.send import edit
from app.modules.notifications.services.support_confirm import signed, stamp
from app.modules.notifications.services.support_desk import question_for
from app.modules.supportchat.preview import preview_text
from app.modules.supportchat.selectors import (
    drawn,
    staff_message_for_relay,
    unanswered_relays,
)
from app.modules.supportchat.services import (
    REPLY_ANSWERS_RELAYS,
    mark_relays_answered,
)

logger = logging.getLogger(__name__)


@on(REPLY_ANSWERS_RELAYS)
def queue_support_answered(*, reply_id: Any, **_: Any) -> None:
    """Mark the copies from a worker, once the reply has committed."""
    from app.modules.notifications.tasks import mark_support_answered_task

    try:
        mark_support_answered_task.delay(str(reply_id))
    except Exception:
        logger.warning("support answered not queued", exc_info=True)


def announce_support_answered(db: Session, *, reply_id: str, now: datetime) -> int:
    """Stamp and rewrite every copy this reply answers. Returns how many.
    Stamped first, rewritten after: a redelivered task finds them stamped
    and rewrites nothing; a rewrite Telegram refuses is lost, the stamp
    stands, and a second reply is still held."""
    reply = staff_message_for_relay(db, message_id=reply_id)
    if reply is None or reply.sender_id == reply.owner_id:
        return 0
    marked = mark_relays_answered(
        db, relays=unanswered_relays(db, reply=reply), reply=reply
    )
    if not marked or not staff_bot_configured():
        return len(marked)
    files = drawn(db, [reply]).files.get(reply.id, [])
    answer = preview_text(reply, files)
    with staff_bot() as client:
        for relay in marked:
            text = support_answered_message(
                question=question_for(db, message=relay.message),
                name=signed(reply),
                at=stamp(reply.created_at),
                answer=answer,
            ).text
            edit(
                client=client,
                chat_id=relay.chat_id,
                message_id=relay.telegram_message_id,
                text=text,
            )
    logger.info(
        "support copies marked answered",
        extra={"reply_id": str(reply.id), "copies": len(marked), "at": now.isoformat()},
    )
    return len(marked)


__all__ = ["announce_support_answered", "queue_support_answered"]
