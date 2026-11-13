"""The discount on a client's first full plan: 20% for a day, then 10% for
three more days, then none. It starts on its own, at one of two moments:

* the client pays Start: the clock is that payment;
* the sales manager presses «Gaplashildi» on a lead who has not paid Start:
  the clock is the press (the ``offered`` line of the card).

A Start payment starts its own clock, whatever the manager's press gave
before. Start itself and one-time plans are never discounted, and the
discount ends for good once a full plan is paid.

The percent is taken off what is left of the plan's price after the unused
days of the running plan (Start's) are credited; a typed code and the wallet
come after it.

The clock is the payment or the press, never the card's column, so a bill
priced a minute before the sweep moves the card is still right."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, exists, func, select
from sqlalchemy.orm import Session

from app.common.choices import Choices
from app.common.money import decimal_places
from app.modules.billing.constants import (
    DEFAULT_PLAN_CODE,
    InvoiceKind,
    InvoiceStatus,
)
from app.modules.billing.models import Invoice, Plan
from app.modules.boards.constants import (
    OFFER_INVOICE_GRACE_MINUTES,
    OFFER_STEPS,
    Board,
    EventKind,
)
from app.modules.boards.models import BoardCard, BoardCardEvent

OFFERED_REF = "offered"


class OfferSource(Choices):
    # The client paid Start.
    START = "start"
    # The manager talked to a lead who has not.
    CONTACT = "contact"


@dataclass(frozen=True, slots=True)
class Offer:
    percent: int
    # When this percent ends; the next step (or none) starts then.
    ends_at: datetime
    started_at: datetime
    source: str = str(OfferSource.CONTACT)
    # The step after this one: its percent and when it ends. 0 and None
    # when this is the last.
    next_percent: int = 0
    next_ends_at: datetime | None = None

    @property
    def pay_until(self) -> datetime:
        """A bill priced at this percent may be paid until then."""
        return self.ends_at + timedelta(minutes=OFFER_INVOICE_GRACE_MINUTES)


def step_at(
    started_at: datetime, now: datetime, *, source: str = str(OfferSource.CONTACT)
) -> Offer | None:
    """The step that is on at ``now`` for a discount started at ``started_at``."""
    for index, (percent, hours, _column) in enumerate(OFFER_STEPS):
        ends_at = started_at + timedelta(hours=hours)
        if now >= ends_at:
            continue
        after = OFFER_STEPS[index + 1] if index + 1 < len(OFFER_STEPS) else None
        return Offer(
            percent=percent,
            ends_at=ends_at,
            started_at=started_at,
            source=source,
            next_percent=after[0] if after else 0,
            next_ends_at=started_at + timedelta(hours=after[1]) if after else None,
        )
    return None


def column_at(started_at: datetime, now: datetime) -> str | None:
    """The discount column a card stands in at ``now``; none once it is over."""
    step = step_at(started_at, now)
    if step is None:
        return None
    return next(str(c) for percent, _h, c in OFFER_STEPS if percent == step.percent)


def start_paid_at() -> Select[Any]:
    """Each client's first Start payment."""
    return (
        select(Invoice.owner_id, func.min(Invoice.paid_at).label("at"))
        .join(Plan, Plan.id == Invoice.plan_id)
        .where(
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.status == str(InvoiceStatus.PAID),
            Invoice.paid_at.is_not(None),
            Plan.code == DEFAULT_PLAN_CODE,
        )
        .group_by(Invoice.owner_id)
    )


def offered_at(db: Session, *, card_id: uuid.UUID) -> datetime | None:
    return db.scalar(
        select(BoardCardEvent.created_at).where(
            BoardCardEvent.card_id == card_id,
            BoardCardEvent.ref == OFFERED_REF,
        )
    )


def bought_full_plan(db: Session, *, owner_id: uuid.UUID) -> bool:
    """A plan the discount is for was paid already: there is no first one left."""
    return bool(
        db.scalar(
            select(
                exists().where(
                    Invoice.owner_id == owner_id,
                    Invoice.kind == str(InvoiceKind.PLAN),
                    Invoice.status.in_(
                        [str(InvoiceStatus.PAID), str(InvoiceStatus.REFUNDED)]
                    ),
                    Invoice.plan_id.in_(
                        select(Plan.id).where(
                            Plan.code != DEFAULT_PLAN_CODE,
                            Plan.is_one_time.is_(False),
                        )
                    ),
                )
            )
        )
    )


def clock(db: Session, *, owner_id: uuid.UUID) -> tuple[datetime, str] | None:
    """When the client's discount started and from what. The Start payment
    wins; without one, the manager's talk on a card still open."""
    paid = start_paid_at().where(Invoice.owner_id == owner_id).subquery()
    started = db.scalar(select(paid.c.at))
    if started is not None:
        return started, str(OfferSource.START)
    talked = db.scalar(
        select(BoardCardEvent.created_at)
        .join(BoardCard, BoardCard.id == BoardCardEvent.card_id)
        .where(
            BoardCard.board == str(Board.SALES),
            BoardCard.owner_id == owner_id,
            BoardCard.closed_at.is_(None),
            BoardCardEvent.ref == OFFERED_REF,
            BoardCardEvent.kind == str(EventKind.OFFERED),
        )
    )
    if talked is not None:
        return talked, str(OfferSource.CONTACT)
    return None


def live_offer(db: Session, *, owner_id: uuid.UUID, now: datetime) -> Offer | None:
    """The client's discount now, if any."""
    started = clock(db, owner_id=owner_id)
    if started is None or bought_full_plan(db, owner_id=owner_id):
        return None
    return step_at(started[0], now, source=started[1])


def clocks_for(
    db: Session, cards: Iterable[BoardCard]
) -> dict[uuid.UUID, tuple[datetime, str]]:
    """The discount clock of each of these Sales cards, in two queries."""
    cards = list(cards)
    if not cards:
        return {}
    paid = start_paid_at().where(
        Invoice.owner_id.in_({card.owner_id for card in cards})
    )
    by_owner = {owner_id: at for owner_id, at in db.execute(paid)}
    talked = {
        card_id: at
        for card_id, at in db.execute(
            select(BoardCardEvent.card_id, BoardCardEvent.created_at).where(
                BoardCardEvent.card_id.in_([card.id for card in cards]),
                BoardCardEvent.ref == OFFERED_REF,
            )
        )
    }
    out: dict[uuid.UUID, tuple[datetime, str]] = {}
    for card in cards:
        if card.owner_id in by_owner:
            out[card.id] = (by_owner[card.owner_id], str(OfferSource.START))
        elif card.id in talked:
            out[card.id] = (talked[card.id], str(OfferSource.CONTACT))
    return out


def is_discounted(plan: Plan) -> bool:
    """Whether the discount applies to this plan: not Start, not a one-time one."""
    return plan.code != DEFAULT_PLAN_CODE and not plan.is_one_time


def offer_minor(
    *, offer: Offer | None, plan: Plan, base_minor: int, credit_minor: int = 0
) -> int:
    """What the discount takes off ``plan`` priced ``base_minor``:
    its percent of what is left once the running plan's unused days
    (``credit_minor``) are credited. In whole units of the currency."""
    left = base_minor - max(0, credit_minor)
    if offer is None or left <= 0 or not is_discounted(plan):
        return 0
    take = left * offer.percent // 100
    return int(take - take % (10 ** decimal_places(plan.currency)))
