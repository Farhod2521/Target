"""The office writing first: a message to a client, opening their chat."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common.exceptions import NotAllowed
from app.modules.accounts.models import User
from app.modules.backoffice.services import may_answer_support
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.models import SupportMessage
from app.modules.supportchat.services._store import store_message
from app.modules.supportchat.services._tx import atomic
from app.modules.supportchat.services.send_to_support import chat_of_client


def write_to_client(
    db: Session, *, client: User, sender: User, draft: Draft, now: datetime
) -> SupportMessage:
    """One message from the office into this client's chat."""
    if not may_answer_support(db, user=sender):
        raise NotAllowed("Mijozga yoza olmaysiz.")

    def run() -> SupportMessage:
        conversation = chat_of_client(db, owner=client, now=now, opened_by=sender)
        return store_message(
            db, conversation=conversation, sender=sender, draft=draft, now=now
        )

    return atomic(db, run)
