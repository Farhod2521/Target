"""The board: a manager's open cards by stage, and this month's closed ones."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, joinedload

from app.common.dates import localtime
from app.modules.accounts.models import Group as RoleGroup
from app.modules.accounts.models import User, UserGroup
from app.modules.sales.constants import (
    COLUMN_CARDS,
    OUTCOME_LABELS,
    STAGE_LABELS,
    Outcome,
    Stage,
)
from app.modules.sales.models import SalesClaim
from app.modules.sales.selectors.arizas import count_of
from app.modules.sales.selectors.search import claim_match, subject_q

SOLD = "sold"
LOST = "lost"
POOL = "pool"
_ORDER = {
    Stage.TAKEN: (SalesClaim.expires_at,),
    Stage.NO_ANSWER: (SalesClaim.expires_at,),
    Stage.CALLBACK: (SalesClaim.callback_at, SalesClaim.expires_at),
    Stage.THINKING: (SalesClaim.callback_at, SalesClaim.expires_at),
    Stage.USING: (SalesClaim.expires_at,),
    Stage.AWAITING: (SalesClaim.expires_at,),
}
LOST_OUTCOMES = (Outcome.LOST, Outcome.UNREACHABLE)


@dataclass(frozen=True, slots=True)
class Scope:
    manager_id: uuid.UUID | None
    term: str = ""


@dataclass(slots=True)
class Column:
    key: str
    label: str
    total: int
    cards: list[SalesClaim] = field(default_factory=list)

    @property
    def hidden(self) -> int:
        return max(self.total - len(self.cards), 0)


def month_start(*, now: datetime) -> datetime:
    local = localtime(now)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _scoped(scope: Scope) -> Select[Any]:
    query = select(SalesClaim).options(
        joinedload(SalesClaim.owner),
        joinedload(SalesClaim.consult),
        joinedload(SalesClaim.manager),
        joinedload(SalesClaim.reason),
        joinedload(SalesClaim.invoice),
    )
    if scope.manager_id is not None:
        query = query.where(SalesClaim.manager_id == scope.manager_id)
    if scope.term:
        query = query.where(claim_match(scope.term))
    return query


def open_cards(*, scope: Scope, stage: str) -> Select[Any]:
    return (
        _scoped(scope)
        .where(SalesClaim.closed_at.is_(None), SalesClaim.stage == stage)
        .order_by(*_ORDER[Stage(stage)])
    )


def closed_cards(*, scope: Scope, column: str, now: datetime) -> Select[Any]:
    outcomes = (Outcome.SOLD,) if column == SOLD else LOST_OUTCOMES
    return (
        _scoped(scope)
        .where(
            SalesClaim.closed_at >= month_start(now=now),
            SalesClaim.outcome.in_([str(item) for item in outcomes]),
        )
        .order_by(SalesClaim.closed_at.desc())
    )


def _column(db: Session, key: str, label: str, query: Select[Any]) -> Column:
    return Column(
        key=key,
        label=label,
        total=count_of(db, query),
        cards=list(db.scalars(query.limit(COLUMN_CARDS)).unique()),
    )


def columns(db: Session, *, scope: Scope, now: datetime) -> list[Column]:
    result = [
        _column(
            db, str(stage), STAGE_LABELS[stage], open_cards(scope=scope, stage=stage)
        )
        for stage in Stage
    ]
    result.append(
        _column(
            db,
            SOLD,
            OUTCOME_LABELS[Outcome.SOLD],
            closed_cards(scope=scope, column=SOLD, now=now),
        )
    )
    result.append(
        _column(
            db,
            LOST,
            OUTCOME_LABELS[Outcome.LOST],
            closed_cards(scope=scope, column=LOST, now=now),
        )
    )
    attach_plans(db, [card for column in result for card in column.cards], now=now)
    return result


def column_of(claim: SalesClaim) -> str:
    if claim.closed_at is None:
        return str(claim.stage)
    if claim.outcome == Outcome.SOLD:
        return SOLD
    if claim.outcome in LOST_OUTCOMES:
        return LOST
    return ""


def attach_plans(db: Session, cards: list[SalesClaim], *, now: datetime) -> None:
    from app.modules.billing.constants import LIVE_SUBSCRIPTION_STATUSES
    from app.modules.billing.models import Subscription

    owners = {card.owner_id for card in cards if card.owner_id is not None}
    live: dict[Any, Subscription] = {}
    if owners:
        live = {
            row.owner_id: row
            for row in db.scalars(
                select(Subscription)
                .options(joinedload(Subscription.plan))
                .where(
                    Subscription.owner_id.in_(owners),
                    Subscription.status.in_(
                        [str(s) for s in LIVE_SUBSCRIPTION_STATUSES]
                    ),
                    Subscription.expires_at > now,
                )
            )
        }
    for card in cards:
        card.live = live.get(card.owner_id)  # type: ignore[attr-defined]


def attach_plan(db: Session, card: SalesClaim, *, now: datetime) -> SalesClaim:
    attach_plans(db, [card], now=now)
    return card


def board_cursor(db: Session, *, scope: Scope) -> str:
    rows = _scoped(scope).options().subquery()
    stamp = db.scalar(select(func.max(rows.c.updated_at)))
    opened = db.scalar(
        select(func.count()).select_from(rows).where(rows.c.closed_at.is_(None))
    )
    return f"{stamp.isoformat() if stamp else '-'}|{opened or 0}"


def open_count(db: Session, *, manager: User) -> int:
    return (
        db.scalar(
            select(func.count(SalesClaim.id)).where(
                SalesClaim.manager_id == manager.id, SalesClaim.closed_at.is_(None)
            )
        )
        or 0
    )


def _staff_in(names: list[str]) -> Select[Any]:
    holding = (
        select(UserGroup.user_id)
        .join(RoleGroup, RoleGroup.id == UserGroup.group_id)
        .where(RoleGroup.name.in_(names))
    )
    return select(User).where(User.is_staff.is_(True), User.id.in_(holding))


def managers(db: Session) -> list[User]:
    from app.modules.backoffice.constants import SALES_ROLES

    names = [str(role) for role in SALES_ROLES]
    return list(db.scalars(_staff_in(names).order_by(User.full_name, User.email)))


def sellers(db: Session) -> list[User]:
    from app.modules.backoffice.constants import Role

    return list(db.scalars(_staff_in([str(Role.SALES)])))


def column_totals(db: Session, *, scope: Scope, now: datetime) -> dict[str, int]:
    totals = {str(stage): 0 for stage in Stage}
    rows = _scoped(scope).subquery()
    for stage, count in db.execute(
        select(rows.c.stage, func.count())
        .where(rows.c.closed_at.is_(None))
        .group_by(rows.c.stage)
    ):
        totals[stage] = count
    totals[SOLD] = count_of(db, closed_cards(scope=scope, column=SOLD, now=now))
    totals[LOST] = count_of(db, closed_cards(scope=scope, column=LOST, now=now))
    return totals


def card_in_scope(
    db: Session, *, client_id: uuid.UUID, scope: Scope, now: datetime
) -> SalesClaim | None:
    rows = _scoped(scope).where(subject_q(SalesClaim, client_id))
    card = db.scalars(rows.where(SalesClaim.closed_at.is_(None)).limit(1)).first()
    if card is None:
        card = db.scalars(
            rows.where(
                SalesClaim.closed_at >= month_start(now=now),
                SalesClaim.outcome.in_(
                    [str(Outcome.SOLD), *[str(item) for item in LOST_OUTCOMES]]
                ),
            )
            .order_by(SalesClaim.closed_at.desc())
            .limit(1)
        ).first()
    if card is not None:
        attach_plan(db, card, now=now)
    return card
