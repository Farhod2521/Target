"""A month of selling, per manager: what was taken, talked to, sold and earned."""

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.common.dates import localtime, office_zone
from app.modules.accounts.models import User
from app.modules.sales.constants import OUTCOME_LABELS, SOURCE_LABELS, Outcome
from app.modules.sales.models import (
    LostReason,
    SalesClaim,
    SalesCommission,
    SalesMonth,
    SaleSource,
)


@dataclass(frozen=True, slots=True)
class Span:
    month: date
    start: datetime
    end: datetime


def span_of(month: date) -> Span:
    first = month.replace(day=1)
    following = date(first.year + first.month // 12, first.month % 12 + 1, 1)
    zone = office_zone()
    return Span(
        month=first,
        start=datetime(first.year, first.month, 1, tzinfo=zone),
        end=datetime(following.year, following.month, 1, tzinfo=zone),
    )


def current_span(*, now: datetime) -> Span:
    return span_of(localtime(now).date())


@dataclass(slots=True)
class ManagerMonth:
    manager_id: uuid.UUID
    name: str
    claimed: int = 0
    contacted: int = 0
    sold: int = 0
    base_minor: int = 0
    commission_minor: int = 0
    currency: str = ""
    open_now: int | None = None

    @property
    def conversion(self) -> int:
        return self.sold * 100 // self.claimed if self.claimed else 0


def _name(user: User | None) -> str:
    if user is None:
        return ""
    return user.full_name or user.email


def figure_month(db: Session, *, span: Span) -> list[ManagerMonth]:
    rows: dict[uuid.UUID, ManagerMonth] = {}

    def row(manager_id: uuid.UUID) -> ManagerMonth:
        if manager_id not in rows:
            rows[manager_id] = ManagerMonth(manager_id=manager_id, name="")
        return rows[manager_id]

    for column, target in (
        (SalesClaim.claimed_at, "claimed"),
        (SalesClaim.contacted_at, "contacted"),
    ):
        for manager_id, count in db.execute(
            select(SalesClaim.manager_id, func.count(SalesClaim.id))
            .where(
                column >= span.start,
                column < span.end,
                SalesClaim.manager_id.is_not(None),
            )
            .group_by(SalesClaim.manager_id)
        ):
            setattr(row(manager_id), target, count)
    for owner_id, currency, count, base, share in db.execute(
        select(
            SalesCommission.owner_id,
            SalesCommission.currency,
            func.count(SalesCommission.id),
            func.sum(SalesCommission.base_minor),
            func.sum(SalesCommission.amount_minor),
        )
        .where(
            SalesCommission.earned_at >= span.start,
            SalesCommission.earned_at < span.end,
        )
        .group_by(SalesCommission.owner_id, SalesCommission.currency)
    ):
        target = row(owner_id)
        target.sold += count
        target.base_minor += base or 0
        target.commission_minor += share or 0
        target.currency = currency
    if rows:
        people = {
            person.id: person
            for person in db.scalars(select(User).where(User.id.in_(list(rows))))
        }
        for manager_id, figures in rows.items():
            figures.name = _name(people.get(manager_id))
    return sorted(rows.values(), key=lambda item: (-item.sold, -item.claimed))


def live_month(db: Session, *, span: Span) -> list[ManagerMonth]:
    figures = figure_month(db, span=span)
    holding = dict(
        db.execute(
            select(SalesClaim.manager_id, func.count(SalesClaim.id))
            .where(SalesClaim.closed_at.is_(None))
            .group_by(SalesClaim.manager_id)
        ).all()
    )
    for item in figures:
        item.open_now = holding.get(item.manager_id, 0)
    return figures


def closed_month(db: Session, *, month: date) -> list[ManagerMonth]:
    rows = db.scalars(
        select(SalesMonth)
        .options(joinedload(SalesMonth.owner))
        .where(SalesMonth.month == month)
    )
    figures = [
        ManagerMonth(
            manager_id=item.owner_id,
            name=_name(item.owner),
            claimed=item.claimed,
            contacted=item.contacted,
            sold=item.sold,
            base_minor=item.base_minor,
            commission_minor=item.commission_minor,
            currency=item.currency,
        )
        for item in rows
    ]
    return sorted(figures, key=lambda item: (-item.sold, -item.claimed))


def closed_months(db: Session) -> list[date]:
    return list(
        db.scalars(
            select(SalesMonth.month).distinct().order_by(SalesMonth.month.desc())
        )
    )


def is_closed(db: Session, *, month: date) -> bool:
    return (
        db.scalar(select(SalesMonth.id).where(SalesMonth.month == month).limit(1))
        is not None
    )


def sales_of(
    db: Session, *, manager_id: uuid.UUID, span: Span
) -> list[SalesCommission]:
    from app.modules.billing.models import Invoice

    return list(
        db.scalars(
            select(SalesCommission)
            .options(
                joinedload(SalesCommission.client),
                joinedload(SalesCommission.invoice).joinedload(Invoice.plan),
            )
            .where(
                SalesCommission.owner_id == manager_id,
                SalesCommission.earned_at >= span.start,
                SalesCommission.earned_at < span.end,
            )
            .order_by(SalesCommission.earned_at.desc())
        )
    )


@dataclass(frozen=True, slots=True)
class Share:
    label: str
    count: int
    width: int


def _bars(pairs: list[tuple[str, int]]) -> list[Share]:
    top = max((count for _, count in pairs), default=0)
    return [
        Share(label=label, count=count, width=count * 100 // top if top else 0)
        for label, count in pairs
    ]


def reasons_in(db: Session, *, span: Span) -> list[Share]:
    count = func.count(SalesClaim.id)
    rows = db.execute(
        select(LostReason.label, count)
        .select_from(SalesClaim)
        .outerjoin(LostReason, LostReason.id == SalesClaim.reason_id)
        .where(
            SalesClaim.closed_at >= span.start,
            SalesClaim.closed_at < span.end,
            SalesClaim.outcome.in_([str(Outcome.LOST), str(Outcome.UNREACHABLE)]),
        )
        .group_by(LostReason.label)
        .order_by(count.desc())
    )
    return _bars(
        [(label or OUTCOME_LABELS[Outcome.UNREACHABLE], n) for label, n in rows]
    )


def sources_in(db: Session, *, span: Span) -> list[Share]:
    count = func.count(SaleSource.id)
    rows = db.execute(
        select(SaleSource.source, count)
        .where(SaleSource.paid_at >= span.start, SaleSource.paid_at < span.end)
        .group_by(SaleSource.source)
        .order_by(count.desc())
    )
    return _bars(
        [(str(SOURCE_LABELS.get(source, source)), n) for source, n in rows]  # type: ignore[call-overload]
    )
