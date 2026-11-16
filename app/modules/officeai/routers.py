"""The office assistant's HTTP surface, under ``/api/v2/office/ai``.

Only the Owner and a superuser open it. Each person sees only their own
threads. The same assistant answers the owners in @owners_tai_bot
(``services.telegram``).

A question goes to ``POST /ask``; its answer is read from
``GET /stream/{turn_id}`` as server-sent events.
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import Db
from app.common import tokens
from app.common.cache import cache
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.constants import MONEY_ROLES, Role
from app.modules.backoffice.permissions import has_role, staff_required
from app.modules.officeai.constants import (
    MAX_QUESTION_CHARS,
    OUT_KEY,
    POLL_SECONDS,
    QUESTIONS_PER_DAY,
    STREAM_TIMEOUT_SECONDS,
    SUGGESTIONS,
    TITLE_CHARS,
)
from app.modules.officeai.models import OfficeAiMessage, OfficeAiThread
from app.modules.officeai.selectors import threads

router = APIRouter(prefix="/office/ai", tags=["office ai"])
Admin = Annotated[User, Depends(staff_required(Role.OWNER))]


class ThreadOut(BaseModel):
    id: str
    title: str
    last_message_at: datetime | None
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    author: str = Field(description="`user` or `ai`.")
    text: str
    html: str = Field(
        description="The answer drawn: escaped first, then only `p`, `br`, "
        "`strong`, `code`, lists and tables - safe to insert as is."
    )
    status: str = Field(description="`pending`, `done` or `failed`.")
    masked_figures: int = Field(
        description="Figures shown as `[?]`: no look-up returned them."
    )
    meta: dict[str, Any] = Field(
        description="`lookups` - what was read for the answer; `stopped`."
    )
    created_at: datetime


class ScreenOut(BaseModel):
    sees_money: bool = Field(description="False: money questions are refused.")
    threads: list[ThreadOut]
    thread: ThreadOut | None
    messages: list[MessageOut]
    has_earlier: bool
    suggestions: list[str] = Field(description="Questions to offer on an empty screen.")
    questions_left: int
    questions_total: int


class PageOut(BaseModel):
    messages: list[MessageOut]
    has_earlier: bool


class AskIn(BaseModel):
    question: str = Field(max_length=MAX_QUESTION_CHARS * 2)
    thread: str = Field("", max_length=64, description="Empty starts a thread.")


class TurnOut(BaseModel):
    turn_id: str
    thread_id: str
    message_id: str
    left: int


class RenameIn(BaseModel):
    title: str = Field(max_length=200)


class StopOut(BaseModel):
    stopped: bool


def _thread_row(row: OfficeAiThread) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "last_message_at": row.last_message_at,
        "created_at": row.created_at,
    }


def _message_row(row: OfficeAiMessage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "author": row.author,
        "text": row.text,
        "html": row.html,
        "status": row.status,
        "masked_figures": row.masked_figures,
        "meta": row.meta or {},
        "created_at": row.created_at,
    }


def _sees_money(db: Session, user: User) -> bool:
    return has_role(db, user, MONEY_ROLES)


def _screen(db: Session, *, user: User, thread: OfficeAiThread | None) -> Any:
    from app.modules.officeai.services.ask import questions_left

    rows, has_earlier = (
        threads.messages_page(db, thread=thread) if thread else ([], False)
    )
    return jsonable_encoder(
        {
            "sees_money": _sees_money(db, user),
            "threads": [
                _thread_row(row) for row in threads.threads_for(db, staff=user)
            ],
            "thread": _thread_row(thread) if thread is not None else None,
            "messages": [_message_row(row) for row in rows],
            "has_earlier": has_earlier,
            "suggestions": list(SUGGESTIONS),
            "questions_left": questions_left(db, staff=user, now=utcnow()),
            "questions_total": QUESTIONS_PER_DAY,
        }
    )


def _found(db: Session, *, user: User, pk: uuid.UUID | str) -> OfficeAiThread:
    found = threads.thread_for(db, staff=user, pk=pk)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suhbat topilmadi.")
    return found


@router.get("", response_model=ScreenOut)
def screen(db: Db, user: Admin) -> Any:
    """The rail of this person's threads and an empty box."""
    return _screen(db, user=user, thread=None)


@router.get("/threads/{pk}", response_model=ScreenOut)
def thread(pk: uuid.UUID, db: Db, user: Admin) -> Any:
    """One thread, its newest rows."""
    return _screen(db, user=user, thread=_found(db, user=user, pk=pk))


@router.get("/threads/{pk}/messages", response_model=PageOut)
def earlier(
    pk: uuid.UUID,
    db: Db,
    user: Admin,
    before: uuid.UUID = Query(description="The oldest row the page has."),
) -> Any:
    found = _found(db, user=user, pk=pk)
    oldest = threads.message_for(db, staff=user, pk=before)
    if oldest is None or oldest.thread_id != found.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Xabar topilmadi.")
    rows, has_earlier = threads.messages_page(db, thread=found, before=oldest)
    return jsonable_encoder(
        {"messages": [_message_row(row) for row in rows], "has_earlier": has_earlier}
    )


@router.patch("/threads/{pk}", response_model=ThreadOut)
def rename_thread(pk: uuid.UUID, body: RenameIn, db: Db, user: Admin) -> Any:
    found = _found(db, user=user, pk=pk)
    title = " ".join(body.title.split())[:TITLE_CHARS]
    if not title:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Suhbat nomi bo'sh bo'lmasin."
        )
    found.title = title
    db.commit()
    return jsonable_encoder(_thread_row(found))


@router.delete("/threads/{pk}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(pk: uuid.UUID, db: Db, user: Admin) -> None:
    """The thread and its rows. Production's foreign keys do not cascade."""
    found = _found(db, user=user, pk=pk)
    db.execute(delete(OfficeAiMessage).where(OfficeAiMessage.thread_id == found.id))
    db.delete(found)
    db.commit()


@router.post("/ask", response_model=TurnOut)
def ask(body: AskIn, db: Db, user: Admin) -> TurnOut:
    """One question in, one turn out; the answer arrives on ``/stream``."""
    from app.modules.officeai.services.ask import start_turn
    from app.modules.officeai.tasks import answer_office_turn

    found = _found(db, user=user, pk=body.thread) if body.thread else None
    turn = start_turn(
        db,
        staff=user,
        question=body.question,
        thread=found,
        sees_money=_sees_money(db, user),
        now=utcnow(),
    )
    db.commit()
    answer_office_turn.delay(turn.turn_id)
    return TurnOut(
        turn_id=turn.turn_id,
        thread_id=turn.thread_id,
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
    return (tokens.read(raw, kind="access") or "") if raw else ""


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
    """Server-sent events until the answer is finished. Each frame is JSON:
    ``delta`` (append it), ``restart`` (clear, then append), ``status``
    (what is being read), and on the last ``done: true`` with ``html``,
    ``masked`` and ``stopped``. ``error``: ``failed``, ``denied``,
    ``timeout``."""
    viewer = _viewer(request, token)
    return StreamingResponse(
        _frames(turn_id=turn_id[:64], viewer=viewer),
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
            if not viewer or state.get("staff_id") != viewer:
                yield _event({"done": True, "error": "denied"})
                return
            text = str(state.get("text", ""))
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
                    "thread_id": state.get("thread_id", ""),
                }
                if state.get("done"):
                    frame |= {
                        "html": state.get("html", ""),
                        "masked": state.get("masked", 0),
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
def stop(turn_id: str, user: Admin) -> StopOut:
    """End the answer being written where it is."""
    from app.modules.officeai.services.answer import stop as stop_turn

    return StopOut(stopped=stop_turn(turn_id=turn_id[:64], viewer=str(user.id)))


__all__ = ["router"]
