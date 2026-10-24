"""Requests from the site's consult form, as cards for somebody to call."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.public.models import ConsultRequest
from app.modules.sales.constants import Group
from app.modules.sales.models import ContactHold, LostReason, SalesClaim
from app.modules.sales.selectors.search import request_match, subject_q

ARIZA_FIELDS = ("last_closed", "last_reason")


def _last_claim(column: Any) -> Any:
    earlier = aliased(ConsultRequest)
    return (
        select(column)
        .select_from(SalesClaim)
        .join(earlier, earlier.id == SalesClaim.consult_id)
        .outerjoin(LostReason, LostReason.id == SalesClaim.reason_id)
        .where(
            earlier.phone_e164 == ConsultRequest.phone_e164,
            SalesClaim.closed_at.is_not(None),
        )
        .order_by(SalesClaim.closed_at.desc())
        .limit(1)
        .correlate(ConsultRequest)
        .scalar_subquery()
    )


def _waiting(*, now: datetime) -> Any:
    later = aliased(ConsultRequest)
    registered = exists(
        select(User.id).where(
            User.phone == ConsultRequest.phone_e164,
            User.is_staff.is_(False),
            User.is_active.is_(True),
        )
    )
    claimed = exists(
        select(SalesClaim.id).where(
            SalesClaim.consult_id == ConsultRequest.id,
            SalesClaim.owner_id.is_(None),
            SalesClaim.closed_at.is_(None),
        )
    )
    held = exists(
        select(ContactHold.id).where(
            ContactHold.consult_id == ConsultRequest.id,
            ContactHold.owner_id.is_(None),
            ContactHold.lifted_at.is_(None),
            or_(ContactHold.until.is_(None), ContactHold.until > now),
        )
    )
    repeated = exists(
        select(later.id).where(
            later.phone_e164 == ConsultRequest.phone_e164,
            later.created_at > ConsultRequest.created_at,
        )
    )
    return and_(~registered, ~claimed, ~held, ~repeated)


def ariza_queue(*, now: datetime, term: str = "") -> Select[Any]:
    """Requests nobody has taken, held, registered over or asked again since."""
    query = select(
        ConsultRequest,
        _last_claim(SalesClaim.closed_at).label("last_closed"),
        _last_claim(LostReason.label).label("last_reason"),
    ).where(_waiting(now=now))
    if term:
        query = query.where(
            request_match(
                term, name=ConsultRequest.name, phone_e164=ConsultRequest.phone_e164
            )
        )
    return query.order_by(ConsultRequest.created_at.desc())


def load_arizas(db: Session, query: Select[Any]) -> list[ConsultRequest]:
    rows = []
    for row in db.execute(query):
        consult = row[0]
        consult.group = str(Group.ARIZA)
        consult.is_request = True
        consult.asked_at = consult.created_at
        for name in ARIZA_FIELDS:
            setattr(consult, name, row._mapping[name])
        rows.append(consult)
    return rows


def queued_ariza(
    db: Session, *, consult_id: uuid.UUID, now: datetime, term: str = ""
) -> ConsultRequest | None:
    found = load_arizas(
        db, ariza_queue(now=now, term=term).where(ConsultRequest.id == consult_id)
    )
    return found[0] if found else None


def consult_by_id(db: Session, *, consult_id: uuid.UUID) -> ConsultRequest | None:
    return db.get(ConsultRequest, consult_id)


def count_of(db: Session, query: Select[Any]) -> int:
    return (
        db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        or 0
    )


def waiting_ariza_count(db: Session, *, now: datetime) -> int:
    return count_of(db, ariza_queue(now=now))


__all__ = [
    "ariza_queue",
    "consult_by_id",
    "count_of",
    "load_arizas",
    "queued_ariza",
    "subject_q",
    "waiting_ariza_count",
]
