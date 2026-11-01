"""Fikrlar in the office, as JSON: customers' feedback and the site's carousel.

Approving pays into a customer's balance, so only the Owner and a superuser
answer a piece; Support and Finance keep the carousel. A refusal is the
DomainError body.
"""

import uuid
from pathlib import PurePosixPath
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.api.deps import Db
from app.common import storage
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.modules.accounts.models import User
from app.modules.backoffice import services
from app.modules.backoffice.constants import ADMIN_ROLES, FEEDBACK_ROLES, ActionKind
from app.modules.backoffice.permissions import has_role, staff_required
from app.modules.backoffice.routers._out import person_out
from app.modules.backoffice.schemas import (
    FeedbackQueueOut,
    MessageOut,
    PublishableOut,
    TestimonialOut,
)
from app.modules.backoffice.selectors.feedback import (
    FeedbackPayout,
    TestimonialCard,
    all_testimonials,
    feedback_by_id,
    feedback_payouts,
    publishable_feedback,
    recent_feedback_decisions,
    waiting_feedback,
)
from app.modules.backoffice.selectors.payments import business_names
from app.modules.backoffice.services import seen
from app.modules.public.constants import TESTIMONIAL_TEXT_MAX, TestimonialKind
from app.modules.public.services import (
    add_testimonial,
    change_testimonial,
    delete_testimonial,
)
from app.modules.referrals.constants import FeedbackKind, FeedbackStatus
from app.modules.referrals.models import Feedback
from app.modules.supportchat.constants import MessageKind
from app.modules.supportchat.files import file_response
from app.modules.supportchat.routers import file_reader

router = APIRouter()
Admin = Annotated[User, Depends(staff_required(*ADMIN_ROLES))]
Answerer = Annotated[User, Depends(staff_required(*FEEDBACK_ROLES))]


def file_listener(db: Db, user: User = Depends(file_reader)) -> User:
    """``?token=`` too: a player sends no header. 404 without the role."""
    if not has_role(db, user, FEEDBACK_ROLES):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return user


Listener = Annotated[User, Depends(file_listener)]


class ReasonIn(BaseModel):
    reason: str = Field(
        min_length=1, max_length=500, description="Why - the customer reads it."
    )


class CardIn(BaseModel):
    is_active: bool
    sort_order: int = Field(ge=0, le=32767)


def _piece(db: Db, feedback_id: uuid.UUID) -> Feedback:
    piece = feedback_by_id(db, feedback_id=feedback_id)
    if piece is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return piece


def _customer(row: Feedback, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {**(person_out(row.owner) or {}), "business": names.get(row.owner_id, "")}


def _file_path(row: Feedback) -> str:
    return f"/api/v1/office/feedback/{row.id}/file" if row.file else ""


def _waiting_out(
    row: Feedback, names: dict[uuid.UUID, str], payout: FeedbackPayout
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "customer": _customer(row, names),
        "kind": row.kind,
        "text": row.text,
        "file_url": _file_path(row),
        "created_at": row.created_at,
        "plan_name": payout.plan_name,
        "reward_percent": payout.percent,
        "reward_minor": payout.amount_minor,
        "currency": payout.currency,
    }


def _decision_out(row: Feedback) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": (person_out(row.owner) or {}).get("name", ""),
        "approved": row.status == FeedbackStatus.APPROVED,
        "amount_minor": row.amount_minor,
        "currency": row.currency,
        "reason": row.reason,
        "by": person_out(row.decided_by),
        "at": row.decided_at or row.updated_at,
    }


def _card_out(card: TestimonialCard, names: dict[uuid.UUID, str]) -> dict[str, Any]:
    row = card.piece
    source = row.source
    return {
        "id": str(row.id),
        "kind": row.kind,
        "image": storage.url(row.image) if row.image else "",
        "video": storage.url(row.video) if row.video else "",
        "audio": storage.url(row.audio) if row.audio else "",
        "text": row.text,
        "from_customer": source is not None,
        "name": (person_out(source.owner) or {}).get("name", "") if source else "",
        "business": names.get(source.owner_id, "") if source else "",
        "size_bytes": card.size_bytes,
        "is_active": row.is_active,
        "sort_order": row.sort_order,
    }


@router.get("/feedback", responses={200: {"model": FeedbackQueueOut}})
def feedback_queue(db: Db, user: Answerer) -> dict[str, Any]:
    """The pieces waiting, oldest first, and the latest answers."""
    pieces = waiting_feedback(db)
    payouts = feedback_payouts(db, pieces=pieces, now=utcnow())
    names = business_names(db, (piece.owner_id for piece in pieces))
    return {
        "rows": [_waiting_out(piece, names, payouts[piece.id]) for piece in pieces],
        "recent": [_decision_out(row) for row in recent_feedback_decisions(db)],
    }


@router.get("/feedback/publishable", responses={200: {"model": PublishableOut}})
def publishable(db: Db, user: Answerer) -> dict[str, Any]:
    """Approved pieces with no card on the site yet, newest first."""
    pieces = publishable_feedback(db)
    names = business_names(db, (piece.owner_id for piece in pieces))
    return {
        "rows": [
            {
                "id": str(piece.id),
                "customer": _customer(piece, names),
                "kind": piece.kind,
                "text": piece.text,
                "file_url": _file_path(piece),
                "decided_at": piece.decided_at or piece.updated_at,
            }
            for piece in pieces
        ]
    }


@router.get("/feedback/{feedback_id}/file", response_class=Response)
def feedback_file(
    feedback_id: uuid.UUID,
    db: Db,
    user: Listener,
    range_header: Annotated[str, Header(alias="Range")] = "",
) -> Response:
    """The recording, for the player. The files are not public: each opening
    goes to the journal, as a support file's does."""
    piece = _piece(db, feedback_id)
    if not piece.file:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    seen(db, customer=piece.owner, actor=user, kind=ActionKind.FEEDBACK_FILE)
    db.commit()
    return file_response(
        name=piece.file,
        filename=PurePosixPath(piece.file).name,
        kind=(
            MessageKind.VIDEO if piece.kind == FeedbackKind.VIDEO else MessageKind.VOICE
        ),
        mime="",
        view=True,
        range_header=range_header,
    )


@router.post("/feedback/{feedback_id}/approve", responses={200: {"model": MessageOut}})
def approve(feedback_id: uuid.UUID, db: Db, actor: Answerer) -> dict[str, Any]:
    """Pay the reward into the customer's balance."""
    services.approve_piece(db, piece=_piece(db, feedback_id), actor=actor, now=utcnow())
    db.commit()
    return {"message": "Fikr tasdiqlandi."}


@router.post("/feedback/{feedback_id}/reject", responses={200: {"model": MessageOut}})
def reject(
    feedback_id: uuid.UUID, body: ReasonIn, db: Db, actor: Answerer
) -> dict[str, Any]:
    """Turn the piece down; the reason is what the customer reads."""
    services.refuse_piece(
        db,
        piece=_piece(db, feedback_id),
        reason=body.reason,
        actor=actor,
        now=utcnow(),
    )
    db.commit()
    return {"message": "Fikr rad etildi."}


@router.post("/feedback/{feedback_id}/publish", responses={200: {"model": MessageOut}})
def publish(feedback_id: uuid.UUID, db: Db, actor: Answerer) -> dict[str, Any]:
    """Put an approved piece on the site, at the head of the carousel."""
    services.publish_piece(db, piece=_piece(db, feedback_id), actor=actor)
    db.commit()
    return {"message": "Fikr saytga chiqdi."}


@router.get("/testimonials", responses={200: {"model": list[TestimonialOut]}})
def testimonials(db: Db, user: Admin) -> list[dict[str, Any]]:
    """Every card, in the carousel's order, hidden ones too."""
    cards = all_testimonials(db)
    names = business_names(
        db, (card.piece.source.owner_id for card in cards if card.piece.source)
    )
    return [_card_out(card, names) for card in cards]


def _upload(file: UploadFile | None) -> tuple[Any, str] | None:
    return (file.file, file.filename or "") if file is not None else None


@router.post("/testimonials", responses={200: {"model": MessageOut}})
def add_card(
    db: Db,
    actor: Admin,
    media: TestimonialKind = Form(...),
    text: str = Form("", max_length=TESTIMONIAL_TEXT_MAX),
    order: int = Form(0, ge=0, le=32767),
    visible: bool = Form(True),
    file: UploadFile | None = File(None),
    cover: UploadFile | None = File(None),
) -> dict[str, Any]:
    """A new card of one kind. A file sent for another kind is left out, and
    a video's cover is kept as the card's picture."""
    words = text.strip() if media == TestimonialKind.TEXT else ""
    if media == TestimonialKind.TEXT and not words:
        raise InputRefused({"text": "Matnni yozing."})
    if media != TestimonialKind.TEXT and file is None:
        raise InputRefused({"file": "Faylni yuklang."})
    is_video = media == TestimonialKind.VIDEO
    add_testimonial(
        db,
        image=_upload(
            file if media == TestimonialKind.IMAGE else cover if is_video else None
        ),
        video=_upload(file if is_video else None),
        audio=_upload(file if media == TestimonialKind.AUDIO else None),
        text=words,
        is_active=visible,
        sort_order=order,
        actor=actor,
    )
    db.commit()
    return {"message": "Fikr qo'shildi."}


@router.patch("/testimonials/{testimonial_id}", responses={200: {"model": MessageOut}})
def save_card(
    testimonial_id: uuid.UUID, body: CardIn, db: Db, actor: Admin
) -> dict[str, Any]:
    """One card's switch and place."""
    change_testimonial(
        db,
        testimonial_id=testimonial_id,
        is_active=body.is_active,
        sort_order=body.sort_order,
        actor=actor,
    )
    db.commit()
    return {"message": "Saqlandi."}


@router.delete("/testimonials/{testimonial_id}", responses={200: {"model": MessageOut}})
def delete_card(testimonial_id: uuid.UUID, db: Db, actor: Admin) -> dict[str, Any]:
    """Remove a card and its files for good."""
    delete_testimonial(db, testimonial_id=testimonial_id, actor=actor)
    db.commit()
    return {"message": "Fikr o'chirildi."}
