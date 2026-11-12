"""Whom an incoming call is put through to. The exchange asks before it
rings anybody and waits a few seconds at most; no answer worth giving
sends the call to the exchange's own fallback group."""

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.telephony import calls, live
from app.modules.telephony.constants import ROUTE_RECENT_DAYS
from app.modules.telephony.models import PhoneCall, PhoneConnection, PhoneExtension

logger = logging.getLogger(__name__)

# Never an empty body: UTeL reads one as null and the call drops.
NOBODY: dict[str, Any] = {"extension": None, "module": None, "contact_name": None}


def _wanted(db: Session, *, phone: str) -> tuple[list[Any], str | None]:
    """The people this caller should reach, first choice first, and the
    caller's name: whoever works their open cards, the card moved last
    before the others; then whoever spoke with them last."""
    from app.modules.boards.models import BoardCard

    clients = list(
        db.scalars(
            select(User)
            .where(User.phone == phone, User.is_staff.is_(False))
            .order_by(User.date_joined)
        )
    )
    name = next((c.full_name for c in clients if c.full_name), None)
    people: list[Any] = []
    if clients:
        people += db.scalars(
            select(BoardCard.manager_id)
            .where(
                BoardCard.owner_id.in_([client.id for client in clients]),
                BoardCard.closed_at.is_(None),
                BoardCard.manager_id.is_not(None),
            )
            .order_by(BoardCard.column_since.desc())
        )
    return people, name


def _spoke_last(
    db: Session, *, connection: PhoneConnection, phone: str, now: datetime
) -> Any:
    return db.scalar(
        select(PhoneCall.user_id)
        .where(
            PhoneCall.connection_id == connection.id,
            PhoneCall.number == phone,
            PhoneCall.answered.is_(True),
            PhoneCall.user_id.is_not(None),
            PhoneCall.started_at >= now - timedelta(days=ROUTE_RECENT_DAYS),
        )
        .order_by(PhoneCall.started_at.desc())
        .limit(1)
    )


def route(
    db: Session, *, connection: PhoneConnection, number: object, now: datetime
) -> dict[str, Any]:
    """The answer for UTeL, in both shapes it is known to read: the
    internal number as ``extension`` (text) and as ``module`` (number)."""
    phone = calls.as_phone(number)
    if not phone or calls.is_extension(phone):
        return dict(NOBODY)
    people, name = _wanted(db, phone=phone)
    last = _spoke_last(db, connection=connection, phone=phone, now=now)
    if last is not None:
        people.append(last)
    seen: set[Any] = set()
    for person_id in people:
        if person_id in seen:
            continue
        seen.add(person_id)
        extension = db.scalar(
            select(PhoneExtension.number)
            .join(User, User.id == PhoneExtension.user_id)
            .where(
                PhoneExtension.connection_id == connection.id,
                PhoneExtension.user_id == person_id,
                PhoneExtension.is_gone.is_(False),
                User.is_active.is_(True),
                User.is_staff.is_(True),
            )
        )
        if not extension or not extension.isdigit():
            continue
        if live.is_busy(db, connection=connection, extension=extension, now=now):
            continue
        return {"extension": extension, "module": int(extension), "contact_name": name}
    return dict(NOBODY) | {"contact_name": name}


def answer(
    db: Session, *, key: str, number: object, now: datetime
) -> dict[str, Any] | None:
    """None: the key opens nothing. Anything going wrong is nobody: the
    call must go on to the fallback group, not wait on us."""
    connection = db.scalar(
        select(PhoneConnection).where(PhoneConnection.hook_key == key)
    )
    if connection is None:
        return None
    try:
        found = route(db, connection=connection, number=number, now=now)
    except Exception:
        db.rollback()
        logger.exception("telephony: routing failed, the call goes to the group")
        return dict(NOBODY)
    logger.info("telephony route: %s", found["extension"] or "group")
    return found
