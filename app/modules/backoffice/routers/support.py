"""The support queue in the office: every client's chat, and one of them.

Support and the Owner only. Reading a client's chat or taking a file out of
it is a reading of somebody's account, so both leave a journal row the way
opening their card does. Writes are the support chat's own services; this
is the console around them.

A chat never closes. Besides answering, the office can say the client's
last words need no answer, which takes the chat out of the queue until they
write again. Live updates come over ``/office/support/{id}/ws``.
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import ANSWER_ROLES, ActionKind
from app.modules.backoffice.permissions import has_role, staff_required
from app.modules.backoffice.routers._out import choices, person_out
from app.modules.backoffice.schemas import (
    ChatHoldOut,
    MessageOut,
    SupportQueueOut,
    SupportThreadOut,
)
from app.modules.backoffice.selectors.card import person
from app.modules.backoffice.services import seen
from app.modules.boards import chat_hold
from app.modules.notifications.selectors import last_support_bot_chat_for
from app.modules.supportchat import selectors, services
from app.modules.supportchat.constants import EVERYONE, OFFICE, WAITING
from app.modules.supportchat.drafts import Draft, Voice
from app.modules.supportchat.exceptions import AlreadySent
from app.modules.supportchat.files import attachment_response, stored_file_response
from app.modules.supportchat.live import (
    broadcast_change,
    broadcast_message,
    broadcast_read,
)
from app.modules.supportchat.models import SupportConversation, SupportMessage
from app.modules.supportchat.preview import preview_text
from app.modules.supportchat.routers import check_box, composer, file_reader
from app.modules.supportchat.routers.live import office_socket
from app.modules.supportchat.rules import side_of
from app.modules.supportchat.schemas import MessageOut as ChatMessageOut
from app.modules.supportchat.schemas import SentOut

router = APIRouter(prefix="/support")
Answer = Annotated[User, Depends(staff_required(*ANSWER_ROLES))]

# The chips above the list. Waiting first, because that is the work.
STATES = ((WAITING, "Javob kutmoqda"), (EVERYONE, "Hammasi"))
SOCKET_PATH = "/api/v1/office/support/{id}/ws"


def file_answerer(db: Db, user: User = Depends(file_reader)) -> User:
    """``?token=`` too, for a link the browser opens itself; 404 without the role."""
    if not has_role(db, user, ANSWER_ROLES):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


FileAnswer = Annotated[User, Depends(file_answerer)]


def _thread(db: Session, conversation_id: uuid.UUID) -> SupportConversation:
    chat = selectors.staff_conversation(db, pk=conversation_id)
    if chat is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return chat


def _client(db: Session, customer_id: uuid.UUID) -> User:
    client = person(db, customer_id=customer_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return client


def _tickets(
    db: Session, owner_ids: list[uuid.UUID], *, viewer: User
) -> dict[uuid.UUID, dict[str, Any]]:
    """Each client's Support ticket, as the chat shows it: where it stands
    and who holds it."""
    from app.modules.boards.constants import (
        SUPPORT_COLUMN_LABELS,
        SUPPORT_FINAL_COLUMNS,
        Board,
        SupportColumn,
    )
    from app.modules.boards.models import BoardCard

    if not owner_ids:
        return {}
    cards = db.scalars(
        select(BoardCard).where(
            BoardCard.board == str(Board.SUPPORT),
            BoardCard.owner_id.in_(owner_ids),
            BoardCard.term_ends_at.is_(None),
        )
    ).all()
    people = {
        p.id: p
        for p in db.scalars(
            select(User).where(
                User.id.in_({c.manager_id for c in cards if c.manager_id})
            )
        )
    }
    out: dict[uuid.UUID, dict[str, Any]] = {}
    for card in cards:
        manager = people.get(card.manager_id) if card.manager_id else None
        column = card.column_code
        label = (
            SUPPORT_COLUMN_LABELS[SupportColumn(column)]
            if column in SupportColumn.values
            else column
        )
        out[card.owner_id] = {
            "id": str(card.id),
            "column": column,
            "column_label": str(label),
            "manager": person_out(manager) if manager else None,
            "mine": card.manager_id == viewer.id,
            "closed": column in SUPPORT_FINAL_COLUMNS,
        }
    return out


def _row_out(
    row: selectors.QueueRow,
    drawn: selectors.Drawn,
    tickets: dict[uuid.UUID, dict[str, Any]],
) -> dict[str, Any]:
    chat, last = row.conversation, row.last
    return {
        "id": str(chat.id),
        "customer": person_out(chat.owner),
        "ticket": tickets.get(chat.owner_id),
        "waiting": row.waiting,
        "last_message_at": chat.last_message_at,
        "last_client_at": chat.last_client_at,
        "preview": (
            preview_text(last, drawn.files.get(last.id, []))[:160] if last else ""
        ),
        "last_side": side_of(last) if last is not None else "",
    }


def _span(
    db: Session,
    *,
    client: User,
    chat: SupportConversation | None,
    shown: selectors.MessagePage,
) -> tuple[datetime | None, datetime | None]:
    """The time this page of the support chat covers: from its first
    message (from the start on the first page) to the next page's first
    (to now on the last). The assistant's rows in it go with the page."""
    from app.modules.supportchat.constants import MESSAGE_PAGE_SIZE

    rows = shown.drawn.messages
    since = rows[0].created_at if shown.has_previous and rows else None
    until = None
    if chat is not None and shown.has_next:
        until = db.scalar(
            select(SupportMessage.created_at)
            .where(
                SupportMessage.owner_id == client.id,
                SupportMessage.conversation_id == chat.id,
            )
            .order_by(SupportMessage.created_at, SupportMessage.id)
            .offset(shown.number * MESSAGE_PAGE_SIZE)
            .limit(1)
        )
    return since, until


def _hold_out(db: Session, *, client: User, viewer: User) -> dict[str, Any]:
    state = chat_hold.seen_by(db, client=client, user=viewer)
    return {
        "holder": person_out(state.hold.holder) if state.hold else None,
        "since": state.hold.since if state.hold else None,
        "mine": state.mine,
        "can_take": state.can_take,
        "can_release": state.can_release,
        "can_hand": state.can_hand,
        "busy_with": state.busy_with,
    }


def _screen(
    db: Session,
    *,
    client: User,
    chat: SupportConversation | None,
    page: str | None,
    viewer: User,
) -> dict[str, Any]:
    from app.modules.assistant.selectors.office import assistant_rows

    shown = selectors.messages_page(db, owner=client, conversation=chat, page=page)
    since, until = _span(db, client=client, chat=chat, shown=shown)
    return jsonable_encoder(
        {
            "customer": person_out(client),
            "ticket": _tickets(db, [client.id], viewer=viewer).get(client.id),
            "support_bot": _support_bot(db, client),
            "conversation_id": str(chat.id) if chat is not None else None,
            "waiting": chat is not None and selectors.is_waiting(conversation=chat),
            "messages": (
                selectors.message_views(
                    shown.drawn, conversation=chat, viewer=OFFICE, now=utcnow()
                )
                if chat is not None
                else []
            ),
            "page": shown.number,
            "pages": shown.pages,
            "has_previous": shown.has_previous,
            "has_next": shown.has_next,
            "client_read_at": chat.client_read_at if chat is not None else None,
            "send_key": uuid.uuid4().hex,
            "ws_path": SOCKET_PATH.format(id=chat.id) if chat is not None else "",
            "composer": composer(),
            "chat": _hold_out(db, client=client, viewer=viewer),
            "assistant": assistant_rows(
                db, owner_id=client.id, since=since, until=until
            ),
        }
    )


def _support_bot(db: Session, client: User) -> dict[str, Any] | None:
    row = last_support_bot_chat_for(db, owner=client)
    if row is None:
        return None
    return {
        "linked": row.is_active,
        "username": row.username,
        "last_error": row.last_error,
    }


def _drawn_one(db: Session, message: SupportMessage) -> dict[str, Any]:
    chat = _thread(db, message.conversation_id)
    return jsonable_encoder(
        selectors.message_view(
            message,
            drawn=selectors.drawn(db, [message]),
            conversation=chat,
            viewer=OFFICE,
            now=utcnow(),
        )
    )


def _draft(
    *,
    body: str,
    attachments: list[UploadFile] | None,
    voice: UploadFile | None,
    voice_seconds: int | None,
    sticker: str,
    reply_to: str,
) -> Draft:
    files = [item for item in attachments or [] if item.filename]
    recording = voice if voice is not None and voice.filename else None
    check_box(body=body, files=files, voice_seconds=voice_seconds)
    return Draft(
        body=body,
        files=tuple(files),
        voice=Voice(upload=recording, seconds=voice_seconds or 0)
        if recording is not None
        else None,
        sticker=sticker,
        reply_to=reply_to,
    )


Body = Annotated[str, Form(description="The words.")]
Attachments = Annotated[
    list[UploadFile] | None, File(description="Up to 10 pictures, videos, documents.")
]
Recording = Annotated[UploadFile | None, File(description="webm, ogg, m4a or mp3.")]
Seconds = Annotated[int | None, Form(description="The recording's length.")]
Sticker = Annotated[str, Form(max_length=32, description="A sticker code.")]
ReplyTo = Annotated[str, Form(max_length=64, description="The message answered.")]
SendKey = Annotated[str, Form(max_length=64, description="The screen's `send_key`.")]
Nonce = Annotated[str, Form(max_length=64, description="Echoed on the socket.")]


@router.get("", responses={200: {"model": SupportQueueOut}})
def support_queue(
    db: Db,
    user: Answer,
    state: str = Query(WAITING, description="`waiting` (default) or `all`."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """One row per client who has written; the waiting ones by default."""
    asked = EVERYONE if state == EVERYONE else WAITING
    page = selectors.staff_conversations(db, state=asked, offset=offset)
    drawn = selectors.drawn(db, [row.last for row in page.rows if row.last])
    tickets = _tickets(
        db, [row.conversation.owner_id for row in page.rows], viewer=user
    )
    return jsonable_encoder(
        {
            "state": asked,
            "states": choices(STATES),
            "rows": [_row_out(row, drawn, tickets) for row in page.rows],
            "total": page.total,
            "offset": page.offset,
            "next_offset": page.next_offset,
            "has_more": page.has_more,
        }
    )


@router.get("/customers/{customer_id}", responses={200: {"model": SupportThreadOut}})
def support_client(customer_id: uuid.UUID, db: Db, user: Answer) -> dict[str, Any]:
    """This client's chat, or the empty one the first message will write.
    Opening an existing chat reads it, as ``GET /support/{id}`` does."""
    client = _client(db, customer_id)
    chat = selectors.chat_of(db, owner=client)
    if chat is not None:
        return support_thread(chat.id, db, user, page=None)
    return _screen(db, client=client, chat=None, page=None, viewer=user)


@router.post(
    "/customers/{customer_id}/messages",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": SentOut}},
)
def support_start(
    customer_id: uuid.UUID,
    db: Db,
    actor: Answer,
    body: Body = "",
    attachments: Attachments = None,
    voice: Recording = None,
    voice_seconds: Seconds = None,
    sticker: Sticker = "",
    reply_to: ReplyTo = "",
) -> dict[str, Any]:
    """The office's first message to a client, which writes their chat."""
    client = _client(db, customer_id)
    draft = _draft(
        body=body,
        attachments=attachments,
        voice=voice,
        voice_seconds=voice_seconds,
        sticker=sticker,
        reply_to=reply_to,
    )
    message = services.write_to_client(
        db, client=client, sender=actor, draft=draft, now=utcnow()
    )
    broadcast_message(message=message)
    return {"already_sent": False, "message": _drawn_one(db, message)}


class HandIn(BaseModel):
    staff_id: uuid.UUID = Field(
        description="Somebody in Support (`/office/boards/staff`)."
    )


def _held(db: Session, *, client: User, viewer: User) -> dict[str, Any]:
    db.commit()
    return jsonable_encoder(_hold_out(db, client=client, viewer=viewer))


@router.post(
    "/customers/{customer_id}/chat/take", responses={200: {"model": ChatHoldOut}}
)
def chat_take(customer_id: uuid.UUID, db: Db, user: Answer) -> dict[str, Any]:
    """«Men javob beraman»: from now this person answers the client and the
    assistant does not. Their ticket, opened if there is none, is theirs
    too. 409 when somebody else works with the client (the Owner may take
    it from them), or at «Zayavka olish»'s limit."""
    client = _client(db, customer_id)
    chat_hold.take_chat(db, client=client, user=user, now=utcnow())
    return _held(db, client=client, viewer=user)


@router.post(
    "/customers/{customer_id}/chat/hand", responses={200: {"model": ChatHoldOut}}
)
def chat_hand(
    customer_id: uuid.UUID, body: HandIn, db: Db, user: Answer
) -> dict[str, Any]:
    """The Owner gives the chat, with the ticket, to somebody in Support."""
    client = _client(db, customer_id)
    chat_hold.hand_chat(db, client=client, user=user, to_id=body.staff_id, now=utcnow())
    return _held(db, client=client, viewer=user)


@router.post(
    "/customers/{customer_id}/chat/release", responses={200: {"model": ChatHoldOut}}
)
def chat_release(customer_id: uuid.UUID, db: Db, user: Answer) -> dict[str, Any]:
    """«AI ga qaytarish»: the assistant answers the client again. The person
    who has the chat, or the Owner; the ticket stays where it is."""
    client = _client(db, customer_id)
    chat_hold.release_chat(db, client=client, user=user, now=utcnow())
    return _held(db, client=client, viewer=user)


@router.get("/{conversation_id}", responses={200: {"model": SupportThreadOut}})
def support_thread(
    conversation_id: uuid.UUID,
    db: Db,
    user: Answer,
    page: str | None = Query(None, description="Page number; the newest if empty."),
) -> dict[str, Any]:
    """One client's chat, read by the office - and journalled as read."""
    chat = _thread(db, conversation_id)
    client = chat.owner
    seen(db, customer=client, actor=user, kind=ActionKind.SUPPORT_VIEW)
    now = utcnow()
    if services.mark_read(db, conversation=chat, reader=user, now=now):
        set_committed_value(chat, "office_read_at", now)
        broadcast_read(owner_id=client.id, side=OFFICE, at=now)
    db.commit()
    return _screen(db, client=client, chat=chat, page=page, viewer=user)


@router.post(
    "/{conversation_id}/messages",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": SentOut}},
)
def support_send(
    conversation_id: uuid.UUID,
    db: Db,
    actor: Answer,
    body: Body = "",
    attachments: Attachments = None,
    voice: Recording = None,
    voice_seconds: Seconds = None,
    sticker: Sticker = "",
    reply_to: ReplyTo = "",
    send_key: SendKey = "",
    nonce: Nonce = "",
) -> dict[str, Any]:
    """A reply from the office, once per `send_key`."""
    chat = _thread(db, conversation_id)
    draft = _draft(
        body=body,
        attachments=attachments,
        voice=voice,
        voice_seconds=voice_seconds,
        sticker=sticker,
        reply_to=reply_to,
    )
    try:
        message = services.post_message(
            db,
            conversation=chat,
            sender=actor,
            draft=draft,
            now=utcnow(),
            send_key=send_key,
        )
    except AlreadySent:
        return {"already_sent": True, "message": None}
    broadcast_message(message=message, nonce=nonce)
    return {"already_sent": False, "message": _drawn_one(db, message)}


@router.post("/{conversation_id}/settle", responses={200: {"model": MessageOut}})
def support_settle(conversation_id: uuid.UUID, db: Db, actor: Answer) -> dict[str, Any]:
    """Out of the queue: the client's last words need no answer. The client
    sees nothing; their next message brings it back."""
    services.settle_conversation(
        db, conversation=_thread(db, conversation_id), actor=actor, now=utcnow()
    )
    return {"message": "Navbatdan olindi."}


class EditIn(BaseModel):
    body: str = Field("", description="The new words.")


@router.patch("/messages/{message_id}", responses={200: {"model": ChatMessageOut}})
def support_edit(
    message_id: uuid.UUID, body: EditIn, db: Db, actor: Answer
) -> dict[str, Any]:
    """New words on one's own reply."""
    message = services.edit_message(
        db, message_id=message_id, sender=actor, body=body.body, now=utcnow()
    )
    broadcast_change(message=message)
    return _drawn_one(db, message)


@router.delete("/messages/{message_id}", responses={200: {"model": ChatMessageOut}})
def support_delete(message_id: uuid.UUID, db: Db, actor: Answer) -> dict[str, Any]:
    """Taking back one's own reply."""
    message = services.delete_message(
        db, message_id=message_id, sender=actor, now=utcnow()
    )
    broadcast_change(message=message)
    return _drawn_one(db, message)


@router.get("/messages/{message_id}/file", response_class=Response)
def support_file(
    message_id: uuid.UUID,
    db: Db,
    user: FileAnswer,
    view: str = Query("", description="`1`: show it in the page."),
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """A file out of any client's chat, with the reading journalled."""
    message = selectors.staff_message_for_download(db, message_id=message_id)
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    seen(db, customer=message.owner, actor=user, kind=ActionKind.SUPPORT_FILE)
    db.commit()
    return attachment_response(
        message=message, view=bool(view), range_header=range_header
    )


@router.get("/files/{attachment_id}", response_class=Response)
def support_attachment(
    attachment_id: uuid.UUID,
    db: Db,
    user: FileAnswer,
    view: str = Query("", description="`1`: show it in the page."),
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """One of a message's files, out of any client's chat, journalled."""
    attachment = selectors.staff_attachment_for_download(
        db, attachment_id=attachment_id
    )
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    seen(db, customer=attachment.owner, actor=user, kind=ActionKind.SUPPORT_FILE)
    db.commit()
    return stored_file_response(
        attachment=attachment, view=bool(view), range_header=range_header
    )


router.add_api_websocket_route("/{conversation_id}/ws", office_socket)
