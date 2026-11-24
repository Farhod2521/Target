"""A board column by column over a period: how many cards stand in each
now, how many came into it, and how long a card stood there before it left.
Every column the reader sees is on it, the superuser's own too, so a column
added in the office is counted the day it is added."""

from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.modules.accounts.models import User
from app.modules.boards.access import Access
from app.modules.boards.constants import REPORT_MAX_DAYS, Board
from app.modules.boards.exceptions import ReportPeriodInvalid
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.sales_report import day_bounds
from app.modules.boards.selectors import columns_for


def report(
    db: Session, *, board: Board, user: User, access: Access, start: date, end: date
) -> dict[str, Any]:
    """A manager reads their own cards; the board's lead, the Owner and the
    superuser everybody's."""
    if end < start or (end - start).days > REPORT_MAX_DAYS:
        raise ReportPeriodInvalid
    first, after = day_bounds(start, end)
    everybody = access.leads_board(board)
    scope = [BoardCard.board == str(board)]
    if not everybody:
        scope.append(BoardCard.manager_id == user.id)
    cards = select(BoardCard.id).where(*scope)

    standing = {
        code: int(total)
        for code, total in db.execute(
            select(BoardCard.column_code, func.count())
            .where(*scope)
            .group_by(BoardCard.column_code)
        )
    }
    in_period = (
        BoardCardEvent.card_id.in_(cards),
        BoardCardEvent.created_at >= first,
        BoardCardEvent.created_at < after,
        BoardCardEvent.from_column != BoardCardEvent.to_column,
    )
    entered = {
        code: int(total)
        for code, total in db.execute(
            select(
                BoardCardEvent.to_column,
                func.count(func.distinct(BoardCardEvent.card_id)),
            )
            .where(*in_period, BoardCardEvent.to_column != "")
            .group_by(BoardCardEvent.to_column)
        )
    }
    # A stay that ended in the period: from the card's last coming to the
    # column before the line that took it out.
    came = aliased(BoardCardEvent)
    arrived = (
        select(func.max(came.created_at))
        .where(
            came.card_id == BoardCardEvent.card_id,
            came.to_column == BoardCardEvent.from_column,
            came.created_at < BoardCardEvent.created_at,
        )
        .correlate(BoardCardEvent)
        .scalar_subquery()
    )
    stays: dict[str, tuple[int, float]] = {
        code: (int(total), float(seconds or 0))
        for code, total, seconds in db.execute(
            select(
                BoardCardEvent.from_column,
                func.count(arrived),
                func.avg(func.extract("epoch", BoardCardEvent.created_at - arrived)),
            )
            .where(*in_period, BoardCardEvent.from_column != "")
            .group_by(BoardCardEvent.from_column)
        )
    }
    rows = []
    for column in columns_for(db, board=board, access=access):
        left, seconds = stays.get(column.code, (0, 0.0))
        rows.append(
            {
                "code": column.code,
                "name": column.name,
                "is_custom": column.is_custom,
                "is_final": column.is_final,
                "now": standing.get(column.code, 0),
                "entered": entered.get(column.code, 0),
                "left": left,
                "stay_hours": round(seconds / 3600, 1) if left else None,
            }
        )
    return {
        "board": str(board),
        "date_from": start,
        "date_to": end,
        "everybody": everybody,
        "rows": rows,
    }
