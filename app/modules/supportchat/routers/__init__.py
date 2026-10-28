"""The client's side of the support chat ("Yordam"): their one chat with the office.

Only the client's own - no chat id in any address: every client has exactly
one chat, and whose it is comes from the token. The office answers from
its console, which is not here.

Live updates come over the socket (``/support/ws``, see ``routers/live``);
a client without one polls ``GET /support/messages?after=<cursor>``.
"""

import uuid
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.api.deps import CurrentUser, Db, current_user
from app.common.db import get_db, utcnow
from app.common.exceptions import NotFound
from app.modules.accounts.models import User
from app.modules.supportchat import selectors, services
from app.modules.supportchat.constants import (
    ALLOWED_UPLOAD_SUFFIXES,
    ALLOWED_VOICE_SUFFIXES,
    CLIENT,
    MAX_BODY_CHARS,
    MAX_FILES_PER_MESSAGE,
    MAX_SEND_BYTES,
    MAX_SEND_MB,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    MAX_VOICE_SECONDS,
    STICKERS,
    TYPING_BEAT_MS,
    TYPING_SHOWN_MS,
)
from app.modules.supportchat.drafts import Draft, Voice
from app.modules.supportchat.exceptions import (
    AlreadySent,
    MessageTooLong,
    SendTooLarge,
    TooManyFiles,
    UnsupportedFileType,
    UploadTooLarge,
    VoiceRefused,
)
from app.modules.supportchat.files import attachment_response, stored_file_response
from app.modules.supportchat.live import (
    CLIENT_SOCKET_PATH,
    broadcast_change,
    broadcast_message,
    broadcast_read,
)
from app.modules.supportchat.models import SupportConversation
from app.modules.supportchat.preview import preview_text
from app.modules.supportchat.routers.live import support_socket
from app.modules.supportchat.schemas import (
    ChangesOut,
    MessageOut,
    ScreenOut,
    SentOut,
    WidgetOut,
)
from app.modules.supportchat.services._files import upload_size

router = APIRouter(prefix="/support", tags=["support"])

PAGE_Q = Query(None, description="Page number; the newest page when empty.")
TOKEN_Q = Query("", description="The access token, for an `<img>` or `<video>`.")
VIEW_Q = Query("", description="`1`: show a picture, video or voice in the page.")


def file_reader(
    request: Request,
    db: Session = Depends(get_db),
    token: str = TOKEN_Q,
) -> User:
    """The bearer header, or ``?token=`` for a link the browser opens itself."""
    header = request.headers.get("authorization", "")
    raw = (
        header.removeprefix("Bearer ").strip()
        if header.startswith("Bearer ")
        else token
    )
    credentials = (
        HTTPAuthorizationCredentials(scheme="Bearer", credentials=raw) if raw else None
    )
    return current_user(request, credentials, db)


FileReader = Annotated[User, Depends(file_reader)]


def _us(moment: datetime | None) -> int:
    return int(moment.timestamp() * 1_000_000) if moment is not None else 0


def _cursor(db: Session, *, owner: User, chat: SupportConversation | None) -> str:
    """Moves when a message is written or changed, or the office reads."""
    if chat is None:
        return ""
    changed = selectors.last_change(db, owner=owner, conversation=chat)
    return f"{_us(changed)}.{_us(chat.office_read_at)}"


def _since(cursor: str) -> datetime | None:
    head = cursor.split(".", 1)[0]
    if not head.isdigit() or not int(head):
        return None
    return datetime.fromtimestamp(int(head) / 1_000_000, tz=UTC)


def _read(db: Session, *, owner: User, chat: SupportConversation | None) -> None:
    """The client has the chat in front of them; the office's ticks turn."""
    if chat is None:
        return
    now = utcnow()
    if services.mark_read(db, conversation=chat, reader=owner, now=now):
        set_committed_value(chat, "client_read_at", now)
        broadcast_read(owner_id=owner.id, side=CLIENT, at=now)


def _composer() -> dict[str, Any]:
    return {
        "max_body_chars": MAX_BODY_CHARS,
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_send_mb": MAX_SEND_MB,
        "max_files": MAX_FILES_PER_MESSAGE,
        "max_voice_seconds": MAX_VOICE_SECONDS,
        "typing_beat_ms": TYPING_BEAT_MS,
        "typing_shown_ms": TYPING_SHOWN_MS,
        "allowed_suffixes": sorted(ALLOWED_UPLOAD_SUFFIXES),
        "voice_suffixes": sorted(ALLOWED_VOICE_SUFFIXES),
        "stickers": [
            {"code": code, "emoji": emoji, "name": name}
            for code, emoji, name in STICKERS
        ],
    }


def _screen(db: Session, *, owner: User, page: str | None) -> dict[str, Any]:
    """The chat with its messages and the box. Opening it reads it."""
    chat = selectors.chat_of(db, owner=owner)
    _read(db, owner=owner, chat=chat)
    shown = selectors.messages_page(db, owner=owner, conversation=chat, page=page)
    now = utcnow()
    return jsonable_encoder(
        {
            "page_title": "Yordam",
            "viewer": CLIENT,
            "has_chat": chat is not None,
            "messages": selectors.message_views(
                shown.drawn, conversation=chat, viewer=CLIENT, now=now
            )
            if chat is not None
            else [],
            "page": shown.number,
            "pages": shown.pages,
            "has_previous": shown.has_previous,
            "has_next": shown.has_next,
            "cursor": _cursor(db, owner=owner, chat=chat),
            "office_read_at": chat.office_read_at if chat is not None else None,
            "send_key": uuid.uuid4().hex,
            "ws_path": CLIENT_SOCKET_PATH,
            "composer": _composer(),
        }
    )


@router.get("", responses={200: {"model": ScreenOut}})
def support_chat(
    db: Db, user: CurrentUser, page: str | None = PAGE_Q
) -> dict[str, Any]:
    """The client's one chat, a page at a time. Opening it reads it."""
    return _screen(db, owner=user, page=page)


@router.get("/panel", responses={200: {"model": ScreenOut}})
def support_panel(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The same chat for the corner widget's panel: only the newest page."""
    return _screen(db, owner=user, page=None)


@router.get("/widget", responses={200: {"model": WidgetOut}})
def support_widget(db: Db, user: CurrentUser) -> dict[str, Any]:
    """What the corner widget shows before anybody opens it. Reads nothing."""
    chat = selectors.chat_of(db, owner=user)
    if chat is None:
        return {"has_chat": False, "unread": False, "preview": ""}
    unread = selectors.is_unread(conversation=chat)
    reply = selectors.last_office_reply(db, owner=user) if unread else None
    preview = ""
    if reply is not None:
        drawn = selectors.drawn(db, [reply])
        preview = preview_text(reply, drawn.files.get(reply.id, []))
    return {"has_chat": True, "unread": unread, "preview": preview}


@router.get(
    "/messages",
    response_model=None,
    responses={
        200: {"model": ChangesOut, "description": "Something changed."},
        204: {"description": "Nothing changed since `after`."},
    },
)
def support_changes(
    db: Db,
    user: CurrentUser,
    after: str = Query("", description="The `cursor` from the last answer."),
    watch: bool = Query(
        False, description="Only listening (the widget): do not mark the chat read."
    ),
) -> dict[str, Any] | Response:
    """The poll for a page without a socket: what is new or changed."""
    chat = selectors.chat_of(db, owner=user)
    cursor = _cursor(db, owner=user, chat=chat)
    if chat is None or cursor == after:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    changed = selectors.changed_since(
        db, owner=user, conversation=chat, since=_since(after)
    )
    if not watch and changed.messages:
        _read(db, owner=user, chat=chat)
    return jsonable_encoder(
        {
            "cursor": cursor,
            "messages": selectors.message_views(
                changed, conversation=chat, viewer=CLIENT, now=utcnow()
            ),
            "office_read_at": chat.office_read_at,
        }
    )


def _drawn_one(db: Session, *, owner: User, message_id: uuid.UUID) -> dict[str, Any]:
    message = selectors.message_in_chat(db, owner_id=owner.id, message_id=message_id)
    chat = selectors.chat_of(db, owner=owner)
    if message is None or chat is None:
        raise NotFound("Xabar topilmadi.")
    drawn = selectors.drawn(db, [message])
    return jsonable_encoder(
        selectors.message_view(
            message,
            drawn=drawn,
            conversation=chat,
            viewer=CLIENT,
            now=utcnow(),
        )
    )


def _check_box(
    *, body: str, files: list[UploadFile], voice_seconds: int | None
) -> None:
    """The composer's own checks, in its order, before the service's."""
    if len(body.strip()) > MAX_BODY_CHARS:
        raise MessageTooLong(MAX_BODY_CHARS)
    for upload in files:
        suffix = PurePosixPath(upload.filename or "").suffix[1:].lower()
        if suffix not in ALLOWED_UPLOAD_SUFFIXES:
            raise UnsupportedFileType
    if len(files) > MAX_FILES_PER_MESSAGE:
        raise TooManyFiles(MAX_FILES_PER_MESSAGE)
    sizes = [upload_size(upload) for upload in files]
    if any(size > MAX_UPLOAD_BYTES for size in sizes):
        raise UploadTooLarge(MAX_UPLOAD_MB)
    if sum(sizes) > MAX_SEND_BYTES:
        raise SendTooLarge(MAX_SEND_MB)
    if voice_seconds is not None and not 1 <= voice_seconds <= MAX_VOICE_SECONDS:
        raise VoiceRefused(MAX_VOICE_SECONDS)


@router.post(
    "/messages",
    status_code=status.HTTP_201_CREATED,
    responses={201: {"model": SentOut}},
)
def send_message(
    db: Db,
    user: CurrentUser,
    body: Annotated[str, Form(description="The words.")] = "",
    attachments: Annotated[
        list[UploadFile] | None,
        File(description="Up to 10 pictures, videos or documents."),
    ] = None,
    voice: Annotated[
        UploadFile | None, File(description="A recording: webm, ogg, m4a or mp3.")
    ] = None,
    voice_seconds: Annotated[
        int | None, Form(description="The recording's length, as the page measured.")
    ] = None,
    sticker: Annotated[str, Form(max_length=32, description="A sticker code.")] = "",
    reply_to: Annotated[
        str, Form(max_length=64, description="The id of the message answered.")
    ] = "",
    send_key: Annotated[
        str, Form(max_length=64, description="The screen's `send_key`.")
    ] = "",
    nonce: Annotated[
        str, Form(max_length=64, description="Echoed on the socket's `message`.")
    ] = "",
) -> dict[str, Any]:
    """Store one message in the client's chat - writing the chat on the
    first one - and announce it to its sockets."""
    files = [item for item in attachments or [] if item.filename]
    recording = voice if voice is not None and voice.filename else None
    _check_box(body=body, files=files, voice_seconds=voice_seconds)
    draft = Draft(
        body=body,
        files=tuple(files),
        voice=Voice(upload=recording, seconds=voice_seconds or 0)
        if recording is not None
        else None,
        sticker=sticker,
        reply_to=reply_to,
    )
    try:
        message = services.send_to_support(
            db, owner=user, draft=draft, now=utcnow(), send_key=send_key
        )
    except AlreadySent:
        # The first press is stored; this one only needs the chat.
        return {"already_sent": True, "message": None}
    broadcast_message(message=message, nonce=nonce)
    return {
        "already_sent": False,
        "message": _drawn_one(db, owner=user, message_id=message.id),
    }


class EditIn(BaseModel):
    body: str = Field("", description="The new words.")


@router.patch("/messages/{message_id}", responses={200: {"model": MessageOut}})
def edit(
    message_id: uuid.UUID, body: EditIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """New words on the client's own message, within a day of sending it."""
    message = services.edit_message(
        db, message_id=message_id, sender=user, body=body.body, now=utcnow()
    )
    broadcast_change(message=message)
    return _drawn_one(db, owner=user, message_id=message.id)


@router.delete("/messages/{message_id}", responses={200: {"model": MessageOut}})
def delete(message_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """The client taking back their own message, within a day of sending it."""
    message = services.delete_message(
        db, message_id=message_id, sender=user, now=utcnow()
    )
    broadcast_change(message=message)
    return _drawn_one(db, owner=user, message_id=message.id)


@router.get("/messages/{message_id}/file", response_class=Response)
def download_attachment(
    message_id: uuid.UUID,
    db: Db,
    user: FileReader,
    view: str = VIEW_Q,
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """A file from before messages carried several, for its client's eyes."""
    message = selectors.message_for_download(db, owner=user, message_id=message_id)
    if message is None:
        raise NotFound("Fayl topilmadi.")
    return attachment_response(
        message=message, view=bool(view), range_header=range_header
    )


@router.get("/files/{attachment_id}", response_class=Response)
def download_file(
    attachment_id: uuid.UUID,
    db: Db,
    user: FileReader,
    view: str = VIEW_Q,
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """One of a message's files, for its client's eyes."""
    attachment = selectors.attachment_for_download(
        db, owner=user, attachment_id=attachment_id
    )
    if attachment is None:
        raise NotFound("Fayl topilmadi.")
    return stored_file_response(
        attachment=attachment, view=bool(view), range_header=range_header
    )


router.add_api_websocket_route("/ws", support_socket)
