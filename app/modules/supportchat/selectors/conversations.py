"""Which chats each end of the support line may see.

The client's half scopes to the owner first. The staff half reads across
owners - the documented exception - and says so in each docstring. Callers
prove the role before calling: these functions check nothing themselves.
"""

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.supportchat.models import SupportConversation

C = SupportConversation

# The client spoke after the office did (or the office never spoke), and
# nobody in the office said those words need no answer. ``is_waiting`` is
# the same reading of one row in Python, and the two must agree.
AWAITING_OFFICE = and_(
    C.last_client_at.is_not(None),
    or_(C.last_office_at.is_(None), C.last_office_at < C.last_client_at),
    or_(C.settled_at.is_(None), C.settled_at < C.last_client_at),
)

# The office spoke after the client last looked: a reply they have not read.
UNREAD_BY_CLIENT = and_(
    C.last_office_at.is_not(None),
    or_(C.client_read_at.is_(None), C.client_read_at < C.last_office_at),
)


def coerce(pk: uuid.UUID | str) -> uuid.UUID | None:
    """An id from a URL or a socket, or ``None`` when it is not one."""
    try:
        return pk if isinstance(pk, uuid.UUID) else uuid.UUID(str(pk))
    except (ValueError, AttributeError):
        return None


def is_waiting(*, conversation: SupportConversation) -> bool:
    """:data:`AWAITING_OFFICE` for one row already in hand."""
    client = conversation.last_client_at
    if client is None:
        return False
    office = conversation.last_office_at
    settled = conversation.settled_at
    return (office is None or office < client) and (settled is None or settled < client)


def is_unread(*, conversation: SupportConversation) -> bool:
    """:data:`UNREAD_BY_CLIENT` for one row already in hand."""
    office = conversation.last_office_at
    seen = conversation.client_read_at
    return office is not None and (seen is None or seen < office)


def chat_of(db: Session, *, owner: User) -> SupportConversation | None:
    """This client's chat, or ``None`` before their first message."""
    return db.scalar(select(C).where(C.owner_id == owner.id).limit(1))


def conversation_for_owner(
    db: Session, *, owner: User, pk: uuid.UUID | str
) -> SupportConversation | None:
    """This client's chat by id; somebody else's reads as missing."""
    ident = coerce(pk)
    if ident is None:
        return None
    return db.scalar(select(C).where(C.owner_id == owner.id, C.id == ident))


def unread_reply(db: Session, *, owner: User) -> SupportConversation | None:
    """This client's chat when it holds a reply they have not seen."""
    return db.scalar(select(C).where(C.owner_id == owner.id, UNREAD_BY_CLIENT).limit(1))


def has_unread_reply(db: Session, *, owner: User) -> bool:
    """Whether the office wrote since this client last looked."""
    found = db.scalar(
        select(C.id).where(C.owner_id == owner.id, UNREAD_BY_CLIENT).limit(1)
    )
    return found is not None


def staff_conversation(
    db: Session, *, pk: uuid.UUID | str
) -> SupportConversation | None:
    """Any client's chat, by id. Cross-tenant by design: the caller has
    already established the office role."""
    ident = coerce(pk)
    if ident is None:
        return None
    return db.get(C, ident)


def office_wrote_at(
    db: Session, *, owner_ids: list[uuid.UUID]
) -> dict[uuid.UUID, datetime]:
    """When the office last wrote to each of these clients. Cross-tenant by
    design - the office's survey answers ask it of a page of clients."""
    rows = db.execute(
        select(C.owner_id, C.last_office_at).where(
            C.owner_id.in_(owner_ids), C.last_office_at.is_not(None)
        )
    )
    return {owner: moment for owner, moment in rows if moment is not None}


def awaiting_reply_count(db: Session) -> int:
    """Chats whose client spoke last and still wait. Cross-tenant by design."""
    return int(
        db.scalar(select(func.count()).select_from(C).where(AWAITING_OFFICE)) or 0
    )
