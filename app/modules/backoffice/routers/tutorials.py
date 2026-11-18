"""Video darsliklar in the office, as JSON. Support, Finance and Owner.

A lesson is a multipart form: the fields, and ``image`` when the cover
changes. The video is either ``video_url`` (YouTube or any other site) or a
file sent beforehand in pieces: ``POST /tutorials/uploads/chunk`` once per
piece (``X-Upload-Id`` a fresh UUID, ``X-Upload-Size``, ``X-Upload-Offset``
headers, the piece as the body; a 409 names the offset to resend from),
then the create or the edit names ``video_upload_id``, ``video_size`` and
``video_name``. Never both: switching an uploaded lesson to a link sends
``remove_video``. ``status`` true shows it in the cabinet. ``places`` is
sent once per screen the lesson shows on (``places=crm&places=leads``); one
empty ``places`` clears them, and an edit without the field keeps them.

Languages: ``title``, ``description``, ``video_url``, ``image``,
``remove_image``, ``video_upload_id``, ``video_size``, ``video_name`` and
``remove_video`` are the Uzbek lesson; the same names ending in ``_ru`` and
``_en`` are the Russian and the English one, each with its own cover and
video. At least one language is written; one sent empty (its files removed)
is dropped. A refusal names the field with its ending (``title_ru``). The
cabinet shows a reader's own language, else the first written of uz, ru, en.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Form, Header, Query, Request
from fastapi import status as http
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.datastructures import UploadFile

from app.api.deps import Db
from app.common import storage
from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.ads.exceptions import ChunkOutOfPlace, ChunkTooLarge
from app.modules.backoffice.constants import ADMIN_ROLES
from app.modules.backoffice.permissions import staff_required
from app.modules.backoffice.schemas import CreatedOut, MessageOut
from app.modules.tutorials import services
from app.modules.tutorials.constants import (
    UPLOAD_CHUNK_BYTES,
    TutorialLanguage,
    TutorialPlace,
    TutorialType,
)
from app.modules.tutorials.exceptions import TutorialNotFound
from app.modules.tutorials.models import Tutorial
from app.modules.tutorials.models.tutorial import column
from app.modules.tutorials.routers import (
    language_choices,
    place_choices,
    tutorial_out,
    type_choices,
)
from app.modules.tutorials.selectors import tutorial_by_id, tutorial_page

router = APIRouter(prefix="/tutorials")
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]


class StatusIn(BaseModel):
    status: bool


def _out(row: Tutorial, *, user: User) -> dict[str, Any]:
    """The lesson as the cabinet's Uzbek reader sees it, and under
    ``versions`` every language as written (``null``: not written)."""
    now = utcnow()
    shown = row.language_for(TutorialLanguage.UZ)
    versions: dict[str, Any] = {}
    for language in TutorialLanguage.values:
        if language not in row.languages:
            versions[language] = None
            continue
        own = tutorial_out(row, wanted=language, user=user, office=True, now=now)
        versions[language] = {
            "title": own["title"],
            "description": own["description"],
            "video_url": row.part("video_url", language),
            "has_video_file": bool(row.part("video_file", language)),
            "has_image": bool(row.part("image", language)),
            "image_url": own["image_url"] if row.part("image", language) else None,
            "video": own["video"],
        }
    return {
        **tutorial_out(row, wanted=shown, user=user, office=True, now=now),
        "status": row.is_active,
        "video_url": row.part("video_url", shown),
        "has_video_file": bool(row.part("video_file", shown)),
        "versions": versions,
    }


def _row(db: Db, tutorial_id: uuid.UUID) -> Tutorial:
    row = tutorial_by_id(db, tutorial_id, active_only=False)
    if row is None:
        raise TutorialNotFound
    return row


def _video(
    actor: User, *, upload_id: str, size: int, name: str
) -> services.VideoUpload | None:
    if not upload_id:
        return None
    return services.assembled_video(
        staff_id=actor.id, upload_id=upload_id, total=size, name=name
    )


def _flag(value: Any) -> bool:
    return str(value or "").strip().lower() in ("true", "1", "on", "yes")


async def _versions(request: Request) -> dict[str, dict[str, Any]]:
    """Each language's fields from the form, by the names in the docstring."""
    form = await request.form()
    versions: dict[str, dict[str, Any]] = {}
    for language in TutorialLanguage.values:

        def field(name: str, language: str = language) -> Any:
            return form.get(column(name, language))

        image = field("image")
        size = str(field("video_size") or "0").strip()
        versions[language] = {
            "title": str(field("title") or ""),
            "description": str(field("description") or ""),
            "video_url": str(field("video_url") or ""),
            "image": image
            if isinstance(image, UploadFile) and image.filename
            else None,
            "remove_image": _flag(field("remove_image")),
            "upload_id": str(field("video_upload_id") or ""),
            "size": int(size) if size.isdigit() else 0,
            "name": str(field("video_name") or ""),
            "remove_video": _flag(field("remove_video")),
        }
    return versions


Versions = Annotated[dict[str, dict[str, Any]], Depends(_versions)]


def _body(
    actor: User,
    *,
    type: str,
    status: bool,
    places: list[str] | None,
    versions: dict[str, dict[str, Any]],
) -> services.TutorialIn:
    return services.TutorialIn(
        type=type,
        is_active=status,
        places=_places(places),
        versions={
            language: services.VersionIn(
                title=sent["title"],
                description=sent["description"],
                video_url=sent["video_url"],
                image=sent["image"],
                video=_video(
                    actor,
                    upload_id=sent["upload_id"],
                    size=sent["size"],
                    name=sent["name"],
                ),
                remove_image=sent["remove_image"],
                remove_video=sent["remove_video"],
            )
            for language, sent in versions.items()
        },
    )


def _places(sent: list[str] | None) -> list[str] | None:
    """None: the field was not sent. An empty value is how a form says none."""
    return None if sent is None else [place for place in sent if place]


def _committed(db: Db, saved: services.Saved) -> None:
    """The new files stay only if the row does; the old ones go only then."""
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
def tutorials(
    db: Db,
    user: Admin,
    type: TutorialType | None = Query(None),
    place: TutorialPlace | None = Query(None, description="Shown on this screen."),
    q: str = Query("", max_length=100, description="Part of the title or description."),
    status: bool | None = Query(None, description="Shown or hidden; empty is both."),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    page = tutorial_page(
        db,
        type=str(type or ""),
        place=str(place or ""),
        term=q.strip(),
        active=status,
        offset=offset,
    )
    return {
        "rows": [_out(row, user=user) for row in page.rows],
        "total": page.total,
        "offset": page.offset,
        "next_offset": page.next_offset,
        "has_more": page.has_more,
        "types": type_choices(),
        "places": place_choices(),
        "languages": language_choices(),
    }


@router.get("/{tutorial_id}")
def tutorial(tutorial_id: uuid.UUID, db: Db, user: Admin) -> dict[str, Any]:
    """One lesson, for the edit form; plays even while hidden."""
    return _out(_row(db, tutorial_id), user=user)


async def _piece(request: Request) -> bytes:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > UPLOAD_CHUNK_BYTES:
        raise ChunkTooLarge
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > UPLOAD_CHUNK_BYTES:
            raise ChunkTooLarge
    return bytes(data)


@router.post("/uploads/chunk")
async def upload_chunk(
    request: Request,
    actor: Admin,
    upload_id: Annotated[str, Header(alias="X-Upload-Id")] = "",
    total: Annotated[int, Header(alias="X-Upload-Size")] = -1,
    offset: Annotated[int, Header(alias="X-Upload-Offset")] = -1,
) -> Any:
    """One piece of a video, at most 8 MB. Answers how much is here now."""
    data = await _piece(request)
    try:
        here = await run_in_threadpool(
            services.append_chunk,
            staff_id=actor.id,
            upload_id=upload_id,
            total=total,
            offset=offset,
            data=data,
        )
    except ChunkOutOfPlace as exc:
        return JSONResponse({"offset": exc.offset}, status_code=http.HTTP_409_CONFLICT)
    return {"offset": here}


@router.post("", responses={200: {"model": CreatedOut}})
def create_tutorial(
    db: Db,
    actor: Admin,
    versions: Versions,
    type: Annotated[str, Form()] = "",
    places: Annotated[list[str] | None, Form()] = None,
    status: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Fields per language as the module's docstring names them."""
    body = _body(actor, type=type, status=status, places=places, versions=versions)
    saved = services.save_tutorial(db, body=body, row=None, actor=actor)
    _committed(db, saved)
    return {"message": "Video darslik qo'shildi.", "id": str(saved.row.id)}


@router.put("/{tutorial_id}", responses={200: {"model": MessageOut}})
def update_tutorial(
    tutorial_id: uuid.UUID,
    db: Db,
    actor: Admin,
    versions: Versions,
    type: Annotated[str, Form()] = "",
    places: Annotated[list[str] | None, Form()] = None,
    status: Annotated[bool, Form()] = False,
) -> dict[str, Any]:
    """Every field as it should be now. No image and no upload of a
    language keep its files there."""
    body = _body(actor, type=type, status=status, places=places, versions=versions)
    saved = services.save_tutorial(
        db, body=body, row=_row(db, tutorial_id), actor=actor
    )
    _committed(db, saved)
    return {"message": "Video darslik yangilandi."}


@router.patch("/{tutorial_id}/status", responses={200: {"model": MessageOut}})
def set_status(
    tutorial_id: uuid.UUID, body: StatusIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """Show it in the cabinet, or hide it, without touching the rest."""
    row = _row(db, tutorial_id)
    row.is_active = body.status
    db.commit()
    return {"message": "Ko'rsatiladi." if body.status else "Yashirildi."}


@router.delete("/{tutorial_id}", responses={200: {"model": MessageOut}})
def delete_tutorial(tutorial_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    files = services.delete_tutorial(db, row=_row(db, tutorial_id))
    db.commit()
    for name in files:
        storage.delete(name)
    return {"message": "Video darslik o'chirildi."}
