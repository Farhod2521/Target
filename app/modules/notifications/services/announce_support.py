"""Telling a client, on their phone, that the office replied.

The support chat is read in the cabinet, and a question asked there is
otherwise answered into a page nobody has open. One message per stretch of
not reading: the subject carries the moment the client last looked, so
three replies written while they are away are one message.
"""

import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.common.hooks import on
from app.common.i18n import override
from app.modules.accounts.models import User
from app.modules.notifications.bot import bot, is_configured
from app.modules.notifications.constants import NoticeKind
from app.modules.notifications.selectors import chat_for
from app.modules.notifications.services.compose import support_reply_message
from app.modules.notifications.services.journal import claim, stamp
from app.modules.notifications.services.send import send_to
from app.modules.supportchat.services import REPLY_POSTED

logger = logging.getLogger(__name__)


@on(REPLY_POSTED)
def queue_support_reply(*, owner_id: Any, subject: str, **_: Any) -> None:
    """Send the message from a worker; the hook fires after the commit."""
    from app.modules.notifications.tasks import deliver_support_reply_task

    try:
        deliver_support_reply_task.delay(str(owner_id), subject)
    except Exception:
        logger.warning("support reply notice not queued", exc_info=True)


def announce_support_reply(
    db: Session, *, owner: User, subject: str, now: datetime
) -> bool:
    """Send it, if a phone is linked and this stretch was not told yet.
    Claim, send, stamp: a worker that dies between leaves a claim rather
    than a duplicate."""
    chat = chat_for(db, owner=owner)
    if chat is None or not is_configured():
        return False
    with override(owner.language):
        notice = claim(db, chat=chat, kind=NoticeKind.SUPPORT_REPLY, subject=subject)
        if notice is None:
            return False
        text = support_reply_message().text
        with bot() as client:
            sent = send_to(db, client=client, chat=chat, text=text, now=now)
    stamp(db, notice=notice, message_id=sent, now=now)
    logger.info(
        "support reply announced",
        extra={"owner_id": str(owner.id), "sent": bool(sent)},
    )
    return bool(sent)


__all__ = ["announce_support_reply", "queue_support_reply"]
