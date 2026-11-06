"""Rassilka in the office, as JSON. The superuser alone.

A broadcast is a multipart form: ``title``, ``body``, the three networks
``to_bot``, ``to_channel``, ``to_site``, and ``image`` when the picture
changes (``remove_image`` drops it). It is saved as a draft and edited
only as one. ``POST /{id}/test`` sends the bot's message to the sender's
own linked chat; ``POST /{id}/send`` sends it to every ticked network,
and ``POST /{id}/stop`` ends a bot send still going. ``networks`` says
which of the three this server can reach; ``GET /recipients`` how many
bot chats a send would go to now.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.deps import Db
from app.common import storage
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.backoffice.permissions import superuser_required
from app.modules.backoffice.schemas import CreatedOut, MessageOut
from app.modules.broadcasts import media, services
from app.modules.broadcasts.constants import (
    BROADCAST_STATUS_LABELS,
    DELIVERY_STATUS_LABELS,
    BroadcastStatus,
)
from app.modules.broadcasts.exceptions import BroadcastNotFound
from app.modules.broadcasts.models import Broadcast
from app.modules.broadcasts.selectors import (
    broadcast_by_id,
    delivery_counts,
    office_page,
    recipients,
)

router = APIRouter(prefix="/broadcasts")
Superuser = Annotated[User, Depends(superuser_required)]


def _out(row: Broadcast, *, counts: dict[str, int]) -> dict[str, Any]:
    status = BroadcastStatus(row.status)
    return {
        "id": str(row.id),
        "title": row.title,
        "body": row.body,
        "image_url": media.image_url(row, office=True, now=utcnow()),
        "to_bot": row.to_bot,
        "to_channel": row.to_channel,
        "to_site": row.to_site,
        "status": row.status,
        "status_label": BROADCAST_STATUS_LABELS[status],
        "bot": {
            "total": sum(counts.values()),
            **counts,
            "labels": {
                str(key): label for key, label in DELIVERY_STATUS_LABELS.items()
            },
        },
        "channel": {
            "posted": bool(row.channel_message_id),
            "error": row.channel_error,
        },
        "created_at": row.created_at.isoformat(),
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
    }


def _one(db: Db, row: Broadcast) -> dict[str, Any]:
    return _out(row, counts=delivery_counts(db, [row.id])[row.id])


def _row(db: Db, broadcast_id: uuid.UUID) -> Broadcast:
    row = broadcast_by_id(db, broadcast_id)
    if row is None:
        raise BroadcastNotFound
    return row


def _committed(db: Db, saved: services.Saved) -> None:
    """The new picture stays only if the row does; the old one goes only then."""
    try:
        db.commit()
    except Exception:
        db.rollback()
        for name in saved.fresh:
            storage.delete(name)
        raise
    for name in saved.stale:
        storage.delete(name)


@router.get("")
def broadcasts(
    db: Db,
    user: Superuser,
    status: BroadcastStatus | None = Query(None),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    page = office_page(db, status=str(status or ""), offset=offset)
    counts = delivery_counts(db, [row.id for row in page.rows])
    return {
        "rows": [_out(row, counts=counts[row.id]) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "networks": services.networks(),
        "statuses": [
            {"value": str(key), "label": label}
            for key, label in BROADCAST_STATUS_LABELS.items()
        ],
    }


@router.get("/recipients")
def recipient_count(db: Db, user: Superuser) -> dict[str, int]:
    """How many bot chats a send would go to now, for the confirmation."""
    return {"bot": len(recipients(db))}


@router.get("/{broadcast_id}")
def broadcast(broadcast_id: uuid.UUID, db: Db, user: Superuser) -> dict[str, Any]:
    return _one(db, _row(db, broadcast_id))


@router.post("", responses={200: {"model": CreatedOut}})
def create_broadcast(
    db: Db,
    actor: Superuser,
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    to_bot: Annotated[bool, Form()] = False,
    to_channel: Annotated[bool, Form()] = False,
    to_site: Annotated[bool, Form()] = False,
    image: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    saved = services.save_broadcast(
        db,
        body=services.BroadcastIn(
            title=title,
            body=body,
            to_bot=to_bot,
            to_channel=to_channel,
            to_site=to_site,
            image=image,
        ),
        row=None,
        actor=actor,
    )
    _committed(db, saved)
    return {"message": "Qoralama saqlandi.", "id": str(saved.row.id)}


@router.put("/{broadcast_id}", responses={200: {"model": MessageOut}})
def update_broadcast(
    broadcast_id: uuid.UUID,
    db: Db,
    actor: Superuser,
    title: Annotated[str, Form()] = "",
    body: Annotated[str, Form()] = "",
    to_bot: Annotated[bool, Form()] = False,
    to_channel: Annotated[bool, Form()] = False,
    to_site: Annotated[bool, Form()] = False,
    image: Annotated[UploadFile | None, File()] = None,
    remove_image: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Every field as it should be now; no ``image`` keeps the picture."""
    saved = services.save_broadcast(
        db,
        body=services.BroadcastIn(
            title=title,
            body=body,
            to_bot=to_bot,
            to_channel=to_channel,
            to_site=to_site,
            image=image,
            remove_image=remove_image,
        ),
        row=_row(db, broadcast_id),
        actor=actor,
    )
    _committed(db, saved)
    return {"message": "Qoralama saqlandi."}


@router.delete("/{broadcast_id}", responses={200: {"model": MessageOut}})
def delete_broadcast(
    broadcast_id: uuid.UUID, db: Db, actor: Superuser
) -> dict[str, Any]:
    files = services.delete_broadcast(db, row=_row(db, broadcast_id))
    db.commit()
    for name in files:
        storage.delete(name)
    return {"message": "Rassilka o'chirildi."}


@router.post("/{broadcast_id}/test", responses={200: {"model": MessageOut}})
def test_broadcast(broadcast_id: uuid.UUID, db: Db, actor: Superuser) -> dict[str, Any]:
    services.send_test(db, row=_row(db, broadcast_id), actor=actor)
    db.commit()
    return {"message": "Test xabar botingizga yuborildi."}


@router.post("/{broadcast_id}/send")
def send_broadcast(broadcast_id: uuid.UUID, db: Db, actor: Superuser) -> dict[str, Any]:
    row = _row(db, broadcast_id)
    chats = services.start(db, row=row)
    db.commit()
    return {"message": "Rassilka yuborilmoqda.", "bot_chats": chats, **_one(db, row)}


@router.post("/{broadcast_id}/stop")
def stop_broadcast(broadcast_id: uuid.UUID, db: Db, actor: Superuser) -> dict[str, Any]:
    row = _row(db, broadcast_id)
    services.stop(db, row=row)
    db.commit()
    return {"message": "Rassilka to'xtatildi.", **_one(db, row)}
