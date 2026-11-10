"""Reading a board's columns and the moment it went live."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.boards.access import Access
from app.modules.boards.constants import LEAD_ONLY_COLUMNS, SEED_COLUMNS, Board
from app.modules.boards.models import BoardColumn, BoardSetting


@dataclass(frozen=True, slots=True)
class ColumnView:
    code: str
    name: str
    position: int
    kind: str
    is_final: bool


def ensure_board(db: Session, *, board: Board, now: datetime) -> None:
    """The board's columns and its live moment, written once. The migration
    writes them at deploy; this covers a database built without it."""
    db.execute(
        insert(BoardSetting)
        .values(board=str(board), live_since=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=["board"])
    )
    have = set(
        db.scalars(select(BoardColumn.code).where(BoardColumn.board == str(board)))
    )
    last = int(
        db.scalar(
            select(func.coalesce(func.max(BoardColumn.position), 0)).where(
                BoardColumn.board == str(board)
            )
        )
        or 0
    )
    for seed in SEED_COLUMNS:
        if seed.board != board or seed.code in have:
            continue
        last += 1
        db.execute(
            insert(BoardColumn)
            .values(
                board=str(board),
                code=seed.code,
                name=seed.name,
                position=last,
                kind=str(seed.kind),
                is_final=seed.is_final,
                is_visible=seed.is_visible,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["board", "code"])
        )
    db.flush()


def live_since(db: Session, *, board: Board) -> datetime | None:
    return db.scalar(
        select(BoardSetting.live_since).where(BoardSetting.board == str(board))
    )


def columns_for(db: Session, *, board: Board, access: Access) -> list[ColumnView]:
    """The columns this person sees, in the board's order. Hidden columns
    (the trial and discount ones, until they are built) are left out, and
    Ishlanmagan and Yopildi are for the board's lead."""
    rows = db.scalars(
        select(BoardColumn)
        .where(BoardColumn.board == str(board), BoardColumn.is_visible.is_(True))
        .order_by(BoardColumn.position, BoardColumn.code)
    )
    lead = access.leads_board(board)
    return [
        ColumnView(
            code=row.code,
            name=row.name,
            position=row.position,
            kind=row.kind,
            is_final=row.is_final,
        )
        for row in rows
        if lead or row.code not in LEAD_ONLY_COLUMNS
    ]
