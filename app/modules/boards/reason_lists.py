"""The lists of reasons a person picks from on a board: why a Sales card is
closed, why a client does not renew, why a call did not reach them, why a
card is moved by hand. The superuser keeps them; a card keeps the reason's
code, so a renamed or archived reason still reads right on old cards and in
the reports. Support's «Bog'lanib bo'lmadi» has its own, older list
(``ContactReason``)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.boards.constants import (
    BOARD_REASON_PURPOSES,
    CUSTOM_REASON_PREFIX,
    REASON_NAME_MAX,
    REASON_PURPOSE_HINTS,
    REASON_PURPOSE_LABELS,
    REASONS_MAX,
    SEED_REASONS,
    Board,
    ReasonPurpose,
)
from app.modules.boards.exceptions import (
    NoSuchReason,
    NoSuchReasonList,
    ReasonNameRequired,
    ReasonNameTaken,
    ReasonRequired,
    TooManyReasons,
)
from app.modules.boards.models import BoardReason


def ensure(db: Session, *, now: datetime) -> None:
    """The reasons the boards came with, written once. The migration writes
    them at deploy; this covers a database built without it."""
    have = int(
        db.scalar(
            select(func.count())
            .select_from(BoardReason)
            .where(BoardReason.is_default.is_(True))
        )
        or 0
    )
    if have >= len(SEED_REASONS):
        return
    position: dict[tuple[str, str], int] = {}
    for seed in SEED_REASONS:
        key = (str(seed.board), str(seed.purpose))
        position[key] = position.get(key, 0) + 1
        db.execute(
            insert(BoardReason)
            .values(
                id=uuid.uuid4(),
                board=key[0],
                purpose=key[1],
                code=seed.code,
                name=seed.name,
                position=position[key],
                note_required=seed.note_required,
                is_archived=False,
                is_default=True,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_nothing(index_elements=["board", "purpose", "code"])
        )
    db.flush()


def has_list(board: Board, purpose: str) -> bool:
    return any(str(item) == purpose for item in BOARD_REASON_PURPOSES[board])


def checked_purpose(board: Board, purpose: str) -> ReasonPurpose:
    if not has_list(board, purpose):
        raise NoSuchReasonList
    return ReasonPurpose(purpose)


def rows(
    db: Session, *, board: Board, purpose: ReasonPurpose, archived: bool = False
) -> list[BoardReason]:
    """The list in its order; the archived ones only when asked for."""
    query = (
        select(BoardReason)
        .where(BoardReason.board == str(board), BoardReason.purpose == str(purpose))
        .order_by(BoardReason.position, BoardReason.created_at, BoardReason.code)
    )
    if not archived:
        query = query.where(BoardReason.is_archived.is_(False))
    return list(db.scalars(query))


def labels(db: Session, *, board: Board, purpose: ReasonPurpose) -> dict[str, str]:
    """Every reason's name by its code, the archived ones too: what a card
    closed long ago is read by."""
    return {
        code: name
        for code, name in db.execute(
            select(BoardReason.code, BoardReason.name).where(
                BoardReason.board == str(board), BoardReason.purpose == str(purpose)
            )
        )
    }


def asked(db: Session, *, board: Board, purpose: ReasonPurpose) -> bool:
    """Whether the list has a reason to pick: an empty one is not asked."""
    return (
        db.scalar(
            select(BoardReason.id)
            .where(
                BoardReason.board == str(board),
                BoardReason.purpose == str(purpose),
                BoardReason.is_archived.is_(False),
            )
            .limit(1)
        )
        is not None
    )


def picked(
    db: Session, *, board: Board, purpose: ReasonPurpose, code: str
) -> BoardReason:
    """A live reason of the list, by its code."""
    if not code:
        raise ReasonRequired
    query = select(BoardReason).where(
        BoardReason.board == str(board),
        BoardReason.purpose == str(purpose),
        BoardReason.code == code,
        BoardReason.is_archived.is_(False),
    )
    found = db.scalar(query)
    if found is None:
        # A database built without the migration has no reasons yet.
        ensure(db, now=utcnow())
        found = db.scalar(query)
    if found is None:
        raise ReasonRequired
    return found


def said(found: BoardReason, note: str) -> str:
    """The line a card's history keeps: the reason, then what was written."""
    return f"{found.name}. {note}" if note else found.name


def _clean(name: str) -> str:
    cleaned = " ".join(name.split())[:REASON_NAME_MAX]
    if not cleaned:
        raise ReasonNameRequired
    return cleaned


def _free(
    db: Session,
    *,
    board: Board,
    purpose: ReasonPurpose,
    name: str,
    but: uuid.UUID | None = None,
) -> None:
    for row in rows(db, board=board, purpose=purpose):
        if row.id != but and row.name.casefold() == name.casefold():
            raise ReasonNameTaken


def add(
    db: Session,
    *,
    board: Board,
    purpose: ReasonPurpose,
    name: str,
    note_required: bool,
    actor_id: uuid.UUID,
    now: datetime,
) -> BoardReason:
    ensure(db, now=now)
    cleaned = _clean(name)
    every = rows(db, board=board, purpose=purpose, archived=True)
    if len(every) >= REASONS_MAX:
        raise TooManyReasons(REASONS_MAX)
    _free(db, board=board, purpose=purpose, name=cleaned)
    row = BoardReason(
        board=str(board),
        purpose=str(purpose),
        code=f"{CUSTOM_REASON_PREFIX}{uuid.uuid4().hex[:10]}",
        name=cleaned,
        position=max((item.position for item in every), default=0) + 1,
        note_required=note_required,
        created_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.commit()
    return row


def _row(
    db: Session, *, board: Board, purpose: ReasonPurpose, reason_id: uuid.UUID
) -> BoardReason:
    found = db.get(BoardReason, reason_id)
    if found is None or found.board != str(board) or found.purpose != str(purpose):
        raise NoSuchReason
    return found


def edit(
    db: Session,
    *,
    board: Board,
    purpose: ReasonPurpose,
    reason_id: uuid.UUID,
    name: str,
    position: int,
    note_required: bool,
    now: datetime,
) -> BoardReason:
    """New words, place, or whether a line is asked with it; cards that
    carry the reason read the new words."""
    row = _row(db, board=board, purpose=purpose, reason_id=reason_id)
    cleaned = _clean(name)
    if not row.is_archived:
        _free(db, board=board, purpose=purpose, name=cleaned, but=row.id)
    row.name = cleaned
    row.position = position
    row.note_required = note_required
    row.updated_at = now
    db.commit()
    return row


def set_archived(
    db: Session,
    *,
    board: Board,
    purpose: ReasonPurpose,
    reason_id: uuid.UUID,
    archived: bool,
    now: datetime,
) -> BoardReason:
    """Off the list to pick from, or back on it; cards keep it either way."""
    row = _row(db, board=board, purpose=purpose, reason_id=reason_id)
    if row.is_archived and not archived:
        _free(db, board=board, purpose=purpose, name=row.name, but=row.id)
    row.is_archived = archived
    row.updated_at = now
    db.commit()
    return row


def row_out(row: BoardReason) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "code": row.code,
        "name": row.name,
        "position": row.position,
        "note_required": row.note_required,
        "is_archived": row.is_archived,
        "is_default": row.is_default,
    }


def lists_view(db: Session, *, board: Board, may_edit: bool) -> dict[str, Any]:
    """The board's lists for its settings, each with its rows, the archived
    ones too: whoever reads the settings sees what was taken off."""
    return {
        "board": str(board),
        "may_edit": may_edit,
        "lists": [
            {
                "purpose": str(purpose),
                "label": str(REASON_PURPOSE_LABELS[purpose]),
                "hint": str(REASON_PURPOSE_HINTS[purpose]),
                "rows": [
                    row_out(row)
                    for row in rows(db, board=board, purpose=purpose, archived=True)
                ],
            }
            for purpose in BOARD_REASON_PURPOSES[board]
        ],
    }
