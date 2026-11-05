"""The sign-in page's "Yordam": a chat for somebody not signed in.

No account, so no bearer: the first message answers with a token, and the
page sends it back as ``X-Guest-Token``. Words only. The page polls
``GET /support/guest``; signing in calls ``POST /support/guest/claim`` with
both the bearer and the token, which moves the words into the account.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Header, Request, status
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.api.deps import CurrentUser, Db, client_address
from app.common.db import utcnow
from app.modules.supportchat import selectors, services
from app.modules.supportchat.constants import CLIENT, MAX_BODY_CHARS
from app.modules.supportchat.exceptions import GuestChatMissing, GuestChatMoved
from app.modules.supportchat.models import SupportGuestChat
from app.modules.supportchat.schemas import (
    GuestChatOut,
    GuestClaimOut,
    GuestMessageOut,
    GuestStartedOut,
)

router = APIRouter(prefix="/support/guest", tags=["support"])

Token = Annotated[
    str,
    Header(
        alias="X-Guest-Token", max_length=128, description="From `POST /support/guest`."
    ),
]


class StartIn(BaseModel):
    name: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=254)
    body: str = Field("", description="Empty: `Parolni tiklash kerak.`")


class SayIn(BaseModel):
    body: str = Field("", description="The words.")


def _chat(db: Session, token: str) -> SupportGuestChat:
    chat = selectors.guest_chat_by_token(db, token=token)
    if chat is None:
        raise GuestChatMissing
    return chat


def _screen(db: Session, chat: SupportGuestChat) -> dict[str, Any]:
    return jsonable_encoder(
        {
            "name": chat.name,
            "phone": chat.phone,
            "email": chat.email,
            "moved": chat.claimed_at is not None,
            "messages": [
                selectors.guest_message_view(message, chat=chat, viewer=CLIENT)
                for message in selectors.guest_messages(db, chat=chat)
            ],
            "office_read_at": chat.office_read_at,
            "max_body_chars": MAX_BODY_CHARS,
        }
    )


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": GuestStartedOut}},
)
def start(body: StartIn, request: Request, db: Db) -> dict[str, Any]:
    """Name, phone and email, and the first message: the chat and its token."""
    started = services.start_guest_chat(
        db,
        name=body.name,
        phone=body.phone,
        email=body.email,
        body=body.body,
        address=client_address(request),
        now=utcnow(),
    )
    return {"token": started.token, "chat": _screen(db, started.chat)}


@router.get("", responses={200: {"model": GuestChatOut}})
def read(db: Db, token: Token) -> dict[str, Any]:
    """The guest's chat. Opening it reads the office's replies."""
    chat = _chat(db, token)
    now = utcnow()
    if services.mark_guest_read(db, chat=chat, by_guest=True, now=now):
        set_committed_value(chat, "guest_read_at", now)
    return _screen(db, chat)


@router.post(
    "/messages",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": GuestMessageOut}},
)
def say(body: SayIn, db: Db, token: Token) -> dict[str, Any]:
    """One more message from the guest."""
    chat = _chat(db, token)
    if chat.claimed_at is not None:
        raise GuestChatMoved
    message = services.guest_writes(db, chat=chat, body=body.body, now=utcnow())
    db.refresh(chat)
    return jsonable_encoder(
        selectors.guest_message_view(message, chat=chat, viewer=CLIENT)
    )


@router.post("/claim", responses={200: {"model": GuestClaimOut}})
def claim(db: Db, user: CurrentUser, token: Token) -> dict[str, Any]:
    """Signed in now: the guest's words go into this account's chat, if the
    guest wrote its email or phone."""
    return {
        "moved": services.claim_guest_chat(db, token=token, user=user, now=utcnow())
    }
