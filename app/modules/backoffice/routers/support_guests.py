"""The sign-in page's chats in the office: people not signed in, mostly
asking for their password back.

Support and the Owner only. The guest wrote a name, a phone and an email;
the account behind that email is shown beside them, with its phone, so the
office checks the phone matches before it gives a password back. A chat
that signing in moved into the account's own chat is read-only here.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ANSWER_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.routers._out import choices, person_out
from app.modules.backoffice.schemas import (
    GuestQueueOut,
    GuestThreadOut,
    MessageOut,
)
from app.modules.supportchat import selectors, services
from app.modules.supportchat.constants import EVERYONE, MAX_BODY_CHARS, OFFICE, WAITING
from app.modules.supportchat.models import SupportGuestChat
from app.modules.supportchat.schemas import GuestMessageOut

router = APIRouter(prefix="/support/guests")
Answer = Annotated[User, Depends(staff_required(*ANSWER_ROLES))]

STATES = ((WAITING, "Javob kutmoqda"), (EVERYONE, "Hammasi"))


class SayIn(BaseModel):
    body: str = Field("", description="The words.")


def _chat(db: Session, chat_id: uuid.UUID) -> SupportGuestChat:
    chat = selectors.guest_chat(db, pk=chat_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return chat


def _guest(chat: SupportGuestChat) -> dict[str, Any]:
    return {
        "id": str(chat.id),
        "name": chat.name,
        "phone": chat.phone,
        "email": chat.email,
        "created_at": chat.created_at,
        "moved": chat.claimed_at is not None,
        "claimed_by": person_out(chat.claimed_by),
    }


def _account(db: Session, chat: SupportGuestChat) -> dict[str, Any] | None:
    """The account behind the guest's email: who to give a password back to,
    and whether the phone the guest wrote is the one it holds."""
    account = services.account_for_guest(db, chat=chat)
    if account is None:
        return None
    return {
        **(person_out(account) or {}),
        "phone": account.phone,
        "phone_matches": bool(account.phone) and account.phone == chat.phone,
    }


@router.get("", responses={200: {"model": GuestQueueOut}})
def guest_queue(
    db: Db,
    user: Answer,
    state: str = Query(WAITING, description="`waiting` (default) or `all`."),
) -> dict[str, Any]:
    """The guests who wrote; the waiting ones by default, oldest first."""
    asked = EVERYONE if state == EVERYONE else WAITING
    rows = selectors.guest_queue(db, state=asked)
    return jsonable_encoder(
        {
            "state": asked,
            "states": choices(STATES),
            "rows": [
                {
                    **_guest(row.chat),
                    "waiting": row.waiting,
                    "last_message_at": row.chat.last_message_at,
                    "preview": row.last.body[:160] if row.last else "",
                    "last_side": (
                        ("client" if row.last.from_guest else "office")
                        if row.last
                        else ""
                    ),
                }
                for row in rows
            ],
        }
    )


@router.get("/{chat_id}", responses={200: {"model": GuestThreadOut}})
def guest_thread(chat_id: uuid.UUID, db: Db, user: Answer) -> dict[str, Any]:
    """One guest's chat. Opening it reads it."""
    chat = _chat(db, chat_id)
    now = utcnow()
    if services.mark_guest_read(db, chat=chat, by_guest=False, now=now):
        set_committed_value(chat, "office_read_at", now)
    return jsonable_encoder(
        {
            **_guest(chat),
            "waiting": selectors.is_guest_waiting(chat=chat),
            "account": _account(db, chat),
            "messages": [
                selectors.guest_message_view(message, chat=chat, viewer=OFFICE)
                for message in selectors.guest_messages(db, chat=chat)
            ],
            "guest_read_at": chat.guest_read_at,
            "max_body_chars": MAX_BODY_CHARS,
        }
    )


@router.post(
    "/{chat_id}/messages",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": GuestMessageOut}},
)
def guest_reply(
    chat_id: uuid.UUID, body: SayIn, db: Db, actor: Answer
) -> dict[str, Any]:
    """A reply to the guest. The page they have open shows it on its next poll."""
    chat = _chat(db, chat_id)
    message = services.office_answers_guest(
        db, chat=chat, sender=actor, body=body.body, now=utcnow()
    )
    db.refresh(chat)
    return jsonable_encoder(
        selectors.guest_message_view(message, chat=chat, viewer=OFFICE)
    )


@router.post("/{chat_id}/settle", responses={200: {"model": MessageOut}})
def guest_settle(chat_id: uuid.UUID, db: Db, actor: Answer) -> dict[str, Any]:
    """Out of the queue: the guest's last words need no answer."""
    services.settle_guest(db, chat=_chat(db, chat_id), now=utcnow())
    return {"message": "Navbatdan olindi."}
