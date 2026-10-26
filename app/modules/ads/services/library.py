"""The owner's file on its way to the ad account's library: received in pieces,
sent from a worker that can carry on an interrupted video, its first frame read,
and taken off the library again when nothing shows it."""

import fcntl
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from uuid import UUID

from adskit.dto import ActionResult
from adskit.errors import ProviderError, RateLimited, TemporaryFailure
from adskit.refs import ExternalRef, ProviderName
from metaads.assets import MetaAssets
from metaads.chunks import VideoSession
from metaads.dto import MediaDTO
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.common import storage
from app.common.db import on_commit, utcnow
from app.common.exceptions import DomainError
from app.modules.accounts.models import User
from app.modules.ads.constants import (
    ALLOWED_VIDEO_TYPES,
    MAX_VIDEO_MB,
    PARTIAL_UPLOAD_DIR,
    PARTIAL_UPLOAD_HOURS,
    STILL_POLL_SECONDS,
    UPLOAD_ABANDONED_MINUTES,
    UPLOAD_CHUNK_BYTES,
    UPLOAD_SWEEP_BATCH,
    UPLOAD_SWEEP_SAMPLE,
    LibraryUpload,
    MediaKind,
)
from app.modules.ads.exceptions import (
    ChunkOutOfPlace,
    ChunkRefused,
    MediaDeleteRunning,
    MediaInUse,
    MediaNotStored,
    MediaNotUploaded,
    StillNotReady,
    UnknownMedia,
    UploadIncomplete,
    UploadInterrupted,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative, MediaAsset
from app.modules.ads.selectors.library import deleting_files, library_file, media_usage
from app.modules.ads.selectors.schedule import max_creatives
from app.modules.ads.services.access import launch_account_and_token, token_for
from app.modules.ads.services.manage import close_log, fail_log, open_log
from app.modules.ads.services.variants import add_media, remove_variant
from app.modules.audit.constants import ActionStatus, ActionType, EventName
from app.modules.audit.models import ActionLog
from app.modules.integrations.models import AdAccount

logger = logging.getLogger(__name__)
AGGREGATE = "media_asset"
UPLOAD_STATE = "upload"
ABANDONED_REASON = "no worker finished this upload"
_SUFFIX = ".part"
_MB = 1024 * 1024


class Upload:
    """A file handed on as if it had arrived in one request."""

    def __init__(
        self, *, file: BinaryIO, filename: str, size: int, path: Path | None = None
    ):
        self.file = file
        self.filename: str | None = filename
        self.size = size
        self.path = path

    def close(self) -> None:
        self.file.close()


def _account_ref(account: AdAccount) -> ExternalRef:
    return ExternalRef(
        provider=ProviderName(account.provider), level="account", id=account.external_id
    )


def _kind_of(filename: str) -> str:
    if filename.rsplit(".", 1)[-1].lower() in ALLOWED_VIDEO_TYPES:
        return MediaKind.VIDEO.value
    return MediaKind.IMAGE.value


# -- the pieces ------------------------------------------------------------------------


def append_chunk(
    *, launch: CampaignLaunch, upload_id: str, total: int, offset: int, data: bytes
) -> int:
    """Add one piece to the end of the file. Returns how much is here now."""
    if total <= 0 or total > MAX_VIDEO_MB * _MB or len(data) > UPLOAD_CHUNK_BYTES:
        raise ChunkRefused
    if offset < 0 or offset + len(data) > total:
        raise ChunkRefused
    path = _partial(launch=launch, upload_id=upload_id, total=total)
    if not path.exists() and _open_files(path.parent) >= max_creatives():
        raise ChunkRefused
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        here = handle.seek(0, os.SEEK_END)
        if here != offset:
            raise ChunkOutOfPlace(offset=here)
        handle.write(data)
        return here + len(data)


def assembled_upload(
    *, launch: CampaignLaunch, upload_id: str, total: int, name: str
) -> Upload:
    """The whole file, once every piece is here. Refused while one is not."""
    path = _partial(launch=launch, upload_id=upload_id, total=total)
    if not path.is_file() or path.stat().st_size != total:
        raise UploadIncomplete
    clean = PurePosixPath(name.replace("\\", "/")).name.strip()[:200]
    if not clean:
        raise ChunkRefused
    return Upload(file=path.open("rb"), filename=clean, size=total, path=path)


def discard_upload(*, upload: Upload) -> None:
    upload.close()
    if upload.path is not None:
        upload.path.unlink(missing_ok=True)


def drop_stale_partials(*, now: datetime) -> int:
    """Delete every half-sent file nobody has added to in a day."""
    root = storage.media_path(PARTIAL_UPLOAD_DIR)
    if not root.is_dir():
        return 0
    cutoff = (now - timedelta(hours=PARTIAL_UPLOAD_HOURS)).timestamp()
    dropped = 0
    for path in root.glob(f"*/*{_SUFFIX}"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                dropped += 1
        except FileNotFoundError:
            continue
    for folder in root.iterdir():
        if folder.is_dir() and not any(folder.iterdir()):
            folder.rmdir()
    if dropped:
        logger.info("half-sent uploads dropped", extra={"count": dropped})
    return dropped


def _partial(*, launch: CampaignLaunch, upload_id: str, total: int) -> Path:
    try:
        ident = UUID(upload_id)
    except (TypeError, ValueError) as exc:
        raise ChunkRefused from exc
    return storage.media_path(
        f"{PARTIAL_UPLOAD_DIR}/{launch.id}/{ident}.{total}{_SUFFIX}"
    )


def _open_files(folder: Path) -> int:
    if not folder.is_dir():
        return 0
    return sum(1 for _ in folder.glob(f"*{_SUFFIX}"))


# -- the upload ------------------------------------------------------------------------


def request_library_upload(
    db: Session, *, launch: CampaignLaunch, upload: Any
) -> LaunchCreative:
    """Add one file to the launch, and queue it for the library. Commits."""
    from app.modules.ads.tasks import upload_to_library_task

    db.scalar(
        select(CampaignLaunch.id)
        .where(CampaignLaunch.id == launch.id)
        .with_for_update()
    )
    add_media(db, launch=launch, asset_ids=[], uploads=[upload])
    row = db.scalar(
        select(LaunchCreative)
        .where(LaunchCreative.launch_id == launch.id)
        .order_by(LaunchCreative.position.desc())
        .limit(1)
    )
    if row is None or not row.media_upload:
        raise MediaNotStored
    row.library_upload = str(LibraryUpload.PENDING)
    filename = PurePosixPath(row.media_upload).name
    log = open_log(
        db,
        owner=launch.owner,
        action=ActionType.MEDIA_UPLOAD,
        provider=launch.provider,
        level=_kind_of(filename),
        external_id=str(row.id),
        requested={
            "launch": str(launch.id),
            "variant": str(row.id),
            "file": filename,
            "bytes": int(getattr(upload, "size", 0) or storage.size(row.media_upload)),
        },
        previous={},
        dry_run=False,
    )
    creative_id, log_id = str(row.id), str(log.id)
    on_commit(db, lambda: upload_to_library_task.delay(creative_id, log_id))
    db.commit()
    return row


def upload_to_library(
    db: Session, *, creative_id: UUID | str, log_id: UUID | str
) -> str:
    """Send one waiting file to the library. Returns a word for the task log."""
    log = db.get(ActionLog, UUID(str(log_id)))
    if log is None or log.status != ActionStatus.PENDING:
        return "done"
    row = db.get(LaunchCreative, UUID(str(creative_id)))
    if row is None or not row.media_upload:
        fail_log(db, log=log, code="gone", message="the variant or its file is gone")
        return "gone"
    filename = PurePosixPath(row.media_upload).name
    try:
        account, token = launch_account_and_token(db, launch=row.launch)
        media = _send(
            db, row=row, log=log, account=account, token=token, filename=filename
        )
    except (RateLimited, TemporaryFailure) as exc:
        _still_going(db, row=row)
        raise UploadInterrupted(str(exc)) from exc
    except (DomainError, ProviderError, OSError) as exc:
        _refused(db, row=row, log=log, code=_code_of(exc), message=str(exc))
        return "failed"
    _land(db, row=row, log=log, account=account, media=media, filename=filename)
    return "uploaded"


def give_up_on_upload(
    db: Session, *, creative_id: UUID | str, log_id: UUID | str, reason: str
) -> str:
    """Stop trying, say so on the tile, and leave nothing half-sent at Meta."""
    log = db.get(ActionLog, UUID(str(log_id)))
    row = db.get(LaunchCreative, UUID(str(creative_id)))
    if log is None or row is None or log.status != ActionStatus.PENDING:
        return "done"
    session = _resume_of(log)
    if session is not None:
        _abandon(db, row=row, session=session)
    _refused(db, row=row, log=log, code="interrupted", message=reason)
    return "failed"


def _send(
    db: Session,
    *,
    row: LaunchCreative,
    log: ActionLog,
    account: AdAccount,
    token: str,
    filename: str,
) -> MediaDTO:
    ref = _account_ref(account)
    assets = MetaAssets()
    with storage.media_path(row.media_upload).open("rb") as handle:
        if _kind_of(filename) == MediaKind.VIDEO:
            video_id = assets.upload_video(
                account=ref,
                file=handle,
                file_size=storage.size(row.media_upload),
                filename=filename,
                token=token,
                resume=_resume_of(log),
                remember=lambda state: _remember(db, row=row, log=log, session=state),
                dry_run=False,
            )
            return MediaDTO(
                kind=MediaKind.VIDEO.value, external_id=video_id, name=filename
            )
        image_hash = assets.upload_image(
            account=ref,
            data=handle.read(),
            filename=filename,
            token=token,
            dry_run=False,
        )
    if not image_hash:
        raise MediaNotUploaded
    return assets.describe_image(account=ref, image_hash=image_hash, token=token)


def _resume_of(log: ActionLog) -> VideoSession | None:
    saved = (log.request_payload or {}).get(UPLOAD_STATE)
    if not isinstance(saved, dict) or not saved.get("session"):
        return None
    try:
        return VideoSession(
            session_id=str(saved["session"]),
            video_id=str(saved.get("video", "")),
            start_offset=int(saved.get("start", 0)),
            end_offset=int(saved.get("end", 0)),
        )
    except (TypeError, ValueError):
        return None


def _remember(
    db: Session, *, row: LaunchCreative, log: ActionLog, session: VideoSession
) -> None:
    now = utcnow()
    payload = {
        **(log.request_payload or {}),
        UPLOAD_STATE: {
            "session": session.session_id,
            "video": session.video_id,
            "start": session.start_offset,
            "end": session.end_offset,
        },
    }
    log.request_payload = payload
    db.execute(
        update(ActionLog)
        .where(ActionLog.id == log.id)
        .values(request_payload=payload, updated_at=now)
    )
    db.execute(
        update(LaunchCreative).where(LaunchCreative.id == row.id).values(updated_at=now)
    )
    db.commit()


def _still_going(db: Session, *, row: LaunchCreative) -> None:
    db.execute(
        update(LaunchCreative)
        .where(LaunchCreative.id == row.id)
        .values(updated_at=utcnow())
    )
    db.commit()


def _abandon(db: Session, *, row: LaunchCreative, session: VideoSession) -> None:
    try:
        account, token = launch_account_and_token(db, launch=row.launch)
        MetaAssets().abandon_video(
            account=_account_ref(account), session_id=session.session_id, token=token
        )
    except (DomainError, ProviderError, OSError):
        logger.info(
            "an unfinished video was left at Meta",
            extra={"variant": str(row.id), "session": session.session_id},
        )


def _land(
    db: Session,
    *,
    row: LaunchCreative,
    log: ActionLog,
    account: AdAccount,
    media: MediaDTO,
    filename: str,
) -> None:
    """Mirror the new library row, point the variant at it, close the books."""
    from app.modules.ads.tasks import fetch_video_still_task
    from app.modules.audit.services import emit

    now = utcnow()
    asset = db.scalar(
        select(MediaAsset).where(
            MediaAsset.owner_id == row.owner_id,
            MediaAsset.provider == row.launch.provider,
            MediaAsset.kind == media.kind,
            MediaAsset.external_id == media.external_id,
        )
    )
    if asset is None:
        asset = MediaAsset(
            owner_id=row.owner_id,
            provider=row.launch.provider,
            kind=media.kind,
            external_id=media.external_id,
        )
        db.add(asset)
    asset.ad_account_id = account.id
    asset.page_id = None
    asset.name = media.name or filename
    asset.thumbnail_url = media.thumbnail_url
    asset.permalink_url = media.permalink_url
    asset.width = media.width
    asset.height = media.height
    asset.created_at_provider = media.created_time or now
    asset.synced_at = now
    db.flush()
    name = row.media_upload
    row.media_upload = ""
    row.media_asset_id = asset.id
    row.library_upload = ""
    on_commit(db, lambda: storage.delete(name))
    log.target_external_id = media.external_id
    close_log(
        db,
        log=log,
        result=ActionResult(
            ok=True,
            ref=_account_ref(account),
            applied={"kind": media.kind, "external_id": media.external_id},
            dry_run=False,
        ),
        previous={},
    )
    emit(
        db,
        owner_id=row.owner_id,
        name=EventName.MEDIA_UPLOADED,
        aggregate_type=AGGREGATE,
        aggregate_id=asset.id,
        payload={
            "kind": media.kind,
            "external_id": media.external_id,
            "ad_account": account.external_id,
            "launch": str(row.launch_id),
        },
    )
    if media.kind == MediaKind.VIDEO:
        args = [str(asset.id), str(row.launch_id)]
        on_commit(
            db,
            lambda: fetch_video_still_task.apply_async(
                args=args, countdown=STILL_POLL_SECONDS
            ),
        )
    db.commit()


def _refused(
    db: Session, *, row: LaunchCreative, log: ActionLog, code: str, message: str
) -> None:
    db.execute(
        update(LaunchCreative)
        .where(LaunchCreative.id == row.id)
        .values(library_upload=str(LibraryUpload.FAILED), updated_at=utcnow())
    )
    fail_log(db, log=log, code=code, message=message)
    logger.info("library upload refused", extra={"variant": str(row.id), "code": code})


def _code_of(exc: Exception) -> str:
    return str(getattr(exc, "code", "") or type(exc).__name__)


def sweep_abandoned_uploads(db: Session, *, now: datetime) -> int:
    """Give up on every upload nothing has touched in half an hour."""
    rows = list(
        db.scalars(
            select(LaunchCreative)
            .where(
                LaunchCreative.library_upload == str(LibraryUpload.PENDING),
                LaunchCreative.updated_at
                < now - timedelta(minutes=UPLOAD_ABANDONED_MINUTES),
            )
            .order_by(LaunchCreative.updated_at)
            .limit(UPLOAD_SWEEP_BATCH)
        )
    )
    if not rows:
        return 0
    closed = sum(_close(db, row=row, now=now) for row in rows)
    if not closed:
        return 0
    logger.error(
        "library uploads were abandoned by whatever was sending them",
        extra={
            "uploads": closed,
            "minutes": UPLOAD_ABANDONED_MINUTES,
            "variants": [str(row.id) for row in rows[:UPLOAD_SWEEP_SAMPLE]],
        },
    )
    return closed


def _close(db: Session, *, row: LaunchCreative, now: datetime) -> int:
    log = db.scalar(
        select(ActionLog)
        .where(
            ActionLog.action == str(ActionType.MEDIA_UPLOAD),
            ActionLog.target_external_id == str(row.id),
            ActionLog.status == str(ActionStatus.PENDING),
        )
        .order_by(ActionLog.created_at.desc())
        .limit(1)
    )
    if log is None:
        done = db.execute(
            update(LaunchCreative)
            .where(
                LaunchCreative.id == row.id,
                LaunchCreative.library_upload == str(LibraryUpload.PENDING),
            )
            .values(library_upload=str(LibraryUpload.FAILED), updated_at=now)
        ).rowcount
        db.commit()
        return int(done or 0)
    ended = give_up_on_upload(
        db, creative_id=row.id, log_id=log.id, reason=ABANDONED_REASON
    )
    return int(ended == "failed")


# -- the first frame of a video --------------------------------------------------------


def fetch_video_still(
    db: Session, *, asset_id: UUID | str, launch_id: UUID | str
) -> str:
    """Write the video's still, or ask to be tried again. Returns a word."""
    asset = db.get(MediaAsset, UUID(str(asset_id)))
    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if asset is None or asset.kind != MediaKind.VIDEO or launch is None:
        return "gone"
    if asset.thumbnail_url:
        return "done"
    try:
        _account, token = launch_account_and_token(db, launch=launch)
        still = MetaAssets().video_thumbnail(video_id=asset.external_id, token=token)
    except (RateLimited, TemporaryFailure) as exc:
        raise StillNotReady(str(exc)) from exc
    except (DomainError, ProviderError) as exc:
        logger.info(
            "a video still could not be read",
            extra={"asset": str(asset.id), "error": type(exc).__name__},
        )
        return "failed"
    if not still:
        raise StillNotReady
    asset.thumbnail_url = still
    asset.synced_at = utcnow()
    db.commit()
    return "found"


def read_library_for_still(db: Session, *, asset_id: UUID | str) -> str:
    from app.modules.ads.tasks import sync_media_task

    account_id = db.scalar(
        select(MediaAsset.ad_account_id).where(MediaAsset.id == UUID(str(asset_id)))
    )
    if account_id is None:
        return "gone"
    sync_media_task.delay(str(account_id))
    return "late"


# -- taking a file off the library ---------------------------------------------------


def request_library_delete(
    db: Session, *, owner: User, asset_id: UUID | str
) -> ActionLog:
    """Check that the file may go, and queue it. Commits."""
    from app.modules.ads.tasks import delete_library_media_task

    asset = library_file(db, owner=owner, asset_id=asset_id)
    if asset is None:
        raise UnknownMedia
    if asset.external_id in deleting_files(db, owner=owner, now=utcnow()):
        raise MediaDeleteRunning
    used = media_usage(db, owner=owner, assets=[asset]).get(asset.id, 0)
    if used:
        raise MediaInUse(count=used)
    log = open_log(
        db,
        owner=owner,
        action=ActionType.MEDIA_DELETE,
        provider=asset.provider,
        level=asset.kind,
        external_id=asset.external_id,
        requested={"asset": str(asset.id)},
        previous=_snapshot(asset),
        dry_run=False,
    )
    log_id = str(log.id)
    on_commit(db, lambda: delete_library_media_task.delay(log_id))
    db.commit()
    return log


def delete_library_media(db: Session, *, log_id: UUID | str) -> str:
    """Take one queued file off the library. Returns a word for the task log."""
    log = db.get(ActionLog, UUID(str(log_id)))
    if log is None or log.status != ActionStatus.PENDING:
        return "done"
    owner = db.get(User, log.owner_id)
    asset = (
        library_file(
            db, owner=owner, asset_id=str((log.request_payload or {}).get("asset"))
        )
        if owner is not None
        else None
    )
    if owner is None or asset is None or asset.ad_account is None:
        fail_log(
            db, log=log, code="gone", message="the file is no longer in the library"
        )
        return "gone"
    account = asset.ad_account
    try:
        token = token_for(ad_account=account)
        _refuse_if_shown(db, owner=owner, asset=asset, account=account, token=token)
        _delete(asset=asset, account=account, token=token)
    except MediaInUse as exc:
        fail_log(db, log=log, code="in_use", message=str(exc))
        return "in_use"
    except (DomainError, ProviderError) as exc:
        code = str(getattr(exc, "code", "") or type(exc).__name__)
        fail_log(db, log=log, code=code, message=str(exc))
        logger.warning(
            "library delete of %s on %s failed: %s: %s",
            asset.external_id,
            account.external_id,
            code,
            exc,
        )
        return "failed"
    _forget(db, owner=owner, asset=asset, account=account, log=log)
    return "deleted"


def _refuse_if_shown(
    db: Session, *, owner: User, asset: MediaAsset, account: AdAccount, token: str
) -> None:
    used = media_usage(db, owner=owner, assets=[asset]).get(asset.id, 0)
    if asset.kind == MediaKind.IMAGE:
        shown = MetaAssets().image_creatives(
            account=_account_ref(account), image_hash=asset.external_id, token=token
        )
        used = max(used, len(shown))
    if used:
        raise MediaInUse(count=used)


def _delete(*, asset: MediaAsset, account: AdAccount, token: str) -> None:
    assets = MetaAssets()
    if asset.kind == MediaKind.VIDEO:
        assets.delete_video(video_id=asset.external_id, token=token, dry_run=False)
        return
    assets.delete_image(
        account=_account_ref(account),
        image_hash=asset.external_id,
        token=token,
        dry_run=False,
    )


def _forget(
    db: Session, *, owner: User, asset: MediaAsset, account: AdAccount, log: ActionLog
) -> None:
    """The mirror row, and every unfinished launch that had chosen it."""
    from app.modules.audit.services import emit

    launch_ids = set(
        db.scalars(
            select(LaunchCreative.launch_id).where(
                LaunchCreative.owner_id == owner.id,
                LaunchCreative.media_asset_id == asset.id,
            )
        )
    )
    for launch in db.scalars(
        select(CampaignLaunch).where(
            CampaignLaunch.owner_id == owner.id, CampaignLaunch.id.in_(launch_ids)
        )
    ):
        while (
            row := db.scalar(
                select(LaunchCreative)
                .where(
                    LaunchCreative.launch_id == launch.id,
                    LaunchCreative.media_asset_id == asset.id,
                )
                .limit(1)
            )
        ) is not None:
            remove_variant(db, launch=launch, position=row.position)
    close_log(
        db,
        log=log,
        result=ActionResult(
            ok=True, ref=_account_ref(account), applied={"deleted": True}, dry_run=False
        ),
        previous=dict(log.previous_state or {}),
    )
    emit(
        db,
        owner_id=owner.id,
        name=EventName.MEDIA_DELETED,
        aggregate_type=AGGREGATE,
        aggregate_id=asset.id,
        payload={
            "kind": asset.kind,
            "external_id": asset.external_id,
            "ad_account": account.external_id,
        },
    )
    db.delete(asset)
    db.commit()


def _snapshot(asset: MediaAsset) -> dict[str, Any]:
    return {
        "kind": asset.kind,
        "external_id": asset.external_id,
        "name": asset.name,
        "thumbnail_url": asset.thumbnail_url,
        "width": asset.width,
        "height": asset.height,
    }
