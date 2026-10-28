"""Write inside a chat by its id: the office's replies, and the client's
words in a chat they already have."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import NotAllowed
from app.modules.accounts.models import User
from app.modules.backoffice.services import may_answer_support
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.models import SupportConversation, SupportMessage
from app.modules.supportchat.services._once import once
from app.modules.supportchat.services._store import store_message
from app.modules.supportchat.services._tx import atomic


def post_message(
    db: Session,
    *,
    conversation: SupportConversation,
    sender: User,
    draft: Draft,
    now: datetime,
    send_key: str = "",
) -> SupportMessage:
    """Append one message to this chat, once per ``send_key``. The client
    writes in their own chat; Support writes in any."""

    def run() -> SupportMessage:
        locked = db.scalar(
            select(SupportConversation)
            .where(SupportConversation.id == conversation.id)
            .with_for_update(of=SupportConversation)
            .execution_options(populate_existing=True)
        )
        if locked is None:
            raise LookupError("support conversation not found")
        if sender.id != locked.owner_id and not may_answer_support(db, user=sender):
            raise NotAllowed("Bu suhbatga yoza olmaysiz.")
        return store_message(
            db, conversation=locked, sender=sender, draft=draft, now=now
        )

    with once(sender=sender, key=send_key):
        return atomic(db, run)
