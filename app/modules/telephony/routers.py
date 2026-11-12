"""The office's telephony settings, ``/api/v2/office/telephony``, and the
address UTeL sends its events to."""

import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.boards.access import Staff, access_for
from app.modules.telephony import calls, services
from app.modules.telephony.constants import (
    CALL_SEARCH_MAX,
    CALLS_PAGE,
    CALLS_PAGE_MAX,
    HOOK_BODY_MAX,
    HOOK_PATH,
    CallScope,
    Direction,
)
from app.modules.telephony.schemas import (
    ConnectIn,
    ExtensionIn,
    JournalOut,
    TelephonyOut,
)

router = APIRouter(prefix="/office/telephony", tags=["office telephony"])
webhooks = APIRouter(tags=["webhooks"])


def _full(db: Db, user: Staff) -> User:
    """The superuser and the Owner role; 404 for anybody else, as every
    office door answers."""
    if not access_for(db, user).full:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


Full = Annotated[User, Depends(_full)]
OUT: dict[int | str, dict[str, Any]] = {200: {"model": TelephonyOut}}


@router.get("", responses=OUT)
def telephony(db: Db, user: Full) -> dict[str, Any]:
    """The connection, the internal numbers and who answers each."""
    return services.state(db, now=utcnow())


@router.put("/connection", responses=OUT)
def connect(body: ConnectIn, db: Db, user: Full) -> dict[str, Any]:
    """Sign in to UTeL. Reads the internal numbers and asks UTeL to send
    events here. If only the last step fails the connection is kept and
    `connection.last_error` says so."""
    services.connect(
        db, tenant=body.tenant, email=body.email, password=body.password, actor=user
    )
    return services.state(db, now=utcnow())


@router.delete("/connection", responses=OUT)
def disconnect(db: Db, user: Full) -> dict[str, Any]:
    """Forget the exchange, its numbers and who answered them."""
    services.disconnect(db, actor=user)
    return services.state(db, now=utcnow())


@router.post("/sync", responses=OUT)
def sync(db: Db, user: Full) -> dict[str, Any]:
    """Read the internal numbers from UTeL again."""
    services.sync(db)
    return services.state(db, now=utcnow())


@router.post("/hook", responses=OUT)
def hook(db: Db, user: Full) -> dict[str, Any]:
    """Ask UTeL again to send events here."""
    services.set_hook(db)
    return services.state(db, now=utcnow())


@router.patch("/extensions/{extension_id}", responses=OUT)
def extension(
    extension_id: uuid.UUID, body: ExtensionIn, db: Db, user: Full
) -> dict[str, Any]:
    """Give a number to a person, take it back, or switch the browser phone."""
    services.assign(
        db, extension_id=extension_id, changes=body.model_dump(exclude_unset=True)
    )
    return services.state(db, now=utcnow())


@dataclass(frozen=True, slots=True)
class Caller:
    user: User
    sees_all: bool


def _caller(db: Db, user: Staff) -> Caller:
    """Anybody a board opens for. Leads, the superuser and the Owner see
    every call; the rest their own and the ones nobody answered."""
    access = access_for(db, user)
    if not access.boards:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return Caller(user=user, sees_all=access.full or bool(access.leads))


OnPhone = Annotated[Caller, Depends(_caller)]


@router.get("/calls", responses={200: {"model": JournalOut}})
def journal(
    db: Db,
    caller: OnPhone,
    scope: Annotated[
        CallScope,
        Query(description="`unknown`: numbers nobody signed up with."),
    ] = CallScope.ALL,
    direction: Annotated[Direction | None, Query()] = None,
    answered: Annotated[
        bool | None, Query(description="`false`: the missed ones.")
    ] = None,
    mine: Annotated[bool, Query(description="Only the reader's own calls.")] = False,
    q: Annotated[
        str, Query(max_length=CALL_SEARCH_MAX, description="Digits of the number.")
    ] = "",
    limit: Annotated[int, Query(ge=1, le=CALLS_PAGE_MAX)] = CALLS_PAGE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """The journal of calls, newest first."""
    return calls.journal(
        db,
        viewer=caller.user,
        sees_all=caller.sees_all,
        scope=scope,
        direction=direction,
        answered=answered,
        mine=mine,
        q=q,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/calls/{call_id}/recording",
    response_class=StreamingResponse,
    responses={200: {"content": {"audio/wav": {}}}},
)
def recording(call_id: uuid.UUID, db: Db, caller: OnPhone) -> StreamingResponse:
    """The call's audio. It needs the reader's token like any other call
    here, so fetch it and play the blob; UTeL's own link is never given out."""
    chunks, kind = calls.recording(
        db, call_id=call_id, viewer=caller.user, sees_all=caller.sees_all
    )
    return StreamingResponse(
        chunks, media_type=kind, headers={"Cache-Control": "private, max-age=3600"}
    )


@webhooks.post(HOOK_PATH, include_in_schema=False)
async def utel_events(key: str, request: Request, db: Db) -> JSONResponse:
    """UTeL waits ten seconds for a 2xx, so the event is only written down.
    The key in the path is the whole check: UTeL signs nothing."""
    body = await request.body()
    if len(body) > HOOK_BODY_MAX:
        raise HTTPException(413)
    try:
        payload = json.loads(body)
    except ValueError:
        payload = None
    if not isinstance(payload, dict):
        raise HTTPException(status.HTTP_400_BAD_REQUEST)
    kept = await run_in_threadpool(services.keep_event, db, key=key, payload=payload)
    if not kept:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return JSONResponse({"ok": True})
