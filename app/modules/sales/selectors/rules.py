"""The office's settings for selling: commission, what "ending" means, reasons."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.modules.sales.constants import DEFAULT_ENDING_DAYS
from app.modules.sales.models import LostReason, SalesRule, SalesSegment


@dataclass(frozen=True, slots=True)
class Rule:
    percent: int
    ending_days: int
    set: bool


def rule_at(db: Session, *, at: datetime) -> Rule:
    row = db.scalars(
        select(SalesRule)
        .where(SalesRule.valid_from <= at)
        .order_by(SalesRule.valid_from.desc())
        .limit(1)
    ).first()
    if row is None:
        return Rule(percent=0, ending_days=DEFAULT_ENDING_DAYS, set=False)
    return Rule(percent=row.percent, ending_days=row.ending_days, set=True)


def rule_history(db: Session, *, limit: int = 12) -> list[SalesRule]:
    return list(
        db.scalars(
            select(SalesRule)
            .options(joinedload(SalesRule.set_by))
            .order_by(SalesRule.valid_from.desc())
            .limit(limit)
        )
    )


def live_reasons(db: Session) -> list[LostReason]:
    return list(
        db.scalars(
            select(LostReason)
            .where(LostReason.archived_at.is_(None))
            .order_by(LostReason.position, LostReason.label)
        )
    )


def all_reasons(db: Session) -> list[LostReason]:
    return list(
        db.scalars(
            select(LostReason).order_by(
                LostReason.archived_at.asc().nulls_first(),
                LostReason.position,
                LostReason.label,
            )
        )
    )


def reason_by_id(db: Session, *, reason_id: uuid.UUID) -> LostReason | None:
    return db.get(LostReason, reason_id)


def segments(db: Session) -> list[SalesSegment]:
    from app.modules.billing.models import Plan

    return list(
        db.scalars(
            select(SalesSegment)
            .join(Plan, Plan.id == SalesSegment.plan_id)
            .options(joinedload(SalesSegment.plan))
            .order_by(Plan.price, SalesSegment.days)
        )
    )


def segment_by_id(db: Session, *, segment_id: uuid.UUID) -> SalesSegment | None:
    return db.scalars(
        select(SalesSegment)
        .options(joinedload(SalesSegment.plan))
        .where(SalesSegment.id == segment_id)
    ).first()
