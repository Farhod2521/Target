"""The wizard's pictures step.

``GET /media`` draws the step: the sources, the library grid, the adverts
chosen so far and the text panel. Opening it asks the provider for the
library again when it is stale; poll ``GET /media/status`` while
``keep_polling`` holds to learn when new files arrive.

A file from the phone goes up whole through ``POST /media/upload``, or in
pieces: ``POST /media/upload/chunk`` once per piece (``X-Upload-Id``,
``X-Upload-Size`` and ``X-Upload-Offset`` headers, the piece as the body;
a 409 names the offset to resend from), then ``POST /media/upload/finish``.

``POST /media`` is "Davom etish": the tiles ticked, the texts, and - once
every advert has its words - the proposal set going.
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Header, Query, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.common import storage
from app.common.db import utcnow
from app.common.exceptions import InputRefused, NotFound
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    MAX_BRIEF_CHARS,
    UPLOAD_CHUNK_BYTES,
    LaunchStatus,
    TextMode,
)
from app.modules.ads.exceptions import ChunkOutOfPlace, ChunkTooLarge
from app.modules.ads.inputs import Problems
from app.modules.ads.inputs.media import (
    NOTHING_CHOSEN,
    MediaContinueIn,
    MediaTextIn,
    asset_briefs,
    check_file,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.routers.launch_common import (
    committed,
    encoded,
    launch_head,
    owned_launch,
    writable_launch,
)
from app.modules.ads.selectors.cards import library_tile
from app.modules.ads.selectors.launch_page import launch_page
from app.modules.ads.selectors.library import (
    deleting_files,
    failed_deletes,
    media_usage,
)
from app.modules.ads.selectors.media import (
    instagram_source_page,
    library_asset,
    media_sources,
    upload_target,
)
from app.modules.ads.selectors.media_step import (
    chosen_source,
    media_step,
    status_poll,
)
from app.modules.ads.selectors.schedule import max_creatives
from app.modules.ads.selectors.variants import launch_variants, variant_upload
from app.modules.ads.services import launch as launch_services
from app.modules.ads.services import library, media, variants
from app.modules.ads.services.launch import is_discardable
from app.modules.integrations.selectors.pages import instagram_profile
from app.modules.integrations.services.discover import learn_business_on_open

router = APIRouter(prefix="/launch", tags=["launch: media"])
UPLOAD_TAKEN = (
    "Fayl yuklandi. U Meta kutubxonasida bir necha daqiqada ko'rinadi, "
    "biroz kutib turing."
)
ASKED = "Meta'dan so'raldi. Bir necha soniyadan keyin yangilang."


class FinishIn(BaseModel):
    upload_id: str
    total: int = Field(ge=1)
    name: str
    asset_ids: list[str] = Field(default_factory=list)


def _open_refreshes(db: Session, *, launch: CampaignLaunch, source: str) -> bool:
    """What opening the step sets going. True when the library is being read."""
    page = launch_page(db, launch=launch)
    shown = instagram_source_page(db, owner=launch.owner, page=page, source=source)
    if shown is not None:
        queued = media.refresh_instagram_on_open(db, page=shown)
    else:
        queued = launch.ad_account is not None and media.refresh_media_on_open(
            db, ad_account=launch.ad_account
        )
    if launch.ad_account is not None:
        learn_business_on_open(db, ad_account=launch.ad_account)
    db.commit()
    return bool(queued)


@router.get("/{launch_id}/media")
def media_page(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    source: str = Query("", description="Which profile the grid shows."),
) -> dict[str, Any]:
    launch = owned_launch(db, user=user, launch_id=launch_id)
    page = launch_page(db, launch=launch)
    sources = media_sources(db, owner=user, account=launch.ad_account, page=page)
    shown = chosen_source(sources, source)
    syncing = _open_refreshes(db, launch=launch, source=shown)
    now = utcnow()
    step = media_step(db, launch=launch, sources=sources, source=shown, now=now)
    showing = next((item for item in sources if item.value == shown), None)
    is_own = (
        showing is not None
        and showing.is_instagram
        and page is not None
        and showing.value == str(page.id)
    )
    synced = step["media_synced_at"]
    return encoded(
        {
            "launch": launch_head(launch),
            **step,
            "library_source": next(
                (item.value for item in sources if not item.is_instagram), ""
            ),
            "upload_target": upload_target(ad_account=launch.ad_account),
            "instagram_profile": instagram_profile(db, owner=user, page=page)
            if is_own
            else None,
            "source_handle": showing.label
            if showing is not None
            and showing.is_instagram
            and showing.label.startswith("@")
            else "",
            "media_since": int(synced.timestamp()) if synced else 0,
            "media_tries": 0,
            "keep_polling": syncing or bool(step["media_busy"]),
            "can_discard": is_discardable(db, launch=launch),
        }
    )


@router.get("/{launch_id}/media/status")
def media_status_poll(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    source: str = "",
    seen: int | None = Query(None, description="How many tiles the grid holds."),
    since: int | None = Query(None, description="The last `media_since`."),
    busy: int = Query(0, ge=0, description="The last `media_busy`."),
    tries: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Whether the library is being read, and what came of it."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    return encoded(
        status_poll(
            db,
            launch=launch,
            source=source,
            seen=seen,
            since=since,
            busy_before=busy,
            tries=tries + 1,
            now=utcnow(),
        )
    )


def _save_text(
    db: Session, *, launch: CampaignLaunch, text: MediaTextIn, asset_ids: list[str]
) -> None:
    for brief in [*text.briefs.values(), *text.asset_briefs.values()]:
        if len(brief) > MAX_BRIEF_CHARS:
            raise InputRefused({"text": f"Matn {MAX_BRIEF_CHARS} belgidan oshmasin."})
    made = {
        str(variant.media_asset_id): str(variant.id)
        for variant in launch_variants(db, launch=launch)
        if variant.media_asset_id and str(variant.media_asset_id) in asset_ids
    }
    variants.save_media_text(
        db,
        launch=launch,
        mode=text.mode or str(launch.answers.get("text_mode") or TextMode.SHARED),
        shared=text.shared,
        briefs=asset_briefs(text, variants=made),
    )


@router.post("/{launch_id}/media")
def media_continue(
    launch_id: uuid.UUID, body: MediaContinueIn, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """The tiles ticked and the texts written - then the proposal, once."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    chosen = len(launch_variants(db, launch=launch))
    limit = max_creatives()
    if not chosen + len(body.asset_ids):
        raise InputRefused({"asset_ids": NOTHING_CHOSEN})
    if chosen + len(body.asset_ids) > limit:
        free = max(0, limit - chosen)
        raise InputRefused(
            {
                "asset_ids": f"Ko'pi bilan {limit} ta rasm. Hozir {chosen} ta "
                f"tanlangan, yana {free} ta qo'sha olasiz."
            }
        )

    # Saved before the text gate, each on its own, as Django did: a missing
    # sentence must not cost somebody the tiles they just ticked.
    if body.asset_ids:
        committed(
            db,
            lambda: variants.add_media(
                db, launch=launch, asset_ids=body.asset_ids, uploads=[]
            ),
        )
    if body.text is not None:
        text = body.text
        committed(
            db,
            lambda: _save_text(db, launch=launch, text=text, asset_ids=body.asset_ids),
        )
    variants.require_ad_texts(db, launch=launch)
    db.refresh(launch)
    if (
        not draft_field.is_written(launch.draft)
        and launch.status != LaunchStatus.BUILDING
    ):
        committed(db, lambda: launch_services.request_preparation(db, launch=launch))
    return launch_head(launch) | {"next": "review"}


@router.post("/{launch_id}/media/text", status_code=status.HTTP_204_NO_CONTENT)
def media_text(
    launch_id: uuid.UUID, body: MediaTextIn, db: Db, user: CurrentUser
) -> None:
    """The text panel, saved as it is typed."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    committed(db, lambda: _save_text(db, launch=launch, text=body, asset_ids=[]))


def _take_file(
    db: Session, *, launch: CampaignLaunch, upload: Any, asset_ids: list[str]
) -> None:
    """The file into the launch and the library queue, with any tiles ticked."""

    def run() -> None:
        if asset_ids:
            variants.add_media(db, launch=launch, asset_ids=asset_ids, uploads=[])
        library.request_library_upload(db, launch=launch, upload=upload)

    committed(db, run)


def _ids(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


@router.post("/{launch_id}/media/upload")
def media_upload(
    launch_id: uuid.UUID,
    db: Db,
    user: CurrentUser,
    file: Annotated[UploadFile, File(description="One picture or video.")],
    assets: Annotated[str, Form(description="Tiles ticked, comma separated.")] = "",
) -> dict[str, str]:
    """One file, into this launch and the ad account's library."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    problems = Problems()
    check_file(file, problems=problems, field="file", number=None)
    problems.refuse()
    _take_file(db, launch=launch, upload=file, asset_ids=_ids(assets))
    return {"detail": UPLOAD_TAKEN}


async def _piece(request: Request) -> bytes:
    """The body, refused as soon as it is longer than one piece may be."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > UPLOAD_CHUNK_BYTES:
        raise ChunkTooLarge
    data = bytearray()
    async for part in request.stream():
        data += part
        if len(data) > UPLOAD_CHUNK_BYTES:
            raise ChunkTooLarge
    return bytes(data)


@router.post("/{launch_id}/media/upload/chunk")
async def media_chunk(
    launch_id: uuid.UUID,
    request: Request,
    db: Db,
    user: CurrentUser,
    upload_id: Annotated[str, Header(alias="X-Upload-Id")] = "",
    total: Annotated[int, Header(alias="X-Upload-Size")] = -1,
    offset: Annotated[int, Header(alias="X-Upload-Offset")] = -1,
) -> Any:
    """One piece. Answers how much of the file is here now.

    Async only to read the body; the query and the write to disk run in the
    thread pool, so a slow disk holds one thread and not every request.
    """
    launch = await run_in_threadpool(
        writable_launch, db, user=user, launch_id=launch_id
    )
    data = await _piece(request)
    try:
        here = await run_in_threadpool(
            library.append_chunk,
            launch=launch,
            upload_id=upload_id,
            total=total,
            offset=offset,
            data=data,
        )
    except ChunkOutOfPlace as exc:
        return JSONResponse(
            {"offset": exc.offset}, status_code=status.HTTP_409_CONFLICT
        )
    return {"offset": here}


@router.post("/{launch_id}/media/upload/finish")
def media_chunk_finish(
    launch_id: uuid.UUID, body: FinishIn, db: Db, user: CurrentUser
) -> dict[str, str]:
    """Every piece is here: the file joins the launch, as one upload would."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    upload = library.assembled_upload(
        launch=launch, upload_id=body.upload_id, total=body.total, name=body.name
    )
    problems = Problems()
    check_file(upload, problems=problems, field="file", number=None)
    try:
        problems.refuse()
        _take_file(db, launch=launch, upload=upload, asset_ids=body.asset_ids)
    finally:
        library.discard_upload(upload=upload)
    return {"detail": UPLOAD_TAKEN}


@router.get("/{launch_id}/media/{position}/file")
def media_file(
    launch_id: uuid.UUID, position: int, db: Db, user: CurrentUser
) -> FileResponse:
    """The creative this owner uploaded, and nobody else's."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    name = variant_upload(db, launch=launch, position=position)
    path = storage.media_path(name) if name else None
    if path is None or not path.is_file():
        raise NotFound("Fayl topilmadi.")
    return FileResponse(
        path, filename=path.name, headers={"Cache-Control": "private, max-age=300"}
    )


@router.get("/{launch_id}/media/{asset_id}/preview")
def media_preview(
    launch_id: uuid.UUID, asset_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """One picture, whole: its words, its date, and what is wrong with it."""
    launch = owned_launch(db, user=user, launch_id=launch_id)
    row = library_asset(
        db,
        owner=user,
        provider=launch.provider,
        ad_account=launch.ad_account,
        page=launch_page(db, launch=launch),
        asset_id=asset_id,
    )
    if row is None:
        raise NotFound("Fayl topilmadi.")
    now = utcnow()
    chosen = launch_variants(db, launch=launch)
    usage = media_usage(db, owner=user, assets=[row])
    refused = failed_deletes(db, owner=user, now=now)
    return encoded(
        {
            "tile": library_tile(
                row,
                used_in=usage.get(row.id, 0),
                deleting=row.external_id in deleting_files(db, owner=user, now=now),
                delete_failed=row.external_id in refused,
                delete_refusal=refused.get(row.external_id),
            ),
            "permalink_url": row.permalink_url,
            "width": row.width,
            "height": row.height,
            "is_eligible": row.is_eligible,
            "ineligible_reason": row.ineligible_reason,
            "created_at_provider": row.created_at_provider,
            "is_chosen": any(variant.media_asset_id == row.id for variant in chosen),
            "is_full": len(chosen) >= max_creatives(),
        }
    )


@router.post("/{launch_id}/media/{asset_id}/delete")
def media_delete(
    launch_id: uuid.UUID, asset_id: uuid.UUID, db: Db, user: CurrentUser
) -> dict[str, str]:
    """Take one file off the ad account's library."""
    writable_launch(db, user=user, launch_id=launch_id)
    committed(
        db, lambda: library.request_library_delete(db, owner=user, asset_id=asset_id)
    )
    return {"detail": ASKED}


@router.post("/{launch_id}/media/refresh")
def media_refresh(launch_id: uuid.UUID, db: Db, user: CurrentUser) -> dict[str, str]:
    """Ask the provider for this account's library again, now."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    committed(db, lambda: media.request_media_refresh(db, ad_account=launch.ad_account))
    return {"detail": ASKED}


@router.post("/{launch_id}/media/{position}/remove")
def media_remove(
    launch_id: uuid.UUID, position: int, db: Db, user: CurrentUser
) -> dict[str, Any]:
    """Drop one advert - the picture and the words that went with it."""
    launch = writable_launch(db, user=user, launch_id=launch_id)
    committed(db, lambda: variants.remove_variant(db, launch=launch, position=position))
    return launch_head(launch)
