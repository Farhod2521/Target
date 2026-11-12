"""Calls going on right now: kept from the exchange's events as they come,
and told to every open office page over the support chat's hub.

The table is the truth; the hub only announces a row already committed,
and a hub that is down fails nothing - a page asks for the whole picture
when it opens and may ask again.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.telephony import calls
from app.modules.telephony.constants import (
    CALL_ID_MAX,
    CALL_SAVED,
    DIRECTION_LABELS,
    LIVE_CHANNEL,
    LIVE_STALE_HOURS,
    NUMBER_MAX,
    Direction,
    LiveState,
)
from app.modules.telephony.models import PhoneConnection, PhoneExtension, PhoneLiveCall

logger = logging.getLogger(__name__)

RINGING = "call.ringing"
TALKING = "call.talking"
ENDED = "call.ended"
SNAPSHOT = "snapshot"
_OVER = frozenset({"call_ended", CALL_SAVED})
_OPENING = frozenset({"call_started", "dial_started", "dial_answered"})


def _side(kind: object, src: str, dst: str) -> Direction | None:
    """In or out, from a call still going on: its type when it has one,
    else an internal number calling is ours calling out. None: colleagues."""
    name = str(kind or "").lower()
    if name.startswith("out"):
        return Direction.OUT
    if name.startswith("in") and not name.startswith("int"):
        return Direction.IN
    if name.startswith("int"):
        return None
    if calls.is_extension(src):
        return None if calls.is_extension(dst) else Direction.OUT
    return Direction.IN


def _ext(value: object) -> str:
    return calls._digits(value)[:NUMBER_MAX] if calls.is_extension(value) else ""


def note(
    db: Session, *, connection: PhoneConnection, name: str, data: dict[str, Any]
) -> dict[str, Any] | None:
    """Take one event into the picture and commit. Returns what to announce,
    or None when the event changes nothing we show."""
    call = data.get("call")
    saved = data.get("call_history")
    call_id = ""
    if isinstance(call, dict):
        call_id = str(call.get("id") or "")
    if not call_id and isinstance(saved, dict):
        call_id = str(saved.get("call_id") or "")
    call_id = call_id[:CALL_ID_MAX]
    if not call_id:
        return None
    mine = (
        PhoneLiveCall.connection_id == connection.id,
        PhoneLiveCall.call_id == call_id,
    )
    if name in _OVER:
        gone = db.execute(delete(PhoneLiveCall).where(*mine))
        db.commit()
        if not gone.rowcount:  # type: ignore[attr-defined]
            return None
        return {"type": ENDED, "call_id": call_id}
    if name not in _OPENING or not isinstance(call, dict):
        return None
    inner = call.get("cdr")
    cdr: dict[str, Any] = inner if isinstance(inner, dict) else {}
    src = str(cdr.get("src") or call.get("src") or "")
    dst = str(cdr.get("dst") or call.get("exten") or "")
    direction = _side(cdr.get("type"), src, dst)
    if direction is None:
        return None
    number = calls.as_phone(src if direction is Direction.IN else dst)
    if not number:
        return None
    answered = name == "dial_answered"
    if direction is Direction.OUT:
        extension = _ext(src)
    else:
        extension = _ext(cdr.get("last_answered")) if answered else ""
        extension = extension or _ext(cdr.get("dst"))
    state = LiveState.TALKING if answered else LiveState.RINGING
    now = utcnow()
    statement = insert(PhoneLiveCall).values(
        id=uuid.uuid4(),
        connection_id=connection.id,
        call_id=call_id,
        direction=str(direction),
        number=number,
        extension=extension,
        state=str(state),
        started_at=now,
        updated_at=now,
    )
    changes: dict[str, Any] = {"updated_at": now}
    if extension:
        changes["extension"] = extension
    if answered:
        changes["state"] = str(LiveState.TALKING)
    row = db.scalar(
        statement.on_conflict_do_update(
            index_elements=["connection_id", "call_id"], set_=changes
        ).returning(PhoneLiveCall),
        execution_options={"populate_existing": True},
    )
    db.commit()
    if row is None:
        return None
    (shown,) = _shown(db, [row])
    return {
        "type": TALKING if row.state == LiveState.TALKING else RINGING,
        "call": shown,
    }


def _shown(db: Session, rows: list[PhoneLiveCall]) -> list[dict[str, Any]]:
    """Each call with who is on it and whose number it is."""
    from app.modules.boards.models import BoardCard

    if not rows:
        return []
    holders = {
        number: person
        for number, person in db.execute(
            select(PhoneExtension.number, User)
            .join(User, User.id == PhoneExtension.user_id)
            .where(
                PhoneExtension.connection_id.in_({row.connection_id for row in rows}),
                PhoneExtension.number.in_({row.extension for row in rows} - {""}),
            )
        )
    }
    clients: dict[str, list[User]] = {}
    for person in db.scalars(
        select(User)
        .where(User.phone.in_({row.number for row in rows}), User.is_staff.is_(False))
        .order_by(User.date_joined)
    ):
        clients.setdefault(person.phone, []).append(person)
    owners = {person.id for people in clients.values() for person in people}
    cards: dict[uuid.UUID, dict[str, str]] = {}
    if owners:
        for card_id, board, owner_id in db.execute(
            select(BoardCard.id, BoardCard.board, BoardCard.owner_id).where(
                BoardCard.owner_id.in_(owners)
            )
        ):
            cards.setdefault(owner_id, {})[board] = str(card_id)
    return [
        {
            "call_id": row.call_id,
            "direction": row.direction,
            "direction_label": str(DIRECTION_LABELS[Direction(row.direction)]),
            "state": row.state,
            "number": row.number,
            "extension": row.extension,
            "staff": calls._person(holders.get(row.extension)),
            "started_at": row.started_at.isoformat(),
            "clients": [
                {
                    "id": str(person.id),
                    "name": person.full_name or person.email,
                    "email": person.email,
                    "sales_card_id": cards.get(person.id, {}).get("sales"),
                    "support_card_id": cards.get(person.id, {}).get("support"),
                }
                for person in clients.get(row.number, [])
            ],
        }
        for row in rows
    ]


def snapshot(db: Session, *, now: datetime) -> dict[str, Any]:
    """Every call going on, oldest first, and the internal numbers talking."""
    rows = list(
        db.scalars(
            select(PhoneLiveCall)
            .where(PhoneLiveCall.updated_at >= now - timedelta(hours=LIVE_STALE_HOURS))
            .order_by(PhoneLiveCall.started_at, PhoneLiveCall.id)
        )
    )
    shown = _shown(db, rows)
    return {
        "calls": shown,
        "busy": sorted(
            {
                call["extension"]
                for call in shown
                if call["extension"] and call["state"] == LiveState.TALKING
            }
        ),
    }


def is_busy(
    db: Session, *, connection: PhoneConnection, extension: str, now: datetime
) -> bool:
    return bool(
        db.scalar(
            select(PhoneLiveCall.id)
            .where(
                PhoneLiveCall.connection_id == connection.id,
                PhoneLiveCall.extension == extension,
                PhoneLiveCall.updated_at >= now - timedelta(hours=LIVE_STALE_HOURS),
            )
            .limit(1)
        )
    )


def forget_stale(db: Session, *, now: datetime) -> int:
    gone = db.execute(
        delete(PhoneLiveCall).where(
            PhoneLiveCall.updated_at < now - timedelta(hours=LIVE_STALE_HOURS)
        )
    )
    db.commit()
    return int(gone.rowcount or 0)  # type: ignore[attr-defined]


def announce(event: dict[str, Any]) -> None:
    """Best effort on purpose: the picture is already committed."""
    from app.modules.supportchat.live import hub

    try:
        hub.publish(LIVE_CHANNEL, event)
    except Exception:
        logger.warning("telephony live event not sent: %s", event.get("type"))
