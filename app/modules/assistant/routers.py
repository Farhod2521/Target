"""The one chat's HTTP surface, under ``/api/v2/assistant``.

A thread holds the assistant's answers and the replies of a person in
Support. A question goes to ``POST /ask`` and its answer is read from
``GET /stream/{turn_id}``; words for a person go to ``POST /support``; what
an answer offers is pressed at ``POST /buttons/{message_id}/{key}``. A
visitor asks without a token and leaves a phone at ``POST /guest-ticket``.

The old ``/api/v1/chat`` and ``/api/v1/support`` are not touched.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime, timedelta
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db, OptionalUser, client_address
from app.common import tokens
from app.common.cache import cache
from app.common.dates import localtime
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.assistant.constants import (
    MAX_QUESTION_CHARS,
    OUT_KEY,
    PAGE_MESSAGES,
    POLL_SECONDS,
    STREAM_TIMEOUT_SECONDS,
)
from app.modules.assistant.models import AssistantMessage, AssistantSession
from app.modules.assistant.selectors import threads
from app.modules.assistant.services import buttons, support
from app.modules.assistant.services import threads as thread_service
from app.modules.backoffice.constants import ANSWER_ROLES
from app.modules.backoffice.permissions import staff_required

router = APIRouter(prefix="/assistant", tags=["assistant"])
office = APIRouter(prefix="/office/help-articles", tags=["assistant office"])
Writer = Annotated[User, Depends(staff_required(*ANSWER_ROLES))]


# -- shapes, for the API reference ------------------------------------------


class ButtonOut(BaseModel):
    kind: str = Field(description="`ticket`, `change`, `offer` or `guest_ticket`.")
    key: str
    label: str = ""
    state: str = Field(
        description="`open`, `sent`, `working`, `done`, `refused`, `dismissed` or `gone`."
    )
    state_text: str = ""


class MessageOut(BaseModel):
    id: str
    author: str = Field(description="`user`, `ai` or `staff` (a person in Support).")
    text: str
    html: str
    status: str = Field(description="`pending`, `done` or `failed`.")
    masked_figures: int
    buttons: list[dict[str, Any]] = Field(
        description="What can be pressed, each with its `state` and `state_text` as of now."
    )
    replies: list[str] = Field(description="Short answers offered as the next words.")
    meta: dict[str, Any] = Field(
        description="`author` (a person's first name) on a `staff` row; `quote` on a "
        "question that replied to a waiting-list line; `stopped: true` on an answer "
        "the client stopped."
    )
    to_support: bool = Field(description="A client's words that went to a person.")
    support: dict[str, Any] | None = Field(
        description="On a row that is a support-chat message: the support chat's own "
        "drawing of it - `files` with `url`, `kind`, `sticker_emoji`, `edited_at`, "
        "`read`, `editable`, `deletable`. Change it with "
        "`PATCH`/`DELETE /api/v1/support/messages/{support.id}`."
    )
    created_at: datetime


class ThreadOut(BaseModel):
    id: str
    title: str
    last_message_at: datetime | None
    created_at: datetime
    support: bool = Field(description="Support is, or was, part of this thread.")


class SupportOut(BaseModel):
    thread_id: str = Field(description="Where a person's next reply is shown.")
    unread: bool = Field(description="A person replied and it was not seen yet.")
    waiting: bool = Field(
        description="The client's last words to a person wait for one."
    )
    ws_path: str = Field(
        description="The support chat's socket: a `message` event "
        "means read the thread again."
    )
    send_key: str
    composer: dict[str, Any] = Field(description="Limits for `POST /support`.")


class ScreenOut(BaseModel):
    entitled: bool = Field(description="False: no live plan - only a person answers.")
    has_earlier: bool = Field(
        description="Older rows are left: read them with `GET /threads/{id}/messages"
        "?before=<the first row's id>`."
    )
    mode: str = Field(
        description="`ai`: send with `POST /ask`; `support`: send with "
        "`POST /support`. The page may let the client switch."
    )
    sessions: list[ThreadOut]
    thread: ThreadOut | None
    messages: list[MessageOut]
    support: SupportOut
    questions_left: int
    questions_total: int
    questions_reset_at: datetime = Field(
        description="When `questions_left` is full again: the next midnight, Tashkent."
    )


class PageOut(BaseModel):
    messages: list[MessageOut]
    has_earlier: bool


class RenameIn(BaseModel):
    title: str = Field(max_length=200)


class StopOut(BaseModel):
    stopped: bool = Field(
        description="False: nothing to stop - finished already, or not yours."
    )


class AskIn(BaseModel):
    question: str = Field(default="", max_length=MAX_QUESTION_CHARS * 2)
    session: str = Field("", description="The thread; empty starts one.")
    item: str = Field(
        "", description="A waiting-list line's key the question replies to."
    )
    suggestion: str = Field("", description="A proposal's id the question is about.")
    asked: list[str] = Field(
        default_factory=list,
        max_length=50,
        description="A visitor's own earlier questions, from their browser.",
    )
    guest_id: str = Field("", max_length=64, description="A visitor's browser id.")


class TurnOut(BaseModel):
    turn_id: str
    session_id: str
    message_id: str
    left: int


class PressOut(BaseModel):
    kind: str
    key: str
    state: str
    text: str


class SentOut(BaseModel):
    already_sent: bool = False
    session_id: str
    message: MessageOut | None
    send_key: str = Field(description="The key for the next `POST /support`.")


class GuestTicketIn(BaseModel):
    turn_id: str = Field(
        max_length=64, description="The answer that offered `guest_ticket`."
    )
    name: str = Field("", max_length=200)
    phone: str = Field("", max_length=40)
    email: str = Field("", max_length=254, description="Optional.")


class GuestTicketOut(BaseModel):
    token: str = Field(description="`X-Guest-Token` for `/api/v1/support/guest`.")
    chat: dict[str, Any]


# -- the client's chat ------------------------------------------------------


def _entitled(db: Session, owner: User) -> bool:
    from app.modules.billing.selectors import has_live_subscription

    return has_live_subscription(db, owner=owner)


def _thread_row(row: AssistantSession) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "last_message_at": row.last_message_at,
        "created_at": row.created_at,
        "support": row.support_at is not None,
    }


def _message_row(
    db: Session,
    *,
    owner: User,
    row: AssistantMessage,
    view: dict[str, Any] | None,
    now: datetime,
    last: bool = True,
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "author": row.author,
        "text": row.text,
        "html": row.html,
        "status": row.status,
        "masked_figures": row.masked_figures,
        "buttons": buttons.buttons_of(db, owner=owner, row=row, now=now),
        # Replies are the next words: only the newest answer offers them.
        "replies": list(row.replies or ()) if last else [],
        "meta": row.meta or {},
        "to_support": support.is_to_support(row),
        "support": view,
        "created_at": row.created_at,
    }


def _support_block(db: Session, *, owner: User) -> dict[str, Any]:
    from app.modules.supportchat.live import CLIENT_SOCKET_PATH
    from app.modules.supportchat.routers import composer

    state = support.state_for(db, owner=owner)
    return {
        "thread_id": state.thread_id,
        "unread": state.unread,
        "waiting": state.waiting,
        "ws_path": CLIENT_SOCKET_PATH,
        "send_key": uuid.uuid4().hex,
        "composer": composer(),
    }


def _rows(
    db: Session,
    *,
    owner: User,
    rows: list[AssistantMessage],
    now: datetime,
    newest: bool,
) -> list[dict[str, Any]]:
    """Rows as the screen draws them. ``newest``: these end the thread, so
    the last one may offer replies."""
    views = support.views(db, owner=owner, messages=rows, now=now)
    return [
        _message_row(
            db,
            owner=owner,
            row=row,
            view=views.get(row.id),
            now=now,
            last=newest and index == len(rows) - 1,
        )
        for index, row in enumerate(rows)
    ]


def _next_midnight(now: datetime) -> datetime:
    """When the plan's daily questions are counted from zero again."""
    local = localtime(now)
    return (local + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _screen(
    db: Session, *, owner: User, thread: AssistantSession | None
) -> dict[str, Any]:
    from app.modules.assistant.services.ask import questions_left

    now = utcnow()
    entitled = _entitled(db, owner)
    if thread is None:
        support.ensure_thread(db, owner=owner, now=now)
    else:
        support.read(db, owner=owner, thread=thread)
    rows, has_earlier = (
        threads.messages_page(db, owner=owner, session=thread)
        if thread
        else ([], False)
    )
    left, total = questions_left(db, owner=owner, entitled=entitled, now=now)
    return jsonable_encoder(
        {
            "entitled": entitled,
            "has_earlier": has_earlier,
            "mode": support.thread_mode(
                db,
                owner=owner,
                thread=thread,
                messages=rows,
                entitled=entitled,
                now=now,
            ),
            "sessions": [
                _thread_row(row) for row in threads.sessions_for(db, owner=owner)
            ],
            "thread": _thread_row(thread) if thread is not None else None,
            "messages": _rows(db, owner=owner, rows=rows, now=now, newest=True),
            "support": _support_block(db, owner=owner),
            "questions_left": left,
            "questions_total": total,
            "questions_reset_at": _next_midnight(now),
        }
    )


@router.get("", response_model=ScreenOut)
def screen(db: Db, user: CurrentUser) -> dict[str, Any]:
    """The rail of threads and an empty box. A client who talked to Support
    before has that chat brought in as a thread called «Yordam»."""
    return _screen(db, owner=user, thread=None)


@router.get("/threads/{pk}", response_model=ScreenOut)
def thread(pk: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    """One thread. Opening one with a person's reply in it reads it."""
    found = threads.session_for(db, owner=user, pk=pk)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suhbat topilmadi.")
    return _screen(db, owner=user, thread=found)


def _found(db: Session, *, owner: User, pk: uuid.UUID) -> AssistantSession:
    found = threads.session_for(db, owner=owner, pk=pk)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suhbat topilmadi.")
    return found


@router.get("/threads/{pk}/messages", response_model=PageOut)
def earlier(
    pk: uuid.UUID,
    db: Db,
    user: CurrentUser,
    before: uuid.UUID = Query(description="The oldest row the page has."),
) -> dict[str, Any]:
    """The rows written before ``before``, oldest first, as many as the
    screen brings at a time."""
    found = _found(db, owner=user, pk=pk)
    oldest = threads.message_for(db, owner=user, pk=before)
    if oldest is None or oldest.session_id != found.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Xabar topilmadi.")
    rows, has_earlier = threads.messages_page(
        db, owner=user, session=found, before=oldest, limit=PAGE_MESSAGES
    )
    return jsonable_encoder(
        {
            "messages": _rows(db, owner=user, rows=rows, now=utcnow(), newest=False),
            "has_earlier": has_earlier,
        }
    )


@router.patch("/threads/{pk}", response_model=ThreadOut)
def rename_thread(
    pk: uuid.UUID, body: RenameIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """The client's own name for a thread."""
    found = thread_service.rename(
        db, thread=_found(db, owner=user, pk=pk), title=body.title
    )
    db.commit()
    return jsonable_encoder(_thread_row(found))


@router.delete("/threads/{pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(pk: uuid.UUID, db: Db, user: CurrentUser) -> None:
    """The thread goes, with its rows. A thread Support is part of
    (``support: true``) stays - 409."""
    thread_service.remove(db, thread=_found(db, owner=user, pk=pk))
    db.commit()


@router.post("/ask", response_model=TurnOut)
def ask(body: AskIn, request: Request, db: Db, user: OptionalUser) -> TurnOut:
    """One question in, one turn out; the answer arrives on ``/stream``. The
    plan's daily questions are the old chat's, counted once for both."""
    from app.modules.assistant.services.ask import start_turn
    from app.modules.assistant.tasks import answer_assistant_turn
    from app.modules.chat.services.quota import scope_for

    question = body.question.strip()
    if not question and not body.item:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Savol bo'sh.")
    entitled = user is not None and _entitled(db, user)
    session = None
    if body.session and user is not None:
        session = threads.session_for(db, owner=user, pk=body.session)
        if session is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suhbat topilmadi.")
    turn = start_turn(
        db,
        question=question,
        owner=user,
        entitled=entitled,
        scope=scope_for(
            user_id=str(user.id) if user is not None else "",
            ip=client_address(request),
            session_key=body.guest_id,
        ),
        now=utcnow(),
        session=session,
        asked=tuple(str(item) for item in body.asked if str(item).strip()),
        focus_id=body.suggestion,
        item_key=body.item,
    )
    db.commit()
    answer_assistant_turn.delay(turn.turn_id)
    return TurnOut(
        turn_id=turn.turn_id,
        session_id=turn.session_id,
        message_id=turn.message_id,
        left=turn.left,
    )


def _viewer(request: Request, token: str) -> str:
    header = request.headers.get("authorization", "")
    raw = (
        header.removeprefix("Bearer ").strip()
        if header.startswith("Bearer ")
        else token
    )
    return tokens.read(raw, kind="access") or "" if raw else ""


@router.get(
    "/stream/{turn_id}",
    responses={
        200: {"content": {"text/event-stream": {}}, "description": "SSE frames."}
    },
)
async def stream(
    turn_id: str,
    request: Request,
    token: str = Query("", description="The access token, for an EventSource."),
) -> StreamingResponse:
    """Server-sent events until the answer is finished.

    Each frame is JSON: ``delta`` (what was written since the last frame -
    append it), ``status`` (what is being looked at, while nothing is being
    written), and on the last one ``done: true`` with ``html`` (the whole
    answer, drawn), ``buttons`` and ``replies``. ``error`` is ``failed``,
    ``denied`` or ``timeout``."""
    viewer = _viewer(request, token)
    return StreamingResponse(
        _frames(turn_id=turn_id, viewer=viewer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _frames(*, turn_id: str, viewer: str) -> Any:
    deadline = time.monotonic() + STREAM_TIMEOUT_SECONDS
    sent = 0
    last_status = None
    while time.monotonic() < deadline:
        state = await asyncio.to_thread(cache.get, OUT_KEY.format(turn_id=turn_id))
        if isinstance(state, dict):
            owner_id = str(state.get("owner_id", ""))
            if owner_id and owner_id != viewer:
                yield _event({"done": True, "error": "denied"})
                return
            text = str(state.get("text", ""))
            # The gate may take back what it held: a shorter text starts over.
            if len(text) < sent:
                sent = 0
            delta = text[sent:]
            status_now = state.get("status", "")
            if delta or status_now != last_status or state.get("done"):
                deadline = time.monotonic() + STREAM_TIMEOUT_SECONDS
                frame: dict[str, Any] = {
                    "delta": delta,
                    "restart": sent == 0 and bool(delta) and len(text) > len(delta),
                    "status": "" if delta else status_now,
                    "done": bool(state.get("done")),
                    "error": state.get("error", ""),
                    "message_id": state.get("message_id", ""),
                    "session_id": state.get("session_id", ""),
                }
                if state.get("done"):
                    frame |= {
                        "html": state.get("html", ""),
                        "masked": state.get("masked", 0),
                        "buttons": state.get("buttons", []),
                        "replies": state.get("replies", []),
                        "stopped": bool(state.get("stopped")),
                    }
                sent, last_status = len(text), status_now
                yield _event(frame)
                if state.get("done"):
                    return
        await asyncio.sleep(POLL_SECONDS)
    yield _event({"done": True, "error": "timeout"})


def _event(frame: dict[str, Any]) -> str:
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


@router.post("/stop/{turn_id}", response_model=StopOut)
def stop(
    turn_id: str, request: Request, token: str = Query("", include_in_schema=False)
) -> StopOut:
    """End the answer being written where it is. The stream's next frame is
    the last (``done: true, stopped: true``) and the row keeps what was
    shown. A question stopped before the model began is not counted. A
    visitor stops their own answer with no token."""
    viewer = _viewer(request, token)
    return StopOut(stopped=thread_service.stop(turn_id=turn_id[:64], viewer=viewer))


@router.post("/support", status_code=status.HTTP_201_CREATED, response_model=SentOut)
def write_to_support(
    db: Db,
    user: CurrentUser,
    body: Annotated[str, Form(description="The words.")] = "",
    session: Annotated[
        str,
        Form(
            max_length=64,
            description="The thread. Empty: the one Support is in, or a new one.",
        ),
    ] = "",
    attachments: Annotated[
        list[UploadFile] | None,
        File(description="Up to 10 pictures, videos or documents."),
    ] = None,
    voice: Annotated[
        UploadFile | None, File(description="A recording: webm, ogg, m4a or mp3.")
    ] = None,
    voice_seconds: Annotated[
        int | None, Form(description="The recording's length.")
    ] = None,
    sticker: Annotated[str, Form(max_length=32, description="A sticker code.")] = "",
    send_key: Annotated[
        str, Form(max_length=64, description="`support.send_key`.")
    ] = "",
    nonce: Annotated[
        str, Form(max_length=64, description="Echoed on the socket.")
    ] = "",
) -> dict[str, Any]:
    """Words for a person, written in the chat - as the support chat takes
    them. No plan needed. Support has them in their queue and in Telegram,
    and their answer comes back into the same thread."""
    from app.modules.supportchat.constants import MessageSource
    from app.modules.supportchat.drafts import Draft, Voice
    from app.modules.supportchat.exceptions import AlreadySent
    from app.modules.supportchat.live import broadcast_message
    from app.modules.supportchat.routers import check_box

    found = threads.session_for(db, owner=user, pk=session) if session else None
    if session and found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suhbat topilmadi.")
    files = [item for item in attachments or [] if item.filename]
    recording = voice if voice is not None and voice.filename else None
    check_box(body=body, files=files, voice_seconds=voice_seconds)
    draft = Draft(
        body=body,
        files=tuple(files),
        voice=Voice(upload=recording, seconds=voice_seconds or 0)
        if recording
        else None,
        sticker=sticker,
        source=MessageSource.AI_CHAT,
    )
    now = utcnow()
    try:
        written = support.write_to_support(
            db, owner=user, session=found, draft=draft, now=now, send_key=send_key
        )
    except AlreadySent:
        return {
            "already_sent": True,
            "session_id": str(found.id) if found else "",
            "message": None,
            "send_key": uuid.uuid4().hex,
        }
    broadcast_message(message=written.support_message, nonce=nonce)
    views = support.views(db, owner=user, messages=[written.message], now=now)
    return jsonable_encoder(
        {
            "already_sent": False,
            "session_id": str(written.session.id),
            "message": _message_row(
                db,
                owner=user,
                row=written.message,
                view=views.get(written.message.id),
                now=now,
            ),
            "send_key": uuid.uuid4().hex,
        }
    )


@router.post("/buttons/{message_id}/{key}", response_model=PressOut)
def press(message_id: uuid.UUID, key: str, db: Db, user: CurrentUser) -> PressOut:
    """Press what an answer offered: send a ticket to Support, carry out a
    change, approve the agent's proposal. Each is checked again here."""
    pressed = buttons.press(
        db, owner=user, message_id=str(message_id), key=key, now=utcnow()
    )
    db.commit()
    return PressOut(
        kind=pressed.kind, key=pressed.key, state=pressed.state, text=pressed.text
    )


@router.post("/buttons/{message_id}/{key}/dismiss", response_model=PressOut)
def dismiss(message_id: uuid.UUID, key: str, db: Db, user: CurrentUser) -> PressOut:
    """The client says no: the button goes and nothing is sent."""
    pressed = buttons.dismiss(
        db, owner=user, message_id=str(message_id), key=key, now=utcnow()
    )
    db.commit()
    return PressOut(
        kind=pressed.kind, key=pressed.key, state=pressed.state, text=pressed.text
    )


@router.get("/buttons/{message_id}/{key}", response_model=PressOut)
def button_state(
    message_id: uuid.UUID, key: str, db: Db, user: CurrentUser
) -> PressOut:
    """Where a pressed button has got to: a ticket is `sent`, `working` (a
    person took it) or `done` (solved); a change `working`, `done` or
    `refused` with the reason. Asked until it stops moving."""
    pressed = buttons.state_of(
        db, owner=user, message_id=str(message_id), key=key, now=utcnow()
    )
    return PressOut(
        kind=pressed.kind, key=pressed.key, state=pressed.state, text=pressed.text
    )


@router.post(
    "/guest-ticket", status_code=status.HTTP_201_CREATED, response_model=GuestTicketOut
)
def guest_ticket(body: GuestTicketIn, request: Request, db: Db) -> dict[str, Any]:
    """A visitor leaves a name and a phone for the request the assistant
    prepared: a guest support chat opens with it and Support hears of it in
    Telegram. The page follows it at ``/api/v1/support/guest`` with the
    token."""
    from app.modules.assistant.services.guest import send_guest_ticket
    from app.modules.supportchat.routers.guests import guest_screen

    opened = send_guest_ticket(
        db,
        turn_id=body.turn_id,
        name=body.name,
        phone=body.phone,
        email=body.email,
        address=client_address(request),
        now=utcnow(),
    )
    return {"token": opened.token, "chat": guest_screen(db, opened.chat)}


# -- the office: the known problems the assistant searches ------------------


class ArticleIn(BaseModel):
    code: str = Field(max_length=64, description="Lowercase latin, digits, `-`, `_`.")
    problem_uz: str = ""
    problem_ru: str = ""
    problem_en: str = ""
    steps_uz: str = Field("", description="One step to a line.")
    steps_ru: str = ""
    steps_en: str = ""
    keywords: str = Field("", description="Other words people use, comma separated.")
    is_published: bool = False
    position: int = 0


@office.get("")
def articles(
    db: Db, user: Writer, q: str = Query("", max_length=100)
) -> dict[str, Any]:
    """Every article, published or not. Support and the Owner."""
    from app.modules.assistant.services.articles import article_out
    from app.modules.assistant.services.articles import articles as found

    return jsonable_encoder({"rows": [article_out(row) for row in found(db, query=q)]})


@office.post("", status_code=status.HTTP_201_CREATED)
def create_article(body: ArticleIn, db: Db, user: Writer) -> dict[str, Any]:
    from app.modules.assistant.services.articles import article_out, save_article

    return jsonable_encoder(
        article_out(save_article(db, fields=body.model_dump(), now=utcnow()))
    )


@office.get("/{pk}")
def read_article(pk: uuid.UUID, db: Db, user: Writer) -> dict[str, Any]:
    from app.modules.assistant.services.articles import article, article_out

    return jsonable_encoder(article_out(article(db, pk)))


@office.put("/{pk}")
def change_article(
    pk: uuid.UUID, body: ArticleIn, db: Db, user: Writer
) -> dict[str, Any]:
    from app.modules.assistant.services.articles import (
        article,
        article_out,
        save_article,
    )

    row = article(db, pk)
    return jsonable_encoder(
        article_out(save_article(db, fields=body.model_dump(), now=utcnow(), row=row))
    )


@office.delete("/{pk}", status_code=status.HTTP_204_NO_CONTENT)
def remove_article(pk: uuid.UUID, db: Db, user: Writer) -> None:
    from app.modules.assistant.services.articles import article, delete_article

    delete_article(db, row=article(db, pk))


@office.post("/search")
def try_search(
    db: Db,
    user: Writer,
    q: str = Query(min_length=2, max_length=160),
    language: str = Query("uz"),
) -> dict[str, str]:
    """What the assistant would be shown for these words - for the office to
    check an article is found."""
    from app.modules.assistant.selectors.help import help_search

    return {"result": help_search(db, query=q, language=language)}


# The support chat's hooks, so Support's replies reach this chat.
from app.modules.assistant import listeners as _listeners  # noqa: E402, F401
