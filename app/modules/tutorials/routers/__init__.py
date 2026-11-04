"""Video darsliklar in the cabinet: what the office has switched on.

``GET /tutorials`` is the list (``type``, ``q`` over the title and the
description, ``offset``); each row's ``image_url`` and ``video.stream_url``
carry their own token and play for a few hours, so a lesson left open past
that asks the list again. ``/video`` answers 206 one piece at a time.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.modules.tutorials import playback
from app.modules.tutorials.constants import TUTORIAL_TYPE_LABELS, TutorialType
from app.modules.tutorials.exceptions import TutorialNotFound
from app.modules.tutorials.models import Tutorial
from app.modules.tutorials.selectors import tutorial_by_id, tutorial_page

BASE = "/api/v1/tutorials"
router = APIRouter(prefix="/tutorials", tags=["tutorials"])


def type_choices() -> list[dict[str, str]]:
    return [
        {"value": str(kind), "label": TUTORIAL_TYPE_LABELS[kind]}
        for kind in TutorialType
    ]


def tutorial_out(row: Tutorial, **links: Any) -> dict[str, Any]:
    kind = TutorialType(row.type) if row.type in TutorialType.values else None
    return {
        "id": str(row.id),
        "title": row.title,
        "type": row.type,
        "type_label": TUTORIAL_TYPE_LABELS[kind] if kind else row.type,
        "description": row.description,
        **playback.links(row, base=BASE, **links),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("")
def tutorials(
    db: Db,
    user: CurrentUser,
    type: TutorialType | None = Query(None, description="One network's lessons."),
    q: str = Query("", max_length=100, description="Part of the title or description."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The lessons switched on, newest first."""
    page = tutorial_page(
        db, type=str(type or ""), term=q.strip(), active=True, offset=offset
    )
    now = utcnow()
    return {
        "rows": [
            tutorial_out(row, user=user, office=False, now=now) for row in page.rows
        ],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "types": type_choices(),
    }


@router.get("/{tutorial_id}")
def tutorial(tutorial_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, Any]:
    row = tutorial_by_id(db, tutorial_id, active_only=True)
    if row is None:
        raise TutorialNotFound
    return tutorial_out(row, user=user, office=False, now=utcnow())


@router.get("/{tutorial_id}/image")
def tutorial_image(
    tutorial_id: uuid.UUID, db: Db, t: str = Query(description="From `image_url`.")
) -> Response:
    return playback.image_response(
        playback.playable(db, token=t, tutorial_id=tutorial_id)
    )


@router.get("/{tutorial_id}/video")
def tutorial_video(
    tutorial_id: uuid.UUID,
    db: Db,
    t: str = Query(description="From `video.stream_url`."),
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """One piece of the video: the range asked for, cut to a couple of MB."""
    row = playback.playable(db, token=t, tutorial_id=tutorial_id)
    return playback.video_response(row, range_header=range_header)
