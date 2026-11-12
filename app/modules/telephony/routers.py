"""The office's telephony settings, ``/api/v2/office/telephony``, and the
address UTeL sends its events to."""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from app.api.deps import Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.boards.access import Staff, access_for
from app.modules.telephony import services
from app.modules.telephony.constants import HOOK_BODY_MAX, HOOK_PATH
from app.modules.telephony.schemas import ConnectIn, ExtensionIn, TelephonyOut

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
