"""The draft's pictures step: the library, the files taken out of it, and uploads.

A file goes up whole (``POST /media/upload``) or, when it is larger than one
piece, in pieces: ``POST /media/upload/chunk`` once per piece (headers
``X-Upload-Id``, ``X-Upload-Size``, ``X-Upload-Offset``; a 409 names the
offset to resend from), then ``POST /media/upload/finish``. Either answers
the tile the file now has on the grid.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Header, Request, Response, UploadFile, status

from app.api.deps import CurrentUser, Db
from app.common.exceptions import DomainError
from app.modules.ads.contract.launch import taps as kept
from app.modules.ads.contract.launch.media import UPLOAD_TILE, asset, library
from app.modules.ads.contract.launch.shapes import MediaAsset, MediaLibrary, UploadDone
from app.modules.ads.exceptions import (
    FileInUse,
    MediaAskedRecently,
    MediaInUse,
    SyncAlreadyRunning,
)
from app.modules.ads.routers import launch_media as media_routes
from app.modules.ads.routers.drafts import launch_of
from app.modules.ads.routers.launch_media import FinishIn

router = APIRouter(prefix="/launch/drafts", tags=["launch: media"])


def read_media(db: Db, user: CurrentUser, draft_id: uuid.UUID) -> MediaLibrary:
    """Both grids: the step serves one source per read."""
    first = media_routes.media_page(draft_id, db, user, source="")
    sources = first.get("sources")
    if sources:
        instagram = next(
            (row["value"] for row in sources if row.get("is_instagram")), ""
        )
        own = first.get("library_source") or ""

        def read(source: str) -> dict[str, Any]:
            if source == first.get("source"):
                return first
            return media_routes.media_page(draft_id, db, user, source=source)

        grids = library(
            read(instagram) if instagram else None, read(own) if own else None
        )
    else:
        grids = library(first, None)
    shown = MediaLibrary.model_validate(grids)
    # What the launch holds and what was listed: a tick on anything else is stale.
    taps = kept.read(draft_id)
    taps["known"] = [tile.id for tile in [*shown.posts, *shown.library]]
    kept.write(draft_id, taps)
    return shown


@router.get("/{draft_id}/media", response_model=MediaLibrary)
def media(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> MediaLibrary:
    launch_of(db, user=user, draft_id=draft_id)
    return read_media(db, user, draft_id)


@router.post("/{draft_id}/media/refresh", response_model=MediaLibrary)
def refresh(draft_id: uuid.UUID, db: Db, user: CurrentUser) -> MediaLibrary:
    """Ask the network for the library again; asked a moment ago, the list as it stands."""
    try:
        media_routes.media_refresh(draft_id, db, user)
    except (MediaAskedRecently, SyncAlreadyRunning):
        db.rollback()
    return read_media(db, user, draft_id)


@router.delete("/{draft_id}/media/held/{position}", response_model=MediaLibrary)
def release(
    draft_id: uuid.UUID, position: int, db: Db, user: CurrentUser
) -> MediaLibrary:
    """Take a held tile out of the launch: the picture and the words that went with it."""
    media_routes.media_remove(draft_id, position, db, user)
    return read_media(db, user, draft_id)


def _tile(
    db: Db, user: CurrentUser, draft_id: uuid.UUID, *, name: str, video: bool
) -> MediaAsset:
    """The upload's tile: the newest one the network has not taken in, or the library's newest."""
    try:
        shown = read_media(db, user, draft_id)
    except DomainError:
        db.rollback()
        shown = None
    if shown is not None and shown.uploads:
        return shown.uploads[-1]
    if shown is not None and shown.library:
        return shown.library[0]
    return MediaAsset.model_validate(
        asset(
            {
                "id": f"{UPLOAD_TILE}new",
                "name": name,
                "kind": "video" if video else "image",
            }
        )
    )


@router.post("/{draft_id}/media/upload", response_model=MediaAsset)
def upload(
    draft_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="One picture or video.")],
) -> MediaAsset:
    """One file, into this launch and the ad account's library."""
    media_routes.media_upload(draft_id, db, user, file=file, assets="")
    name = file.filename or "file"
    return _tile(
        db,
        user,
        draft_id,
        name=name,
        video=(file.content_type or "").startswith("video/"),
    )


@router.post("/{draft_id}/media/upload/chunk")
async def upload_chunk(
    draft_id: uuid.UUID,
    request: Request,
    db: Db,
    user: CurrentUser,
    upload_id: Annotated[str, Header(alias="X-Upload-Id")] = "",
    total: Annotated[int, Header(alias="X-Upload-Size")] = -1,
    offset: Annotated[int, Header(alias="X-Upload-Offset")] = -1,
) -> Any:
    """One piece. Answers how much of the file is here now."""
    return await media_routes.media_chunk(
        draft_id, request, db, user, upload_id=upload_id, total=total, offset=offset
    )


@router.post("/{draft_id}/media/upload/finish", response_model=MediaAsset)
def upload_finish(
    draft_id: uuid.UUID, body: UploadDone, db: Db, user: CurrentUser
) -> MediaAsset:
    """Every piece is here: the file joins the launch, as one upload would."""
    media_routes.media_chunk_finish(
        draft_id,
        FinishIn(upload_id=body.upload_id, total=body.total, name=body.name),
        db,
        user,
    )
    video = body.name.lower().endswith((".mp4", ".mov", ".m4v"))
    return _tile(db, user, draft_id, name=body.name, video=video)


@router.delete("/{draft_id}/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    draft_id: uuid.UUID, asset_id: uuid.UUID, db: Db, user: CurrentUser
) -> Response:
    """Take one file off the ad account's library; one a running advert uses is a 409."""
    try:
        media_routes.media_delete(draft_id, asset_id, db, user)
    except MediaInUse as used:
        raise FileInUse(used.message) from used
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["read_media", "router"]
