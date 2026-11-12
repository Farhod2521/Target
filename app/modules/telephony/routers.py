"""The office's telephony settings, ``/api/v2/office/telephony``, and the
address UTeL sends its events to."""

import asyncio
import json
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import Db
from app.common import tokens
from app.common.db import get_db, utcnow
from app.modules.accounts.models import User
from app.modules.boards.access import Staff, access_for
from app.modules.supportchat.live import hub
from app.modules.telephony import calls, live, routing, services
from app.modules.telephony.constants import (
    CALL_SEARCH_MAX,
    CALLS_PAGE,
    CALLS_PAGE_MAX,
    HOOK_BODY_MAX,
    HOOK_PATH,
    LIVE_CHANNEL,
    ROUTE_PATH,
    CallScope,
    Direction,
)
from app.modules.telephony.schemas import (
    ConnectIn,
    ExtensionIn,
    JournalOut,
    LiveOut,
    MyPhoneOut,
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


NO_STORE = {"Cache-Control": "no-store"}


@router.get("/me", responses={200: {"model": MyPhoneOut}})
def my_phone(db: Db, caller: OnPhone) -> JSONResponse:
    """The reader's browser phone: whether to start it and what it
    registers with. The password is the reader's own number's only."""
    found = services.my_phone(db, user=caller.user)
    return JSONResponse(MyPhoneOut.model_validate(found).model_dump(), headers=NO_STORE)


@router.post("/me/refused", responses={200: {"model": MyPhoneOut}})
def sip_refused(db: Db, caller: OnPhone) -> JSONResponse:
    """Say that UTeL answered 401 or 403 to the registration. The answer
    is the phone's settings again: `enabled` with a new password means try
    once more; not enabled means stop."""
    found = services.sip_refused(db, user=caller.user)
    return JSONResponse(MyPhoneOut.model_validate(found).model_dump(), headers=NO_STORE)


@router.get("/live", responses={200: {"model": LiveOut}})
def live_calls(db: Db, caller: OnPhone) -> dict[str, Any]:
    """The calls going on now. The socket beside it sends each change;
    this is the whole picture, for a page that cannot hold a socket."""
    return live.snapshot(db, now=utcnow())


def _listener(db: Session, token: str) -> bool:
    """A reader the calls may be told to: active staff a board opens for."""
    subject = tokens.read(token, kind="access") if token else None
    try:
        user = db.get(User, uuid.UUID(subject or ""))
        if user is None or not user.is_active or not user.is_staff:
            return False
        return bool(access_for(db, user).boards)
    except ValueError:
        return False
    finally:
        db.close()


def _picture(db: Session) -> dict[str, Any]:
    try:
        calls_now: dict[str, Any] = jsonable_encoder(live.snapshot(db, now=utcnow()))
        return {"type": live.SNAPSHOT} | calls_now
    finally:
        db.close()


async def phone_socket(
    websocket: WebSocket,
    db: Session = Depends(get_db),
    token: str = Query("", description="The access token."),
) -> None:
    """``/api/v2/office/telephony/ws?token=``: the calls going on, live.

    First a ``snapshot`` (the same as ``GET /live``), then ``call.ringing``
    and ``call.talking`` with the call, and ``call.ended`` with its
    ``call_id``. The page says nothing; whatever it sends is ignored."""
    if not await run_in_threadpool(_listener, db, token):
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    async with AsyncExitStack() as stack:
        try:
            frames = await stack.enter_async_context(hub.listen(LIVE_CHANNEL))
        except Exception:
            await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
            return
        await websocket.accept()
        await websocket.send_json(await run_in_threadpool(_picture, db))

        async def forward() -> None:
            async for raw in frames:
                await websocket.send_text(raw)

        forwarding = asyncio.create_task(forward())
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            forwarding.cancel()
            await asyncio.gather(forwarding, return_exceptions=True)


router.add_api_websocket_route("/ws", phone_socket)


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


@webhooks.api_route(ROUTE_PATH, methods=["GET", "POST"], include_in_schema=False)
async def utel_route(key: str, request: Request, db: Db) -> JSONResponse:
    """UTeL asks whom to put an incoming call through to. The number comes
    in the query or in a JSON body; the answer is always a JSON object."""
    number: object = request.query_params.get("number", "")
    if not number and request.method == "POST":
        body = await request.body()
        try:
            sent = json.loads(body) if len(body) <= HOOK_BODY_MAX else None
        except ValueError:
            sent = None
        if isinstance(sent, dict):
            number = sent.get("number") or ""
    found = await run_in_threadpool(
        routing.answer, db, key=key, number=number, now=utcnow()
    )
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return JSONResponse(found)
