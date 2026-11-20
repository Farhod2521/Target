"""Which kinds of lead each Sales manager takes first, and what kind a
waiting lead is.

A lead's kind is read at the moment from the client's Start payment and
Start term (``SalesKind``): the discount still running, the discount over
while the term runs, the term over, or no Start at all. The Owner and the superuser tick, per manager, the kinds that manager
takes; a manager with nothing set takes every kind, and so do the Owner and
the superuser pressing «Lid olish». When none of a manager's kinds waits,
«Lid olish» gives any. Taking by phone ignores kinds altogether.
"""

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import ColumnElement, case, delete, func, select
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError, NotFound
from app.modules.accounts.models import User
from app.modules.billing.constants import DEFAULT_PLAN_CODE, InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice, Plan, Subscription
from app.modules.boards.constants import (
    OFFER_HOURS,
    OFFER_STEPS,
    SALES_KIND_LABELS,
    SALES_KIND_ORDER,
    Board,
    SalesColumn,
    SalesKind,
)
from app.modules.boards.models import BoardCard, SalesKindChoice


class NoKindChosen(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Kamida bitta lid turini belgilang.")


class UnknownKind(DomainError):
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Bunday lid turi yo'q.")


class NotSalesMember(NotFound):
    def __init__(self) -> None:
        super().__init__("Sotuv xodimi topilmadi.")


def start_paid_sql(owner: Any) -> Any:
    """When the client ``owner`` first paid Start, as a correlated subquery."""
    return (
        select(func.min(Invoice.paid_at))
        .join(Plan, Plan.id == Invoice.plan_id)
        .where(
            Invoice.owner_id == owner,
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.status == str(InvoiceStatus.PAID),
            Invoice.paid_at.is_not(None),
            Plan.code == DEFAULT_PLAN_CODE,
        )
        .scalar_subquery()
    )


def start_until_sql(owner: Any) -> Any:
    """When the client ``owner``'s Start term ends (the latest, if more than
    one), as a correlated subquery; None without a Start subscription."""
    return (
        select(func.max(Subscription.expires_at))
        .join(Plan, Plan.id == Subscription.plan_id)
        .where(Subscription.owner_id == owner, Plan.code == DEFAULT_PLAN_CODE)
        .scalar_subquery()
    )


def kind_sql(owner: Any, *, now: datetime) -> ColumnElement[str]:
    """The kind of the lead ``owner`` (a client's id column) at ``now``:
    no Start → new; Start paid under 96 hours ago → its discount runs; then,
    while the Start term runs → the discount ended; once it ran out (or
    with no Start subscription to read) → the term ended."""
    start_at = start_paid_sql(owner)
    until = start_until_sql(owner)
    return case(
        (start_at.is_(None), str(SalesKind.NEW)),
        (start_at > now - timedelta(hours=OFFER_HOURS), str(SalesKind.START_LIVE)),
        (until > now, str(SalesKind.START_ENDED)),
        else_=str(SalesKind.START_EXPIRED),
    )


def kind_order_sql(owner: Any, *, now: datetime) -> tuple[Any, ...]:
    """How «Lid olish» orders the kinds: Start with its discount running
    first, the 20% ones before the 10% ones and the soonest to end first
    within each; then Start whose discount ended while the term runs; then
    Start whose term ended; then new sign-ups. The caller orders by warmth
    after these."""
    kind = kind_sql(owner, now=now)
    start_at = start_paid_sql(owner)
    rank = case(
        *((kind == code, index) for index, code in enumerate(SALES_KIND_ORDER)),
        else_=len(SALES_KIND_ORDER),
    )
    live = kind == str(SalesKind.START_LIVE)
    first_step = timedelta(hours=OFFER_STEPS[0][1])
    step = case((start_at > now - first_step, 0), else_=1)
    return (
        rank,
        case((live, step), else_=0),
        case((live, start_at), else_=None).asc().nulls_last(),
    )


def kinds_for(
    db: Session, owner_ids: list[uuid.UUID], *, now: datetime
) -> dict[uuid.UUID, str]:
    """Each of these clients' kind of lead, in one query."""
    if not owner_ids:
        return {}
    return {
        owner: str(kind)
        for owner, kind in db.execute(
            select(User.id, kind_sql(User.id, now=now)).where(
                User.id.in_(set(owner_ids))
            )
        )
    }


def kind_of_client(db: Session, *, owner_id: uuid.UUID, now: datetime) -> str:
    return kinds_for(db, [owner_id], now=now).get(owner_id, str(SalesKind.NEW))


def kinds_of(db: Session, *, member_id: uuid.UUID) -> frozenset[str] | None:
    """The manager's kinds; None: every kind."""
    rows = db.scalars(
        select(SalesKindChoice.kind).where(SalesKindChoice.member_id == member_id)
    ).all()
    return frozenset(rows) if rows else None


def set_kinds(
    db: Session, *, member_id: uuid.UUID, kinds: list[str], actor: User
) -> frozenset[str] | None:
    """Save the manager's kinds. Every kind ticked is stored as nothing set,
    so a kind added later reaches them too. The caller commits."""
    from app.modules.boards.access import works_on

    member = db.get(User, member_id)
    if member is None or not member.is_active or not works_on(db, member, Board.SALES):
        raise NotSalesMember
    chosen = set(kinds)
    if not chosen:
        raise NoKindChosen
    if not chosen <= set(SALES_KIND_ORDER):
        raise UnknownKind
    db.execute(delete(SalesKindChoice).where(SalesKindChoice.member_id == member_id))
    if chosen != set(SALES_KIND_ORDER):
        db.add_all(
            SalesKindChoice(member_id=member_id, kind=kind, set_by_id=actor.id)
            for kind in SALES_KIND_ORDER
            if kind in chosen
        )
    db.flush()
    return kinds_of(db, member_id=member_id)


def label(kind: str) -> str:
    return str(SALES_KIND_LABELS[SalesKind(kind)]) if kind in SalesKind.values else kind


def _member(db: Session, person: User) -> dict[str, Any]:
    kinds = kinds_of(db, member_id=person.id)
    return {
        "id": str(person.id),
        "name": person.full_name or person.email,
        "email": person.email,
        "kinds": [kind for kind in SALES_KIND_ORDER if kinds is None or kind in kinds],
        "all": kinds is None,
    }


def kinds_view(db: Session) -> dict[str, Any]:
    """The settings: every kind with its name, and each Sales manager with
    the kinds they take."""
    from app.modules.boards.view import board_staff

    people = [
        db.get(User, uuid.UUID(p["id"])) for p in board_staff(db, board=Board.SALES)
    ]
    return {
        "kinds": [{"value": kind, "label": label(kind)} for kind in SALES_KIND_ORDER],
        "members": [_member(db, person) for person in people if person is not None],
    }


def member_view(db: Session, *, member_id: uuid.UUID) -> dict[str, Any]:
    person = db.get(User, member_id)
    if person is None:
        raise NotSalesMember
    return _member(db, person)


def waiting() -> tuple[ColumnElement[bool], ...]:
    """Ishlanmagan with nobody on it: what «Lid olish» may give."""
    return (
        BoardCard.board == str(Board.SALES),
        BoardCard.closed_at.is_(None),
        BoardCard.manager_id.is_(None),
        BoardCard.column_code == str(SalesColumn.UNWORKED),
    )


def waiting_counts(db: Session, *, now: datetime) -> dict[str, int]:
    """How many leads of each kind wait in Ishlanmagan."""
    rows = (
        select(kind_sql(BoardCard.owner_id, now=now).label("kind"))
        .where(*waiting())
        .subquery()
    )
    counts = {code: 0 for code in SALES_KIND_ORDER}
    for code, total in db.execute(
        select(rows.c.kind, func.count()).group_by(rows.c.kind)
    ):
        counts[str(code)] = int(total)
    return counts
