"""What the office shows of a customer's CRM: figures only, never a lead."""

import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.crm.constants import StageKind
from app.modules.crm.models import (
    CrmActivity,
    CrmCard,
    CrmLostReason,
    CrmMember,
    CrmSetup,
    CrmStage,
)
from app.modules.crm.selectors import Scope, countable_leads
from app.modules.integrations.selectors import Pair

NOT_SET_UP = "none"


@dataclass(frozen=True, slots=True)
class CrmTotals:
    """All of the customer's CRM rows, every pair's and those on no pair now."""

    setups: int
    stages: int
    reasons: int
    cards: int
    history: int
    managers: int

    @property
    def any(self) -> bool:
        return any(asdict(self).values())

    def as_detail(self) -> dict[str, int]:
        return asdict(self)


def crm_totals(db: Session, *, owner: User) -> CrmTotals:
    def count(model: Any) -> int:
        return int(
            db.scalar(
                select(func.count())
                .select_from(model)
                .where(model.owner_id == owner.id)
            )
            or 0
        )

    return CrmTotals(
        setups=count(CrmSetup),
        stages=count(CrmStage),
        reasons=count(CrmLostReason),
        cards=count(CrmCard),
        history=count(CrmActivity),
        managers=int(
            db.scalar(
                select(func.count())
                .select_from(User)
                .where(User.crm_owner_id == owner.id)
            )
            or 0
        ),
    )


@dataclass(frozen=True, slots=True)
class PairLine:
    pair: Pair
    state: str
    cards: int
    managers: int


def pair_lines(
    db: Session, *, owner: User, pairs: Sequence[Pair]
) -> tuple[list[PairLine], int]:
    """Each pair's CRM in a line, and the cards on no pair the customer has now."""
    states = {
        (row.page_id, row.ad_account_id): row.state
        for row in db.scalars(select(CrmSetup).where(CrmSetup.owner_id == owner.id))
    }

    def tally(model: Any, *where: Any) -> dict[tuple[Any, Any], int]:
        rows = db.execute(
            select(model.page_id, model.ad_account_id, func.count())
            .where(model.owner_id == owner.id, *where)
            .group_by(model.page_id, model.ad_account_id)
        )
        return {(page, account): count for page, account, count in rows}

    cards = tally(CrmCard)
    managers = tally(CrmMember, CrmMember.is_active.is_(True))
    lines = []
    for pair in pairs:
        key = (pair.page.id, pair.account.id)
        lines.append(
            PairLine(
                pair=pair,
                state=states.get(key, NOT_SET_UP),
                cards=cards.pop(key, 0),
                managers=managers.get(key, 0),
            )
        )
    return lines, sum(cards.values())


@dataclass(frozen=True, slots=True)
class StageFigure:
    cards: int
    won_minor: int


@dataclass(frozen=True, slots=True)
class ManagerFigure:
    open: int
    won: int
    won_minor: int


@dataclass(frozen=True, slots=True)
class PairFigures:
    leads: int
    cards: int
    open: int
    won: int
    won_minor: int
    lost: int
    qualified: int
    late: int
    today: int
    unassigned: int
    returned: int
    last_activity_at: datetime | None
    stages: dict[uuid.UUID, StageFigure]
    managers: dict[uuid.UUID, ManagerFigure]


def pair_figures(
    db: Session, *, owner: User, pair: Pair, scope: Scope, now: datetime
) -> PairFigures:
    kinds = {
        stage.id: stage.kind
        for stage in db.scalars(select(CrmStage).where(scope.holds(CrmStage)))
    }
    stages: dict[uuid.UUID, StageFigure] = {}
    for row in db.execute(
        select(
            CrmCard.stage_id,
            func.count(),
            func.coalesce(func.sum(CrmCard.won_amount_minor), 0),
        )
        .where(scope.holds(CrmCard))
        .group_by(CrmCard.stage_id)
    ):
        stages[row[0]] = StageFigure(cards=row[1], won_minor=int(row[2] or 0))

    def in_kind(*wanted: str) -> int:
        return sum(
            figure.cards
            for stage_id, figure in stages.items()
            if kinds.get(stage_id) in wanted
        )

    start = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    still_open = CrmCard.closed_at.is_(None)
    flags = db.execute(
        select(
            func.count().filter(CrmCard.qualified_at.is_not(None)),
            func.count().filter(still_open, CrmCard.due_at < now),
            func.count().filter(
                still_open,
                CrmCard.due_at >= start,
                CrmCard.due_at < start + timedelta(days=1),
            ),
            func.count().filter(still_open, CrmCard.assignee_id.is_(None)),
            func.count().filter(CrmCard.returned > 0),
        ).where(scope.holds(CrmCard))
    ).one()
    won_ids = [key for key, kind in kinds.items() if kind == StageKind.WON]
    is_won = CrmCard.stage_id.in_(won_ids)
    managers = {
        row[0]: ManagerFigure(open=row[1], won=row[2], won_minor=int(row[3] or 0))
        for row in db.execute(
            select(
                CrmCard.assignee_id,
                func.count().filter(still_open),
                func.count().filter(is_won),
                func.coalesce(
                    func.sum(case((is_won, CrmCard.won_amount_minor), else_=0)), 0
                ),
            )
            .where(scope.holds(CrmCard), CrmCard.assignee_id.is_not(None))
            .group_by(CrmCard.assignee_id)
        )
    }
    leads = db.scalar(
        countable_leads(db, owner=owner, pair=pair)
        .with_only_columns(func.count(), maintain_column_froms=True)
        .order_by(None)
    )
    return PairFigures(
        leads=int(leads or 0),
        cards=sum(figure.cards for figure in stages.values()),
        open=in_kind(StageKind.NEW, StageKind.OPEN),
        won=in_kind(StageKind.WON),
        won_minor=sum(
            figure.won_minor
            for stage_id, figure in stages.items()
            if kinds.get(stage_id) == StageKind.WON
        ),
        lost=in_kind(StageKind.LOST),
        qualified=flags[0],
        late=flags[1],
        today=flags[2],
        unassigned=flags[3],
        returned=flags[4],
        last_activity_at=db.scalar(
            select(func.max(CrmActivity.created_at))
            .join(CrmCard, CrmCard.id == CrmActivity.card_id)
            .where(scope.holds(CrmCard))
        ),
        stages=stages,
        managers=managers,
    )
