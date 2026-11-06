"""The site's news: broadcasts the office ticked "Sayt" for, once sent.

``GET /news`` is the list, newest first, with ``unread``: how many came
since the reader last opened it. ``POST /news/seen`` marks them read.
``image_url`` carries its own token and opens for a few hours.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.broadcasts import media
from app.modules.broadcasts.exceptions import BroadcastNotFound
from app.modules.broadcasts.models import Broadcast, BroadcastSeen
from app.modules.broadcasts.selectors import (
    seen_at,
    site_broadcast,
    site_page,
    unread_count,
)

router = APIRouter(prefix="/news", tags=["news"])


def news_out(row: Broadcast, *, since: datetime, now: datetime) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "body": row.body,
        "image_url": media.image_url(row, office=False, now=now),
        "published_at": row.started_at.isoformat() if row.started_at else None,
        "is_unread": bool(row.started_at and row.started_at > since),
    }


@router.get("")
def news(db: Db, user: CurrentUser, offset: int = Query(0, ge=0)) -> dict[str, Any]:
    page = site_page(db, user=user, offset=offset)
    since, now = seen_at(db, user=user), utcnow()
    return {
        "rows": [news_out(row, since=since, now=now) for row in page.rows],
        "unread": unread_count(db, user=user),
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
    }


@router.get("/unread")
def unread(db: Db, user: CurrentUser) -> dict[str, int]:
    """For the badge, without the list."""
    return {"unread": unread_count(db, user=user)}


@router.post("/seen")
def mark_seen(db: Db, user: CurrentUser) -> dict[str, int]:
    """Everything published until now is read."""
    now = utcnow()
    statement = insert(BroadcastSeen).values(
        id=uuid.uuid4(), owner_id=user.id, seen_at=now, created_at=now, updated_at=now
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[BroadcastSeen.owner_id],
            set_={"seen_at": now, "updated_at": now},
        )
    )
    db.commit()
    return {"unread": 0}


@router.get("/{broadcast_id}")
def one(broadcast_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    row = site_broadcast(db, broadcast_id, user=user)
    if row is None:
        raise BroadcastNotFound
    return news_out(row, since=seen_at(db, user=user), now=utcnow())


@router.get("/{broadcast_id}/image")
def image(
    broadcast_id: uuid.UUID, db: Db, t: str = Query(description="From `image_url`.")
) -> Response:
    return media.image_response(db, broadcast_id=broadcast_id, token=t)
