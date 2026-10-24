"""Where a seller stands this month among the others."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.sales.models import SalesMonth
from app.modules.sales.selectors.board import sellers
from app.modules.sales.selectors.report import ManagerMonth, Span, figure_month


@dataclass(frozen=True, slots=True)
class Ranked:
    place: int
    row: ManagerMonth


@dataclass(frozen=True, slots=True)
class Standing:
    table: list[Ranked]
    mine: Ranked
    to_next: int
    next_place: int = 0


def _score(row: ManagerMonth) -> tuple[int, int, int]:
    return (-row.sold, -row.base_minor, -row.contacted)


def _order(row: ManagerMonth) -> tuple[int, int, int, str]:
    return (*_score(row), row.name.lower())


def _ranked(rows: list[ManagerMonth]) -> list[Ranked]:
    table: list[Ranked] = []
    for index, row in enumerate(sorted(rows, key=_order), start=1):
        tied = table and _score(table[-1].row) == _score(row)
        table.append(Ranked(place=table[-1].place if tied else index, row=row))
    return table


def _blank(person: User) -> ManagerMonth:
    return ManagerMonth(manager_id=person.id, name=person.full_name or person.email)


def standing(db: Session, *, span: Span, reader: User) -> Standing:
    rows = {row.manager_id: row for row in figure_month(db, span=span)}
    for person in sellers(db):
        rows.setdefault(person.id, _blank(person))
    table = _ranked(list(rows.values()))
    mine = next(
        (item for item in table if item.row.manager_id == reader.id),
        Ranked(place=0, row=_blank(reader)),
    )
    above = next(
        (item for item in reversed(table) if 0 < item.place < mine.place), None
    )
    if above is None:
        return Standing(table=table, mine=mine, to_next=0)
    to_next = max(above.row.sold - mine.row.sold + 1, 1)
    return Standing(table=table, mine=mine, to_next=to_next, next_place=above.place)


def months_of(db: Session, *, manager: User, limit: int = 12) -> list[SalesMonth]:
    return list(
        db.scalars(
            select(SalesMonth)
            .where(SalesMonth.owner_id == manager.id)
            .order_by(SalesMonth.month.desc())
            .limit(limit)
        )
    )
