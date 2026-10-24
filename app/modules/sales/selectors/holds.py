"""Do-not-call holds, and the whole sales record of one customer."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload

from app.modules.sales.models import ContactHold, SalesActivity, SalesClaim, SaleSource
from app.modules.sales.selectors.search import subject_q

HOLDS_PAGE = 50
RECORD_CLAIMS = 50
RECORD_LINES = 200


def active_holds(*, now: datetime) -> Select[Any]:
    return (
        select(ContactHold)
        .options(
            joinedload(ContactHold.owner),
            joinedload(ContactHold.consult),
            joinedload(ContactHold.set_by),
            joinedload(ContactHold.reason),
        )
        .where(
            ContactHold.lifted_at.is_(None),
            or_(ContactHold.until.is_(None), ContactHold.until > now),
        )
        .order_by(ContactHold.until.asc().nulls_first(), ContactHold.created_at.desc())
    )


def hold_for(db: Session, *, client_id: uuid.UUID, now: datetime) -> ContactHold | None:
    return db.scalars(
        active_holds(now=now).where(subject_q(ContactHold, client_id)).limit(1)
    ).first()


def hold_by_id(db: Session, *, hold_id: uuid.UUID) -> ContactHold | None:
    return db.get(ContactHold, hold_id)


@dataclass(frozen=True, slots=True)
class SalesRecord:
    claim: SalesClaim | None
    closed: list[SalesClaim]
    lines: list[SalesActivity]
    hold: ContactHold | None

    @property
    def is_empty(self) -> bool:
        return not (self.claim or self.closed or self.lines or self.hold)


def sales_record(db: Session, *, client_id: uuid.UUID, now: datetime) -> SalesRecord:
    claims = (
        select(SalesClaim)
        .options(joinedload(SalesClaim.manager), joinedload(SalesClaim.reason))
        .where(SalesClaim.owner_id == client_id)
    )
    return SalesRecord(
        claim=db.scalars(claims.where(SalesClaim.closed_at.is_(None)).limit(1)).first(),
        closed=list(
            db.scalars(
                claims.where(SalesClaim.closed_at.is_not(None))
                .order_by(SalesClaim.closed_at.desc())
                .limit(RECORD_CLAIMS)
            )
        ),
        lines=list(
            db.scalars(
                select(SalesActivity)
                .options(
                    joinedload(SalesActivity.actor), joinedload(SalesActivity.reason)
                )
                .where(SalesActivity.owner_id == client_id)
                .order_by(SalesActivity.created_at.desc())
                .limit(RECORD_LINES)
            )
        ),
        hold=db.scalars(
            active_holds(now=now).where(ContactHold.owner_id == client_id).limit(1)
        ).first(),
    )


def source_of(db: Session, *, invoice_id: uuid.UUID) -> SaleSource | None:
    return db.scalars(
        select(SaleSource).where(SaleSource.invoice_id == invoice_id)
    ).first()


def referral_paid(db: Session, *, invoice_id: uuid.UUID) -> bool:
    from app.modules.referrals.models import ReferralReward

    return (
        db.scalar(
            select(ReferralReward.id)
            .where(ReferralReward.invoice_id == invoice_id)
            .limit(1)
        )
        is not None
    )
