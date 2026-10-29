"""The sockets on a support chat: words and stickers travel here, files
take ``POST /support/messages``.

``/api/v1/support/ws?token=<access token>`` is the client's; add
``&watch=1`` for the corner widget, which only listens - a message drawn
for it has not been read, so it does not mark the chat as read. The
office's is ``/api/v1/office/support/{conversation_id}/ws?token=``, for a
member who answers support, and speaks the same frames.

What a page says over it, as JSON:

- ``{"body", "nonce", "reply_to"}`` or ``{"sticker", "nonce", "reply_to"}``
  - a message;
- ``{"typing": true}`` - the reader is typing; passed on, never stored;
- ``{"read": true}`` - the widget's panel is open on the chat.

What it hears back: ``message`` (a new row), ``replace`` (a row edited or
taken back), ``read`` (the office read up to a moment, in ms), ``typing``
and ``error``. Events reach every worker's sockets through Redis.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from typing import Any

from fastapi import Depends, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from sqlalchemy.orm import Session

from app.common import tokens
from app.common.db import get_db, utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.backoffice.services import may_answer_support
from app.modules.supportchat import live, selectors, services
from app.modules.supportchat.constants import CLIENT, OFFICE, WATCH_PARAM, Viewer
from app.modules.supportchat.drafts import Draft
from app.modules.supportchat.models import SupportConversation

logger = logging.getLogger(__name__)


class Door:
    """One open socket: its reader, its database session, and its writes
    to the page, each taken one at a time."""

    def __init__(
        self,
        websocket: WebSocket,
        db: Session,
        user_id: uuid.UUID,
        *,
        viewer: Viewer = CLIENT,
        owner_id: uuid.UUID | None = None,
    ) -> None:
        self.websocket = websocket
        self.db = db
        self.user_id = user_id
        self.viewer = viewer
        # Whose chat: the reader's own, or for the office the client's.
        self.owner_id = owner_id or user_id
        self.watching = False
        self._db_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    async def run_db[T](self, work: Callable[[Session, User], T]) -> T | None:
        """``work`` in the thread pool, with the reader fetched afresh; the
        session lets its connection go as soon as it is done."""

        def run() -> T | None:
            try:
                user = self.db.get(User, self.user_id)
                if user is None or not user.is_active:
                    return None
                return work(self.db, user)
            finally:
                self.db.close()

        async with self._db_lock:
            return await run_in_threadpool(run)

    async def send(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_json(payload)

    async def publish(self, event: dict[str, Any]) -> None:
        await run_in_threadpool(live.publish, owner_id=self.owner_id, event=event)

    def chat(self, db: Session) -> SupportConversation | None:
        owner = db.get(User, self.owner_id)
        return selectors.chat_of(db, owner=owner) if owner is not None else None

    async def read(self) -> None:
        """The reader has the chat in front of them: move their side's
        moment, and tell the office's ticks when it moved."""

        def mark(db: Session, user: User) -> Any:
            chat = self.chat(db)
            if chat is None:
                return None
            now = utcnow()
            moved = services.mark_read(db, conversation=chat, reader=user, now=now)
            return now if moved else None

        moment = await self.run_db(mark)
        if moment is not None:
            await self.publish(live.read_event(side=self.viewer, at=moment))

    async def draw(self, message_id: str) -> dict[str, Any] | None:
        """One message of this reader's chat, as the screen draws it."""

        def view(db: Session, user: User) -> dict[str, Any] | None:
            message = selectors.message_in_chat(
                db, owner_id=self.owner_id, message_id=message_id
            )
            chat = self.chat(db)
            if message is None or chat is None:
                return None
            drawn = selectors.drawn(db, [message])
            return jsonable_encoder(
                selectors.message_view(
                    message,
                    drawn=drawn,
                    conversation=chat,
                    viewer=self.viewer,
                    now=utcnow(),
                )
            )

        return await self.run_db(view)

    async def post(self, fields: dict[str, Any]) -> None:
        """Store a message through the one service, or say why not."""
        nonce = _text(fields.get("nonce"))
        draft = Draft(
            body=_text(fields.get("body")),
            sticker=_text(fields.get("sticker")),
            reply_to=_text(fields.get("reply_to")),
        )

        def store(db: Session, user: User) -> tuple[str, str, str]:
            try:
                if self.viewer == CLIENT:
                    message = services.send_to_support(
                        db, owner=user, draft=draft, now=utcnow()
                    )
                else:
                    chat = self.chat(db)
                    if chat is None:
                        return "", "Suhbat topilmadi.", "not_found"
                    message = services.post_message(
                        db, conversation=chat, sender=user, draft=draft, now=utcnow()
                    )
            except DomainError as exc:
                return "", exc.message, exc.code
            return str(message.id), "", ""

        stored = await self.run_db(store)
        if stored is None:
            return
        message_id, refusal, code = stored
        if not message_id:
            await self.send(
                {"type": "error", "message": refusal, "code": code, "nonce": nonce}
            )
            return
        await self.publish(live.message_event(message_id=message_id, nonce=nonce))

    async def receive(self, content: Any) -> None:
        fields = content if isinstance(content, dict) else {}
        if fields.get("read") is True:
            await self.read()
            return
        if fields.get("typing") is True:
            await self.publish(live.typing_event(side=self.viewer))
            return
        await self.post(fields)

    async def forward(self, frames: AsyncIterator[str]) -> None:
        """Each event on the chat's channel, drawn for this reader."""
        async for raw in frames:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            kind = event.get("type")
            if kind in (live.MESSAGE, live.CHANGED):
                view = await self.draw(str(event.get("message_id", "")))
                if view is None:
                    continue
                if kind == live.MESSAGE:
                    await self.send(
                        {
                            "type": "message",
                            "id": view["id"],
                            "nonce": event.get("nonce", ""),
                            "message": view,
                        }
                    )
                    if not self.watching:
                        await self.read()
                else:
                    await self.send(
                        {"type": "replace", "id": view["id"], "message": view}
                    )
            elif kind == live.READ and event.get("side") != self.viewer:
                await self.send({"type": "read", "at": event.get("at", 0)})
            elif kind == live.TYPING and event.get("side") != self.viewer:
                await self.send({"type": "typing", "side": event.get("side", "")})


def _reader(db: Session, token: str) -> uuid.UUID | None:
    """The signed-in client the token names, or ``None``."""
    subject = tokens.read(token, kind="access") if token else None
    try:
        user = db.get(User, uuid.UUID(subject or ""))
    except ValueError:
        return None
    finally:
        db.close()
    if user is None or not user.is_active or user.crm_owner_id is not None:
        return None
    return user.id


def _text(value: object) -> str:
    """A string field from the page, or empty when it sent anything else."""
    return value if isinstance(value, str) else ""


async def support_socket(
    websocket: WebSocket,
    db: Session = Depends(get_db),
    token: str = Query("", description="The access token."),
    watch: str = Query("", alias=WATCH_PARAM, description="`1`: only listen."),
) -> None:
    """The client's live view of their own chat."""
    user_id = await run_in_threadpool(_reader, db, token)
    if user_id is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    door = Door(websocket, db, user_id)
    door.watching = watch == "1"
    await _serve(door)


async def _serve(door: Door) -> None:
    """Listen on the chat's channel and the page until either goes away."""
    websocket = door.websocket
    async with AsyncExitStack() as stack:
        try:
            frames = await stack.enter_async_context(
                live.hub.listen(live.channel_name(owner_id=door.owner_id))
            )
        except Exception:
            logger.warning("support live channel unavailable")
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return
        await websocket.accept()
        forwarding = asyncio.create_task(_forward(door, frames))
        try:
            if not door.watching:
                await door.read()
            while True:
                raw = await websocket.receive_text()
                try:
                    content = json.loads(raw)
                except ValueError:
                    continue
                await door.receive(content)
        except WebSocketDisconnect:
            pass
        finally:
            forwarding.cancel()
            await asyncio.gather(forwarding, return_exceptions=True)


def _office_reader(
    db: Session, token: str, conversation_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """A member who answers for the office, and whose chat they opened."""
    subject = tokens.read(token, kind="access") if token else None
    try:
        user = db.get(User, uuid.UUID(subject or ""))
        if user is None or not user.is_active or not may_answer_support(db, user=user):
            return None
        chat = selectors.staff_conversation(db, pk=conversation_id)
        return (user.id, chat.owner_id) if chat is not None else None
    except ValueError:
        return None
    finally:
        db.close()


async def office_socket(
    websocket: WebSocket,
    conversation_id: uuid.UUID,
    db: Session = Depends(get_db),
    token: str = Query("", description="The access token."),
) -> None:
    """The office's live view of any client's chat."""
    found = await run_in_threadpool(_office_reader, db, token, conversation_id)
    if found is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    user_id, owner_id = found
    await _serve(Door(websocket, db, user_id, viewer=OFFICE, owner_id=owner_id))


async def _forward(door: Door, frames: AsyncIterator[str]) -> None:
    """The channel to the page until either goes away."""
    try:
        await door.forward(frames)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.info("support socket stopped forwarding", exc_info=True)
