"""The sales manager's offer: «Chegirma berish» gives the client 20% off
their first plan for a day, then 10% until the third day ends, then none.
Start (the trial plan) and one-time plans are never discounted.

The clock is the press itself (the ``offered`` line), not the column, so a
bill priced a minute before the sweep moves the card is still right."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.modules.billing.constants import (
    DEFAULT_PLAN_CODE,
    InvoiceKind,
    InvoiceStatus,
)
from app.modules.billing.models import Invoice, Plan
from app.modules.boards.constants import (
    OFFER_COLUMNS,
    OFFER_INVOICE_GRACE_MINUTES,
    OFFER_STEPS,
    Board,
    EventKind,
)
from app.modules.boards.models import BoardCard, BoardCardEvent

OFFERED_REF = "offered"


@dataclass(frozen=True, slots=True)
class Offer:
    percent: int
    # When this percent ends; the next step (or none) starts then.
    ends_at: datetime
    started_at: datetime

    @property
    def pay_until(self) -> datetime:
        """A bill priced at this percent may be paid until then."""
        return self.ends_at + timedelta(minutes=OFFER_INVOICE_GRACE_MINUTES)


def step_at(started_at: datetime, now: datetime) -> Offer | None:
    """The step that is on at ``now`` for an offer pressed at ``started_at``."""
    for percent, hours, _column in OFFER_STEPS:
        ends_at = started_at + timedelta(hours=hours)
        if now < ends_at:
            return Offer(percent=percent, ends_at=ends_at, started_at=started_at)
    return None


def offered_at(db: Session, *, card_id: uuid.UUID) -> datetime | None:
    return db.scalar(
        select(BoardCardEvent.created_at).where(
            BoardCardEvent.card_id == card_id,
            BoardCardEvent.ref == OFFERED_REF,
        )
    )


def live_offer(db: Session, *, owner_id: uuid.UUID, now: datetime) -> Offer | None:
    """The client's offer now, if any: their Sales card is open and in an
    offer column, and they have never paid for a plan. Only the first plan
    is discounted; a card moved out of the offer columns by hand loses it."""
    paid = exists().where(
        Invoice.owner_id == owner_id,
        Invoice.kind == str(InvoiceKind.PLAN),
        Invoice.status.in_([str(InvoiceStatus.PAID), str(InvoiceStatus.REFUNDED)]),
    )
    started = db.scalar(
        select(BoardCardEvent.created_at)
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .where(
            BoardCard.board == str(Board.SALES),
            BoardCard.owner_id == owner_id,
            BoardCard.closed_at.is_(None),
            BoardCard.column_code.in_(OFFER_COLUMNS),
            BoardCardEvent.ref == OFFERED_REF,
            BoardCardEvent.kind == str(EventKind.OFFERED),
            ~paid,
        )
    )
    if started is None:
        return None
    return step_at(started, now)


def is_discounted(plan: Plan) -> bool:
    """Whether the offer applies to this plan: not Start, not a one-time one."""
    return plan.code != DEFAULT_PLAN_CODE and not plan.is_one_time


def offer_minor(*, offer: Offer | None, plan: Plan, base_minor: int) -> int:
    """What the offer takes off ``plan`` priced ``base_minor``."""
    if offer is None or base_minor <= 0 or not is_discounted(plan):
        return 0
    return base_minor * offer.percent // 100
