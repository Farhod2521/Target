"""Customers' feedback as the office answers it, and the site's carousel.

A piece's reward is read off the plan running today, not the one it was sent
under: approving pays a share of what the customer is on when it is pressed.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session, joinedload

from app.common import storage
from app.common.money import to_minor
from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
from app.modules.billing.models import Plan, Subscription
from app.modules.public.models import Testimonial
from app.modules.referrals.constants import (
    FEEDBACK_PERCENT,
    FeedbackKind,
    FeedbackStatus,
)
from app.modules.referrals.models import Feedback

RECENT_DECISIONS = 20
PUBLISHABLE_SHOWN = 30
NO_PLAN = "Tarifsiz"


@dataclass(frozen=True, slots=True)
class FeedbackPayout:
    """What approving one piece would pay today. `amount_minor` is null on a
    plan that gives no reward: a trial, a one-time plan, or none at all."""

    plan_name: str
    percent: int
    amount_minor: int | None
    currency: str


@dataclass(frozen=True, slots=True)
class TestimonialCard:
    """One card and how much disk its files take; null when one is missing."""

    __test__ = False

    piece: Testimonial
    size_bytes: int | None


def waiting_feedback(db: Session) -> list[Feedback]:
    return list(
        db.scalars(
            select(Feedback)
            .options(joinedload(Feedback.owner))
            .where(Feedback.status == FeedbackStatus.PENDING)
            .order_by(Feedback.created_at, Feedback.id)
        )
    )


def feedback_by_id(db: Session, *, feedback_id: uuid.UUID) -> Feedback | None:
    return db.get(Feedback, feedback_id)


def recent_feedback_decisions(db: Session) -> list[Feedback]:
    return list(
        db.scalars(
            select(Feedback)
            .options(joinedload(Feedback.owner), joinedload(Feedback.decided_by))
            .where(Feedback.status != FeedbackStatus.PENDING)
            .order_by(Feedback.decided_at.desc(), Feedback.id)
            .limit(RECENT_DECISIONS)
        )
    )


def publishable_feedback(db: Session) -> list[Feedback]:
    """Approved pieces with no card on the site yet, newest first."""
    on_site = exists().where(Testimonial.source_id == Feedback.id)
    return list(
        db.scalars(
            select(Feedback)
            .options(joinedload(Feedback.owner))
            .where(Feedback.status == FeedbackStatus.APPROVED, ~on_site)
            .order_by(Feedback.decided_at.desc(), Feedback.id)
            .limit(PUBLISHABLE_SHOWN)
        )
    )


def _live_plans(
    db: Session, owners: set[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, Plan]:
    rows = db.execute(
        select(Subscription.owner_id, Plan)
        .join(Plan, Subscription.plan_id == Plan.id)
        .where(
            Subscription.owner_id.in_(owners),
            Subscription.status.in_(LIVE_SUBSCRIPTION_STATUSES),
            Subscription.expires_at > now,
        )
    )
    return {owner_id: plan for owner_id, plan in rows}


def feedback_payouts(
    db: Session, *, pieces: Iterable[Feedback], now: datetime
) -> dict[uuid.UUID, FeedbackPayout]:
    rows = list(pieces)
    plans = _live_plans(db, {piece.owner_id for piece in rows}, now=now)
    answer: dict[uuid.UUID, FeedbackPayout] = {}
    for piece in rows:
        percent = FEEDBACK_PERCENT[FeedbackKind(piece.kind)]
        plan = plans.get(piece.owner_id)
        rewarded = plan is not None and not plan.is_one_time and plan.price > 0
        amount = None
        if plan is not None and rewarded:
            price = int(to_minor(amount=plan.price, currency=plan.currency))
            amount = price * percent // 100
        answer[piece.id] = FeedbackPayout(
            plan_name=plan.name if plan is not None else NO_PLAN,
            percent=percent,
            amount_minor=amount,
            currency=plan.currency if plan is not None else "",
        )
    return answer


def _size(row: Testimonial) -> int | None:
    """The card's files together: a video counts its cover too."""
    total = 0
    for name in (row.image, row.video, row.audio):
        if not name:
            continue
        try:
            total += storage.size(name)
        except (OSError, ValueError):
            return None
    return total


def all_testimonials(db: Session) -> list[TestimonialCard]:
    """Every card, in the order the carousel draws them, hidden ones too."""
    rows = db.scalars(
        select(Testimonial)
        .options(joinedload(Testimonial.source).joinedload(Feedback.owner))
        .order_by(Testimonial.sort_order, Testimonial.created_at)
    )
    return [TestimonialCard(piece=row, size_bytes=_size(row)) for row in rows]
