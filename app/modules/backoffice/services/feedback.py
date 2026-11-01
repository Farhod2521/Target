"""The office's answers to customers' feedback, journalled.

The money decision is referrals', the card is public's; what this adds is
the journal line.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.backoffice.constants import ActionKind
from app.modules.backoffice.services.journal import record
from app.modules.public.models import Testimonial
from app.modules.public.services import publish_feedback
from app.modules.referrals.models import Feedback
from app.modules.referrals.services import approve_feedback, reject_feedback


def approve_piece(
    db: Session, *, piece: Feedback, actor: User, now: datetime
) -> Feedback:
    approved = approve_feedback(db, piece=piece, actor=actor, now=now)
    record(
        db,
        customer=approved.owner,
        actor=actor,
        kind=ActionKind.FEEDBACK_APPROVED,
        detail={
            "kind": approved.kind,
            "percent": approved.percent,
            "amount_minor": approved.amount_minor,
            "currency": approved.currency,
        },
    )
    return approved


def refuse_piece(
    db: Session, *, piece: Feedback, reason: str, actor: User, now: datetime
) -> Feedback:
    refused = reject_feedback(db, piece=piece, reason=reason, actor=actor, now=now)
    record(
        db,
        customer=refused.owner,
        actor=actor,
        kind=ActionKind.FEEDBACK_REJECTED,
        reason=reason,
        detail={"kind": refused.kind},
    )
    return refused


def publish_piece(db: Session, *, piece: Feedback, actor: User) -> Testimonial:
    card = publish_feedback(db, piece=piece, actor=actor)
    record(
        db,
        customer=piece.owner,
        actor=actor,
        kind=ActionKind.FEEDBACK_PUBLISHED,
        detail={"kind": piece.kind},
    )
    return card
