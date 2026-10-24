"""The assistant's HTTP surface: threads, a question, its streamed answer, the week, and a choice.

``ask`` and ``stream`` take an optional reader: the same two serve the widget on
the public site, where the asker has no account. What they may see is decided
inside, from the subscription, never from which address was called.
"""

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db, OptionalUser, client_address
from app.common import tokens
from app.common.cache import cache
from app.common.db import utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.chat.constants import (
    CHOICE_POLL_SECONDS,
    HISTORY_TURNS,
    MAX_QUESTION_CHARS,
    POLL_SECONDS,
    REPORT_POLL_TRIES,
    STREAM_TIMEOUT_SECONDS,
)
from app.modules.chat.models import ChatMessage, ChatSession

router = APIRouter(prefix="/chat", tags=["chat"])


def _entitled(db: Session, owner: User) -> bool:
    from app.modules.billing.selectors import has_live_subscription

    return has_live_subscription(db, owner=owner)


def _session_row(row: ChatSession) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "last_message_at": row.last_message_at,
        "created_at": row.created_at,
    }


def _message_row(row: ChatMessage) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "role": row.role,
        "text": row.text,
        "html": row.html,
        "status": row.status,
        "masked_figures": row.masked_figures,
        "quote": row.quote or {},
        "offers": list(getattr(row, "offers", [])),
        "replies": list(getattr(row, "replies", [])),
        "created_at": row.created_at,
    }


def _card(card: Any) -> dict[str, Any] | None:
    if card is None:
        return None
    return jsonable_encoder(asdict(card))


def _screen(
    db: Session,
    *,
    owner: User,
    thread: ChatSession | None,
    suggestion: str,
    item: str,
    launch: str,
    ask: str,
) -> dict[str, Any]:
    from app.modules.agent.selectors import waiting_count
    from app.modules.chat.selectors import (
        focus_for,
        messages_in,
        sessions_for,
        with_choices,
        with_replies,
    )
    from app.modules.chat.selectors.scope import current_page_scope
    from app.modules.chat.services import questions_left_for

    now = utcnow()
    entitled = _entitled(db, owner)
    counted = questions_left_for(db, owner=owner, entitled=entitled, now=now)
    focused = focus_for(
        db,
        owner=owner,
        entitled=entitled,
        now=now,
        suggestion_id=suggestion,
        item_key=item,
        launch_id=launch,
        ask=ask,
    )
    drawn = (
        with_replies(
            with_choices(
                db, owner=owner, messages=messages_in(db, owner=owner, session=thread)
            )
        )
        if thread is not None
        else []
    )
    return jsonable_encoder(
        {
            "page_title": "AI dan so'rash",
            "entitled": entitled,
            "focus": {
                "card": _card(focused.card),
                "question": focused.question,
                "quote": focused.quote,
                "refusal": focused.refusal,
                "item": asdict(focused.item) if focused.item is not None else None,
            },
            "waiting": waiting_count(
                db, owner=owner, now=now, scope=current_page_scope(db, owner=owner)
            )
            if entitled
            else 0,
            "sessions": [_session_row(row) for row in sessions_for(db, owner=owner)],
            "thread": _session_row(thread) if thread is not None else None,
            "messages": [_message_row(row) for row in drawn],
            "choice_poll_seconds": CHOICE_POLL_SECONDS,
            "free_left": counted.left,
            "free_total": counted.total,
        }
    )


@router.get("")
def chat_screen(
    db: Db,
    user: CurrentUser,
    suggestion: str = "",
    item: str = "",
    launch: str = "",
    ask: str = "",
) -> dict[str, Any]:
    """The rail of threads and an empty box, focused on what this visit came from."""
    return _screen(
        db,
        owner=user,
        thread=None,
        suggestion=suggestion,
        item=item,
        launch=launch,
        ask=ask,
    )


@router.get("/threads/{pk}")
def chat_thread(
    pk: uuid.UUID,
    db: Db,
    user: CurrentUser,
    suggestion: str = "",
    item: str = "",
    launch: str = "",
    ask: str = "",
) -> dict[str, Any]:
    """One thread, every answer carrying whichever of its buttons can still be pressed."""
    from app.modules.chat.selectors import session_for

    thread = session_for(db, owner=user, pk=pk)
    if thread is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Suhbat topilmadi.")
    return _screen(
        db,
        owner=user,
        thread=thread,
        suggestion=suggestion,
        item=item,
        launch=launch,
        ask=ask,
    )


class AskIn(BaseModel):
    question: str = Field(default="", max_length=MAX_QUESTION_CHARS * 2)
    session: str = ""
    suggestion: str = ""
    item: str = ""
    launch: str = ""
    asked: list[str] = Field(default_factory=list, max_length=50)
    guest_id: str = Field(default="", max_length=64)


class TurnOut(BaseModel):
    turn_id: str
    session_id: str
    left: int


@router.post("/ask", response_model=TurnOut)
def ask(body: AskIn, request: Request, db: Db, user: OptionalUser) -> TurnOut:
    """One question in, one turn id out. The answer arrives over ``/chat/stream/{turn_id}``."""
    from app.modules.chat.services import scope_for, start_refusal_turn, start_turn
    from app.modules.chat.tasks import answer_chat_turn, answer_refusal_turn

    question = body.question.strip()
    if body.launch and user is not None:
        entitled = _entitled(db, user)
        turn = start_refusal_turn(
            db,
            owner=user,
            entitled=entitled,
            launch_id=body.launch,
            now=utcnow(),
            session=_session(db, user, entitled, body.session),
        )
        db.commit()
        answer_refusal_turn.delay(turn.turn_id)
        return TurnOut(turn_id=turn.turn_id, session_id=turn.session_id, left=turn.left)
    if not question and not body.item:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Savol bo'sh.")

    entitled = user is not None and _entitled(db, user)
    asked = tuple(str(item) for item in body.asked if str(item).strip())[
        -HISTORY_TURNS:
    ]
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
        session=_session(db, user, entitled, body.session),
        asked=asked,
        focus_id=body.suggestion,
        item_key=body.item,
    )
    db.commit()
    answer_chat_turn.delay(turn.turn_id)
    return TurnOut(turn_id=turn.turn_id, session_id=turn.session_id, left=turn.left)


def _session(
    db: Session, owner: User | None, entitled: bool, raw: str
) -> ChatSession | None:
    from app.modules.chat.selectors import session_for

    if not entitled or owner is None or not raw:
        return None
    return session_for(db, owner=owner, pk=raw)


def _viewer(request: Request, token: str) -> str:
    """Who is listening: the bearer header, or ``?token=`` for an EventSource."""
    header = request.headers.get("authorization", "")
    raw = (
        header.removeprefix("Bearer ").strip()
        if header.startswith("Bearer ")
        else token
    )
    return tokens.read(raw, kind="access") or "" if raw else ""


@router.get("/stream/{turn_id}")
async def stream(
    turn_id: str, request: Request, token: str = Query(default="")
) -> StreamingResponse:
    """Server-sent events until the answer is finished or time runs out."""
    viewer = _viewer(request, token)
    return StreamingResponse(
        _frames(turn_id=turn_id, viewer=viewer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def _frames(*, turn_id: str, viewer: str) -> AsyncIterator[str]:
    """One event per change, then stop."""
    from app.modules.chat.services.frames import OUT_KEY

    deadline = time.monotonic() + STREAM_TIMEOUT_SECONDS
    last: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        state = await asyncio.to_thread(cache.get, OUT_KEY.format(turn_id=turn_id))
        if isinstance(state, dict):
            owner_id = str(state.get("owner_id", ""))
            if owner_id and owner_id != viewer:
                yield _event({"done": True, "error": "denied"})
                return
            if state != last:
                last = state
                deadline = time.monotonic() + STREAM_TIMEOUT_SECONDS
                yield _event(state)
                if state.get("done"):
                    return
        await asyncio.sleep(POLL_SECONDS)
    yield _event({"done": True, "error": "timeout"})


def _event(state: dict[str, Any]) -> str:
    """One SSE frame, JSON on a single line."""
    return f"data: {json.dumps(state, ensure_ascii=False)}\n\n"


@router.get("/report")
def report(
    db: Db, user: CurrentUser, attempt: int = Query(default=0, alias="try", ge=0)
) -> dict[str, Any]:
    """One completed week, and the one sentence under it once a worker has written it."""
    from app.modules.chat.copy import HEADLINE_COPY, SILENCE_COPY
    from app.modules.chat.selectors import weekly_report
    from app.modules.chat.services import request_comment
    from app.modules.chat.tasks import explain_week_task

    if not _entitled(db, user):
        return {"report": None, "entitled": False}
    found = weekly_report(db, owner=user, now=utcnow())
    if found is None:
        return {"report": None, "entitled": True}
    comment, queue = request_comment(owner=user, report=found)
    db.commit()
    if queue:
        explain_week_task.delay(str(user.id))
    return jsonable_encoder(
        {
            "entitled": True,
            "report": asdict(found)
            | {"silence": found.silence, "wants_sentence": found.wants_sentence},
            "comment": asdict(comment),
            "silence": ""
            if found.wants_sentence
            else SILENCE_COPY.get(found.silence, ""),
            "headline_label": HEADLINE_COPY.get(found.headline, ""),
            "next_try": attempt + 1
            if comment.is_pending and attempt < REPORT_POLL_TRIES
            else 0,
        }
    )


class ChoiceOut(BaseModel):
    state: str
    text: str


@router.post("/choices/{pk}", response_model=ChoiceOut)
def press_choice(pk: uuid.UUID, db: Db, user: CurrentUser) -> ChoiceOut:
    """Approve one proposal from inside a conversation: the same service the actions screen uses."""
    from app.modules.agent.selectors import one
    from app.modules.agent.services import approve_suggestion
    from app.modules.notifications.services.refusals import refusal_words

    suggestion = one(db, owner=user, pk=pk)
    if suggestion is None:
        return ChoiceOut(state="refused", text="Bu taklif topilmadi.")
    try:
        approve_suggestion(db, user=user, suggestion=suggestion)
    except DomainError as exc:
        db.rollback()
        return ChoiceOut(state="refused", text=str(refusal_words(exc)))
    db.commit()
    return ChoiceOut(state="working", text="Bajarilmoqda.")


@router.get("/choices/{pk}", response_model=ChoiceOut)
def choice_state(pk: uuid.UUID, db: Db, user: CurrentUser) -> ChoiceOut:
    """Where that change has got to. Asked until it says it has stopped."""
    from app.modules.agent.selectors import card_for, is_working, one

    suggestion = one(db, owner=user, pk=pk)
    if suggestion is None:
        return ChoiceOut(state="gone", text="")
    if is_working(db, owner=user, pk=str(pk), now=utcnow()):
        return ChoiceOut(state="working", text="Bajarilmoqda.")
    card = card_for(db, owner=user, suggestion=suggestion)
    if card.landed is False:
        return ChoiceOut(state="done", text="O'zgarish Meta tomonida ko'rinmadi.")
    return ChoiceOut(state="done", text=str(card.expectation))


__all__ = ["router"]
