"""One side of the chat has seen it as it stands.

The client's reading turns the "new reply" badge off and draws the office's
second tick; the office's reading draws the client's. No audit row and no
event: it moves one moment forward on the chat's own row.
"""

from datetime import datetime

from sqlalchemy import or_, update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.services import may_answer_support
from app.modules.supportchat.models import SupportConversation

C = SupportConversation


def mark_read(
    db: Session, *, conversation: SupportConversation, reader: User, now: datetime
) -> bool:
    """Move the reader's side's moment to ``now``. Whether it moved.

    The client counts for their own chat, a member of Support for the
    office; nobody else's reading counts. One conditional update, so two
    tabs open on the same chat never move the moment backwards.
    """
    if reader.id == conversation.owner_id:
        statement = (
            update(C)
            .where(
                C.id == conversation.id,
                C.owner_id == reader.id,
                or_(C.client_read_at.is_(None), C.client_read_at < now),
            )
            # A queryset update in Django: ``updated_at`` stays as it was.
            .values(client_read_at=now, updated_at=C.updated_at)
        )
    elif may_answer_support(db, user=reader):
        # Cross-tenant by design: the role was checked on the line above.
        statement = (
            update(C)
            .where(
                C.id == conversation.id,
                or_(C.office_read_at.is_(None), C.office_read_at < now),
            )
            .values(office_read_at=now, updated_at=C.updated_at)
        )
    else:
        return False
    moved = db.execute(statement.execution_options(synchronize_session=False))
    db.commit()
    return bool(moved.rowcount)
