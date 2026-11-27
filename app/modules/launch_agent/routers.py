"""The advert chat's door.

    POST /api/v3/launch-agent/sessions                open, or carry on
    GET  /api/v3/launch-agent/sessions/{id}           where it stands
    POST /api/v3/launch-agent/sessions/{id}/turns     one message or press
    POST /api/v3/launch-agent/sessions/{id}/voice     a recording into words
    POST /api/v3/launch-agent/sessions/{id}/close     leave it

Every answer has the same shape (``SessionOut``): the lines to show, the
one question waiting with its buttons, and what is settled so far. Once
``ready`` is true the launch's own first step is saved, and the page goes
on to the launch's media step (``/api/v1/launches/{launch_id}/media``).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.launch_agent.constants import (
    MAX_TURNS,
    NEXT_MEDIA,
    VOICE_MAX_BYTES,
    SessionStatus,
)
from app.modules.launch_agent.exceptions import SessionClosed
from app.modules.launch_agent.schemas import SessionOut, TurnIn, VoiceOut, as_out
from app.modules.launch_agent.services import turns, voice
from app.modules.launch_agent.services.stages import DONE

router = APIRouter(prefix="/launch-agent", tags=["launch-agent"])


@router.post("/sessions", response_model=SessionOut)
def open_session(db: Db, user: CurrentUser) -> SessionOut:
    """Open the advert chat for the page the person is on. A conversation
    left unfinished for the same advert is carried on."""
    session, said = turns.start(db, user=user, now=utcnow())
    db.commit()
    return as_out(session, said, max_turns=MAX_TURNS, next_step=NEXT_MEDIA)


@router.get("/sessions/{session_id}", response_model=SessionOut)
def read_session(session_id: uuid.UUID, db: Db, user: CurrentUser) -> SessionOut:
    session = turns.session_for(db, user=user, pk=session_id)
    now = utcnow()
    said = turns.current(db, user=user, session=session, now=now)
    if said.stage == DONE:
        # The page learns here that the advert was created: the
        # conversation is closed and what it sold is kept.
        turns.settle(db, user=user, session=session, now=now)
        db.commit()
    return as_out(session, said, max_turns=MAX_TURNS, next_step=NEXT_MEDIA)


@router.post("/sessions/{session_id}/turns", response_model=SessionOut)
def take_turn(
    session_id: uuid.UUID, body: TurnIn, db: Db, user: CurrentUser
) -> SessionOut:
    """One message (``text``) or one press (``slot`` + ``value``)."""
    session = turns.session_for(db, user=user, pk=session_id, lock=True)
    try:
        said = turns.turn(
            db,
            user=user,
            session=session,
            text=body.text,
            slot=body.slot,
            value=body.value,
            asset_ids=body.asset_ids,
            now=utcnow(),
        )
    except turns.DomainError:
        # A session closed on the way in stays closed.
        db.commit()
        raise
    if said.stage == DONE:
        turns.settle(db, user=user, session=session, now=utcnow())
    db.commit()
    return as_out(session, said, max_turns=MAX_TURNS, next_step=NEXT_MEDIA)


@router.post("/sessions/{session_id}/voice", response_model=VoiceOut)
def hear_voice(
    session_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    file: Annotated[
        UploadFile, File(description="A recording: webm, ogg, m4a, mp3 or wav.")
    ],
    language: Annotated[
        str, Form(max_length=5, description="uz, ru or en. Empty: it guesses.")
    ] = "",
) -> VoiceOut:
    """A spoken message as words. Nothing is sent: the page puts the words
    in the message box, and the person sends them with ``turns``."""
    session = turns.session_for(db, user=user, pk=session_id)
    if session.status == SessionStatus.CLOSED:
        raise SessionClosed
    # One byte past the limit is enough to know it is too big.
    data = file.file.read(VOICE_MAX_BYTES + 1)
    spoken = voice.to_text(
        db,
        session=session,
        data=data,
        filename=file.filename or "",
        language=language,
    )
    return VoiceOut(text=spoken.text, language=spoken.language)


@router.post("/sessions/{session_id}/close", status_code=204)
def close_session(session_id: uuid.UUID, db: Db, user: CurrentUser) -> None:
    session = turns.session_for(db, user=user, pk=session_id, lock=True)
    turns.close(db, session=session, now=utcnow())
    db.commit()
