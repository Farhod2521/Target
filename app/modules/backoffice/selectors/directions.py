"""The business directions a customer picks from, with what stands on each."""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.businesses.models import Business, BusinessCategory


@dataclass(frozen=True, slots=True)
class DirectionRow:
    direction: BusinessCategory
    businesses: int


def direction_rows(db: Session) -> list[DirectionRow]:
    """Every direction, the switched-off ones too, in the customer's order."""
    counts: dict[uuid.UUID | None, int] = {
        direction_id: count
        for direction_id, count in db.execute(
            select(Business.direction_id, func.count(Business.id))
            .where(Business.direction_id.is_not(None))
            .group_by(Business.direction_id)
        )
    }
    rows = db.scalars(
        select(BusinessCategory).order_by(
            BusinessCategory.position, BusinessCategory.key
        )
    )
    return [DirectionRow(row, counts.get(row.id, 0)) for row in rows]


def direction_by_id(db: Session, *, direction_id: uuid.UUID) -> BusinessCategory | None:
    return db.get(BusinessCategory, direction_id)


def businesses_on(db: Session, *, direction: BusinessCategory) -> int:
    return (
        db.scalar(
            select(func.count(Business.id)).where(Business.direction_id == direction.id)
        )
        or 0
    )
