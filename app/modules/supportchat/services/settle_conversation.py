"""The office saying the client's last words need no answer.

A "thank you" would otherwise sit in the queue as waiting for ever. This
takes the chat out without writing to the client; their next message puts
it back by being later than this moment.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import NotAllowed
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.backoffice.services import may_answer_support
from app.modules.supportchat.models import SupportConversation
from app.modules.supportchat.selectors import is_waiting
from app.modules.supportchat.services._journal import journal
from app.modules.supportchat.services._tx import atomic


def settle_conversation(
    db: Session, *, conversation: SupportConversation, actor: User, now: datetime
) -> SupportConversation:
    """Take this chat out of the queue until the client writes again. Asked
    of a chat that is not waiting, it answers with the row and journals
    nothing - two colleagues pressing together leave one record."""
    if not may_answer_support(db, user=actor):
        raise NotAllowed("Bu suhbatga yoza olmaysiz.")

    def run() -> SupportConversation:
        locked = db.scalar(
            select(SupportConversation)
            .where(SupportConversation.id == conversation.id)
            .with_for_update(of=SupportConversation)
            .execution_options(populate_existing=True)
        )
        if locked is None:
            raise LookupError("support conversation not found")
        if not is_waiting(conversation=locked):
            return locked
        before = locked.settled_at
        locked.settled_at = now
        db.flush()
        journal(
            db,
            conversation=locked,
            actor=actor,
            action=ActionType.SUPPORT_SETTLE,
            event=EventName.SUPPORT_CONVERSATION_SETTLED,
            payload={"settled_at": now.isoformat()},
            previous_state={"settled_at": before.isoformat() if before else None},
            # Within the log's 64 characters: the id without dashes and the
            # moment in whole seconds.
            key=f"support-settle:{locked.id.hex}:{int(now.timestamp())}",
            now=now,
        )
        return locked

    return atomic(db, run)
