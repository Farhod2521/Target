import logging
import secrets
import uuid
from datetime import datetime
from pathlib import PurePosixPath
from typing import BinaryIO

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common import storage
from app.common.config import settings
from app.common.exceptions import ConfigurationError
from app.modules.accounts.models import User
from app.modules.public.constants import (
    CONFIRMATION_CODE_BYTES,
    TESTIMONIAL_AUDIO_EXTENSIONS,
    TESTIMONIAL_IMAGE_EXTENSIONS,
    TESTIMONIAL_UPLOAD_DIR,
    TESTIMONIAL_VIDEO_EXTENSIONS,
    DeletionRequestSource,
    DeletionRequestStatus,
)
from app.modules.public.exceptions import (
    ConsultRequestNotFound,
    FeedbackAlreadyOnSite,
    FeedbackNotPublishable,
    InvalidSignedRequest,
    TestimonialNotFound,
)
from app.modules.public.models import ConsultRequest, DeletionRequest, Testimonial

logger = logging.getLogger(__name__)
_CODE_ATTEMPTS = 3


def create_consult_request(
    db: Session, *, name: str, phone_e164: str, language: str
) -> ConsultRequest:
    existing = db.scalar(
        select(ConsultRequest)
        .where(
            ConsultRequest.phone_e164 == phone_e164,
            ConsultRequest.contacted_at.is_(None),
        )
        .order_by(ConsultRequest.created_at.desc())
        .with_for_update()
        .limit(1)
    )
    if existing is not None:
        existing.name = name
        db.flush()
        logger.info("consult_request.reused", extra={"consult_id": str(existing.id)})
        return existing
    row = ConsultRequest(name=name, phone_e164=phone_e164, language=language)
    db.add(row)
    db.flush()
    logger.info("consult_request.created", extra={"consult_id": str(row.id)})
    return row


def mark_consult_contacted(
    db: Session, *, consult_id: uuid.UUID, actor: User, now: datetime
) -> ConsultRequest:
    row = db.get(ConsultRequest, consult_id, with_for_update=True)
    if row is None:
        raise ConsultRequestNotFound
    if row.contacted_at is None:
        row.contacted_at = now
        row.contacted_by_id = actor.id
        db.flush()
        logger.info(
            "consult_request.contacted",
            extra={"consult_id": str(row.id), "actor_id": str(actor.id)},
        )
    return row


def new_code() -> str:
    return secrets.token_urlsafe(CONFIRMATION_CODE_BYTES)


def create_deletion_request(
    db: Session,
    *,
    source: DeletionRequestSource,
    email: str = "",
    meta_user_id: str = "",
    reason: str = "",
) -> DeletionRequest:
    email = email.strip().lower()
    meta_user_id = meta_user_id.strip()
    if not email and not meta_user_id:
        raise ValueError("a deletion request needs an email or a meta_user_id")
    existing = _find_open(db, email=email, meta_user_id=meta_user_id)
    if existing is not None:
        logger.info(
            "deletion_request.reused",
            extra={"confirmation_code": existing.confirmation_code},
        )
        return existing
    for attempt in range(_CODE_ATTEMPTS):
        request = DeletionRequest(
            confirmation_code=new_code(),
            source=str(source),
            status=str(DeletionRequestStatus.RECEIVED),
            email=email,
            meta_user_id=meta_user_id,
            reason=reason.strip(),
        )
        try:
            with db.begin_nested():
                db.add(request)
        except IntegrityError:
            if attempt == _CODE_ATTEMPTS - 1:
                raise
            continue
        logger.info(
            "deletion_request.created",
            extra={"confirmation_code": request.confirmation_code, "source": source},
        )
        return request
    raise AssertionError("confirmation code generation fell through")


def _find_open(db: Session, *, email: str, meta_user_id: str) -> DeletionRequest | None:
    query = select(DeletionRequest).where(
        DeletionRequest.status.in_(
            (DeletionRequestStatus.RECEIVED, DeletionRequestStatus.IN_PROGRESS)
        )
    )
    if meta_user_id:
        query = query.where(DeletionRequest.meta_user_id == meta_user_id)
    else:
        query = query.where(DeletionRequest.email == email)
    return db.scalar(
        query.order_by(DeletionRequest.created_at.desc()).with_for_update().limit(1)
    )


def process_meta_deletion_callback(
    db: Session, *, signed_request: str
) -> DeletionRequest:
    from metaads.signed_request import SignedRequestError, parse_signed_request

    app_secret = settings.meta_app_secret
    if not app_secret:
        raise ConfigurationError(
            "META_APP_SECRET is not set: deletion callbacks cannot be verified"
        )
    try:
        payload = parse_signed_request(signed_request, app_secret=app_secret)
    except SignedRequestError as exc:
        logger.warning("meta.deletion_callback.rejected", extra={"reason": str(exc)})
        raise InvalidSignedRequest from exc
    return create_deletion_request(
        db, source=DeletionRequestSource.META_CALLBACK, meta_user_id=payload.user_id
    )


def _suffix(name: str) -> str:
    return PurePosixPath(name).suffix.lower().lstrip(".")


def _store(upload: tuple[BinaryIO, str] | None, *, allowed: list[str]) -> str:
    if upload is None:
        return ""
    stream, filename = upload
    if _suffix(filename) not in allowed:
        raise FeedbackNotPublishable("Bu fayl formati qo'llanmaydi.")
    return storage.save(stream, folder=TESTIMONIAL_UPLOAD_DIR, filename=filename)


def add_testimonial(
    db: Session,
    *,
    image: tuple[BinaryIO, str] | None,
    video: tuple[BinaryIO, str] | None,
    audio: tuple[BinaryIO, str] | None,
    text: str,
    is_active: bool,
    sort_order: int,
    actor: User,
) -> Testimonial:
    row = Testimonial(
        is_active=is_active,
        sort_order=sort_order,
        text=text.strip(),
        image=_store(image, allowed=TESTIMONIAL_IMAGE_EXTENSIONS),
        video=_store(video, allowed=TESTIMONIAL_VIDEO_EXTENSIONS),
        audio=_store(audio, allowed=TESTIMONIAL_AUDIO_EXTENSIONS),
    )
    db.add(row)
    db.flush()
    _log("testimonial.added", row=row, actor=actor)
    return row


def change_testimonial(
    db: Session,
    *,
    testimonial_id: uuid.UUID,
    is_active: bool,
    sort_order: int,
    actor: User,
) -> Testimonial:
    row = _locked(db, testimonial_id)
    row.is_active = is_active
    row.sort_order = sort_order
    db.flush()
    _log("testimonial.changed", row=row, actor=actor)
    return row


def delete_testimonial(db: Session, *, testimonial_id: uuid.UUID, actor: User) -> None:
    from app.common.db import on_commit

    row = _locked(db, testimonial_id)
    files = [name for name in (row.image, row.video, row.audio) if name]
    _log("testimonial.deleted", row=row, actor=actor)
    db.delete(row)
    db.flush()
    for name in files:
        on_commit(db, lambda name=name: storage.delete(name))


def _locked(db: Session, testimonial_id: uuid.UUID) -> Testimonial:
    row = db.get(Testimonial, testimonial_id, with_for_update=True)
    if row is None:
        raise TestimonialNotFound
    return row


def _log(event: str, *, row: Testimonial, actor: User) -> None:
    logger.info(event, extra={"testimonial_id": str(row.id), "actor_id": str(actor.id)})


def publish_feedback(db: Session, *, piece: object, actor: User) -> Testimonial:
    from app.modules.referrals.constants import FeedbackKind, FeedbackStatus

    if piece.status != FeedbackStatus.APPROVED or piece.consented_at is None:  # type: ignore[attr-defined]
        raise FeedbackNotPublishable
    if db.scalar(select(Testimonial.id).where(Testimonial.source_id == piece.id)):  # type: ignore[attr-defined]
        raise FeedbackAlreadyOnSite
    row = Testimonial(source_id=piece.id, text=piece.text, is_active=True, sort_order=0)  # type: ignore[attr-defined]
    if piece.kind != FeedbackKind.TEXT:  # type: ignore[attr-defined]
        is_video = piece.kind == FeedbackKind.VIDEO  # type: ignore[attr-defined]
        name = PurePosixPath(piece.file or "").name  # type: ignore[attr-defined]
        allowed = (
            TESTIMONIAL_VIDEO_EXTENSIONS if is_video else TESTIMONIAL_AUDIO_EXTENSIONS
        )
        if _suffix(name) not in allowed:
            raise FeedbackNotPublishable(
                "Sayt bu formatni ko'rsatmaydi: video MP4 yoki WebM bo'lsin."
            )
        with storage.media_path(piece.file).open("rb") as handle:  # type: ignore[attr-defined]
            copied = storage.save(
                handle, folder=TESTIMONIAL_UPLOAD_DIR, filename=name, keep_name=True
            )
        if is_video:
            row.video = copied
        else:
            row.audio = copied
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError as exc:
        storage.delete(row.video or row.audio)
        raise FeedbackAlreadyOnSite from exc
    logger.info(
        "testimonial.published",
        extra={
            "testimonial_id": str(row.id),
            "feedback_id": str(piece.id),  # type: ignore[attr-defined]
            "actor_id": str(actor.id),
        },
    )
    return row


__all__ = [
    "add_testimonial",
    "change_testimonial",
    "create_consult_request",
    "create_deletion_request",
    "delete_testimonial",
    "mark_consult_contacted",
    "process_meta_deletion_callback",
    "publish_feedback",
]
