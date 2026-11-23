import json
import logging
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.autopay import services
from app.modules.autopay.exceptions import CardServiceDown
from app.modules.autopay.schemas import AutopayIn, BindIn, BindOut, CardOut, card_out
from app.modules.autopay.selectors import active_card
from app.modules.billing.selectors import live_subscription, next_term_plan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing/card", tags=["billing autopay"])
webhooks = APIRouter(tags=["webhooks"])


def _shown(db: Session, user: User, *, pending: bool = False) -> CardOut:
    live = live_subscription(db, owner=user)
    return card_out(
        active_card(db, owner=user),
        available=services.autopay_on(),
        expires_at=live.expires_at if live else None,
        pending=pending,
        next_plan=next_term_plan(db, plan=live.plan) if live else None,
    )


@router.get("", response_model=CardOut)
def card(db: Db, user: CurrentUser) -> CardOut:
    """The card the plan is renewed from, and how the last renewal went."""
    return _shown(db, user)


@router.post("/bind", response_model=BindOut)
def bind(body: BindIn, db: Db, user: CurrentUser) -> BindOut:
    """Open Multicard's page for adding a card. A new card replaces the old."""
    binding = services.start_binding(
        db,
        user=user,
        phone=body.phone,
        consent=body.consent,
        now=utcnow(),
        autopay=body.autopay,
        back=body.back,
    )
    db.commit()
    return BindOut(session_id=binding.session_id, form_url=binding.form_url)


@router.post("/bind/{session_id}/check", response_model=CardOut)
def check(session_id: str, db: Db, user: CurrentUser) -> CardOut:
    """After Multicard's page: whether the card was added."""
    found = services.check_binding(db, user=user, session_id=session_id, now=utcnow())
    db.commit()
    return _shown(db, user, pending=found.status == "pending")


@router.post("/autopay", response_model=CardOut)
def autopay(body: AutopayIn, db: Db, user: CurrentUser) -> CardOut:
    """Renew from the card, or stop doing so and keep the card."""
    services.set_autopay(db, user=user, enabled=body.enabled)
    db.commit()
    return _shown(db, user)


@router.delete("", response_model=CardOut)
def remove(db: Db, user: CurrentUser) -> CardOut:
    """Forget the card; Multicard voids its token too."""
    services.remove_card(db, user=user, now=utcnow())
    db.commit()
    return _shown(db, user)


@webhooks.post("/webhooks/cards/multicard", include_in_schema=False)
async def card_callback(request: Request) -> JSONResponse:
    """Multicard says a card was added. Unsigned: the card is read back from it."""
    from app.common.db import SessionLocal

    raw = await request.body()
    session_id = _callback_session(raw, request.headers.get("content-type", ""))
    if not session_id:
        logger.warning(
            "card callback without a session: content-type %r, body %s",
            request.headers.get("content-type", ""),
            _masked(raw),
        )
        return JSONResponse({"success": False}, status_code=400)
    db = SessionLocal()
    try:
        services.binding_reported(db, session_id=session_id, now=utcnow())
        db.commit()
    except CardServiceDown:
        db.rollback()
        # Multicard sends it again in a minute, five times.
        return JSONResponse({"success": False}, status_code=503)
    finally:
        db.close()
    return JSONResponse({"success": True})


# Where Multicard's card callback may name the binding page: its docs say
# ``payer_id``; the others are read too, since the docs and the wire differ.
_SESSION_KEYS = ("payer_id", "session_id")
_SECRET_KEYS = ("card_token", "token", "pinfl")


def _callback_body(raw: bytes, content_type: str) -> dict[str, Any]:
    """The callback's fields, sent as JSON or as a form."""
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        body = None
    if isinstance(body, dict):
        return body
    if "form" in content_type or b"=" in raw:
        return {k: v[0] for k, v in parse_qs(raw.decode("utf-8", "replace")).items()}
    return {}


def _callback_session(raw: bytes, content_type: str) -> str:
    body = _callback_body(raw, content_type)
    for place in (body, body.get("data"), body.get("payload")):
        if isinstance(place, dict):
            for key in _SESSION_KEYS:
                if place.get(key):
                    return str(place[key])[:64]
    return ""


def _masked(raw: bytes) -> str:
    """The rejected body for the log, with the card's secrets blanked."""
    body = _callback_body(raw, "")
    if not body:
        return repr(raw[:300])

    def hide(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                k: "***" if k in _SECRET_KEYS else hide(v) for k, v in value.items()
            }
        if isinstance(value, list):
            return [hide(v) for v in value]
        return value

    return json.dumps(hide(body), ensure_ascii=False, default=str)[:600]
