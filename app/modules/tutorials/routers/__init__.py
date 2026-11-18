"""Video darsliklar in the cabinet: what the office has switched on.

``GET /tutorials`` is the list (``type``, ``place``, ``q`` over the title
and the description, ``offset``); a screen other than Darsliklar asks it
with its own ``place`` and shows what comes back; each row's ``image_url`` and ``video.stream_url``
carry their own token and play for a few hours, so a lesson left open past
that asks the list again. ``/video`` answers 206 one piece at a time.

A lesson is shown in the reader's language: ``lang`` when sent (the site's
own), else the account's. A lesson not written in it shows its first
written language of uz, ru, en; ``language`` says which one came back.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Header, Query, Response

from app.api.deps import CurrentUser, Db
from app.common.db import utcnow
from app.common.i18n import get_language
from app.modules.tutorials import playback
from app.modules.tutorials.constants import (
    TUTORIAL_LANGUAGE_LABELS,
    TUTORIAL_PLACE_LABELS,
    TUTORIAL_TYPE_LABELS,
    TutorialLanguage,
    TutorialPlace,
    TutorialType,
)
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


def place_choices() -> list[dict[str, str]]:
    return [
        {"value": str(place), "label": TUTORIAL_PLACE_LABELS[place]}
        for place in TutorialPlace
    ]


def language_choices() -> list[dict[str, str]]:
    return [
        {"value": str(language), "label": TUTORIAL_LANGUAGE_LABELS[language]}
        for language in TutorialLanguage
    ]


def reader_language(sent: TutorialLanguage | None) -> str:
    """The language asked for, else the signed-in account's."""
    return str(sent) if sent else get_language()


def tutorial_out(row: Tutorial, *, wanted: str, **links: Any) -> dict[str, Any]:
    """The lesson in the language a reader of ``wanted`` sees."""
    kind = TutorialType(row.type) if row.type in TutorialType.values else None
    language = row.language_for(wanted)
    return {
        "id": str(row.id),
        "language": language,
        "languages": row.languages,
        "title": row.part("title", language),
        "type": row.type,
        "type_label": TUTORIAL_TYPE_LABELS[kind] if kind else row.type,
        "places": [
            {"value": place, "label": TUTORIAL_PLACE_LABELS[TutorialPlace(place)]}
            for place in row.places or ()
            if place in TutorialPlace.values
        ],
        "description": row.part("description", language),
        **playback.links(row, base=BASE, language=language, **links),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@router.get("")
def tutorials(
    db: Db,
    user: CurrentUser,
    type: TutorialType | None = Query(None, description="One network's lessons."),
    place: TutorialPlace | None = Query(
        None, description="The lessons one screen shows beside its work."
    ),
    q: str = Query("", max_length=100, description="Part of a title or description."),
    lang: TutorialLanguage | None = Query(
        None, description="The site's language; empty is the account's."
    ),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """The lessons switched on, newest first, each in the reader's language."""
    page = tutorial_page(
        db,
        type=str(type or ""),
        place=str(place or ""),
        term=q.strip(),
        active=True,
        offset=offset,
    )
    now = utcnow()
    wanted = reader_language(lang)
    return {
        "rows": [
            tutorial_out(row, wanted=wanted, user=user, office=False, now=now)
            for row in page.rows
        ],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "types": type_choices(),
        "places": place_choices(),
        "languages": language_choices(),
    }


@router.get("/{tutorial_id}")
def tutorial(
    tutorial_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    lang: TutorialLanguage | None = Query(
        None, description="The site's language; empty is the account's."
    ),
) -> dict[str, Any]:
    row = tutorial_by_id(db, tutorial_id, active_only=True)
    if row is None:
        raise TutorialNotFound
    return tutorial_out(
        row, wanted=reader_language(lang), user=user, office=False, now=utcnow()
    )


@router.get("/{tutorial_id}/image")
def tutorial_image(
    tutorial_id: uuid.UUID,
    db: Db,
    t: str = Query(description="From `image_url`."),
    lang: TutorialLanguage = Query(
        TutorialLanguage.UZ, description="From `image_url`."
    ),
) -> Response:
    return playback.image_response(
        playback.playable(db, token=t, tutorial_id=tutorial_id), language=str(lang)
    )


@router.get("/{tutorial_id}/video")
def tutorial_video(
    tutorial_id: uuid.UUID,
    db: Db,
    t: str = Query(description="From `video.stream_url`."),
    lang: TutorialLanguage = Query(
        TutorialLanguage.UZ, description="From `video.stream_url`."
    ),
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """One piece of the video: the range asked for, cut to a couple of MB."""
    row = playback.playable(db, token=t, tutorial_id=tutorial_id)
    return playback.video_response(row, language=str(lang), range_header=range_header)
