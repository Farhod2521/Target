"""A board's columns and the moment it went live: reading them, and the
superuser's changes (names, order, their own columns)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.boards.access import Access
from app.modules.boards.constants import (
    COLUMN_NAME_MAX,
    COLUMNS_MAX,
    CUSTOM_COLUMN_PREFIX,
    LEAD_ONLY_COLUMNS,
    OFFER_COLUMNS,
    QUEUE_COLUMNS,
    SEED_COLUMNS,
    START_TALKED_COLUMNS,
    Board,
    ColumnKind,
)
from app.modules.boards.models import BoardCard, BoardColumn, BoardSetting


@dataclass(frozen=True, slots=True)
class ColumnView:
    code: str
    name: str
    position: int
    kind: str
    is_final: bool
    is_custom: bool = False
    is_talked: bool = False


def _view(row: BoardColumn) -> ColumnView:
    return ColumnView(
        code=row.code,
        name=row.name,
        position=row.position,
        kind=row.kind,
        is_final=row.is_final,
        is_custom=row.is_custom,
        is_talked=row.is_talked,
    )


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
                is_talked=(board == Board.SALES and seed.code in START_TALKED_COLUMNS),
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
        _view(row) for row in rows if lead or (board, row.code) not in LEAD_ONLY_COLUMNS
    ]


def removed_columns(db: Session, *, board: Board) -> list[ColumnView]:
    """The superuser's own columns taken off the board: a card's history
    still names them, and they may be put back."""
    rows = db.scalars(
        select(BoardColumn)
        .where(
            BoardColumn.board == str(board),
            BoardColumn.is_custom.is_(True),
            BoardColumn.is_visible.is_(False),
        )
        .order_by(BoardColumn.name, BoardColumn.code)
    )
    return [_view(row) for row in rows]


def custom_names(db: Session, *, board: str) -> dict[str, str]:
    """The superuser's own columns by code, the removed ones too: what a
    card's history names them by."""
    return {
        code: name
        for code, name in db.execute(
            select(BoardColumn.code, BoardColumn.name).where(
                BoardColumn.board == board, BoardColumn.is_custom.is_(True)
            )
        )
    }


def _locked_rows(db: Session, board: Board) -> list[BoardColumn]:
    return list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board == str(board))
            .order_by(BoardColumn.position, BoardColumn.code)
            .with_for_update()
        )
    )


def _renumber(shown: list[BoardColumn], rows: list[BoardColumn]) -> None:
    """``shown`` in its order from 1, the hidden ones after them."""
    position = 0
    for row in shown:
        position += 1
        row.position = position
    for row in rows:
        if not row.is_visible:
            position += 1
            row.position = position


def _clean_name(name: str) -> str:
    from app.modules.boards.exceptions import ColumnNameRequired

    cleaned = " ".join(name.split())[:COLUMN_NAME_MAX]
    if not cleaned:
        raise ColumnNameRequired
    return cleaned


def _place(shown: list[BoardColumn], row: BoardColumn, after: str | None) -> None:
    """``row`` into ``shown`` right after the column ``after``; with none
    named, before the first final column (Sotildi, Hal qilindi, …)."""
    from app.modules.boards.exceptions import NoSuchColumn

    if after:
        codes = [item.code for item in shown]
        if after not in codes:
            raise NoSuchColumn
        shown.insert(codes.index(after) + 1, row)
        return
    first_final = next(
        (index for index, item in enumerate(shown) if item.is_final), len(shown)
    )
    shown.insert(first_final, row)


def _room_for_one(shown: list[BoardColumn], name: str) -> None:
    from app.modules.boards.exceptions import ColumnNameTaken, TooManyColumns

    if len(shown) >= COLUMNS_MAX:
        raise TooManyColumns(COLUMNS_MAX)
    if any(item.name.casefold() == name.casefold() for item in shown):
        raise ColumnNameTaken


def add_column(
    db: Session,
    *,
    board: Board,
    name: str,
    after: str | None,
    actor_id: uuid.UUID,
    now: datetime,
) -> str:
    """A column of the superuser's own. No rule knows it: cards come and go
    by hand («Ko'chirish»), and it never closes a card. Its code."""
    cleaned = _clean_name(name)
    rows = _locked_rows(db, board)
    shown = [row for row in rows if row.is_visible]
    _room_for_one(shown, cleaned)
    row = BoardColumn(
        board=str(board),
        code=f"{CUSTOM_COLUMN_PREFIX}{uuid.uuid4().hex[:10]}",
        name=cleaned,
        position=0,
        kind=str(ColumnKind.MANUAL),
        is_final=False,
        is_visible=True,
        is_custom=True,
        created_by_id=actor_id,
        updated_by_id=actor_id,
        created_at=now,
        updated_at=now,
    )
    _place(shown, row, after)
    db.add(row)
    _renumber(shown, rows)
    db.commit()
    return row.code


def _custom(rows: list[BoardColumn], code: str) -> BoardColumn:
    from app.modules.boards.exceptions import ColumnNotCustom, NoSuchColumn

    found = next((row for row in rows if row.code == code), None)
    if found is None:
        raise NoSuchColumn
    if not found.is_custom:
        raise ColumnNotCustom
    return found


def _cards_in(db: Session, *, board: Board, code: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(BoardCard)
            .where(BoardCard.board == str(board), BoardCard.column_code == code)
        )
        or 0
    )


def _move_targets(db: Session, *, board: Board, code: str) -> list[BoardColumn]:
    """Where a removed column's cards may go: a visible column a person
    works, that does not close a card, is not the queue and is not a
    discount column (its clock owns the cards there)."""
    return [
        row
        for row in db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board == str(board), BoardColumn.is_visible.is_(True))
            .order_by(BoardColumn.position, BoardColumn.code)
        )
        if row.code != code
        and not row.is_final
        and row.kind == str(ColumnKind.MANUAL)
        and (board, row.code) not in QUEUE_COLUMNS
        and not (board == Board.SALES and row.code in OFFER_COLUMNS)
    ]


def _attached(db: Session, *, board: Board, code: str) -> tuple[list[Any], list[Any]]:
    """The buttons that send cards to the column and the rules that use it."""
    from app.modules.boards.models import BoardButton, BoardRule

    sending = list(
        db.scalars(
            select(BoardButton).where(
                BoardButton.board == str(board), BoardButton.to_column == code
            )
        )
    )
    using = [
        rule
        for rule in db.scalars(select(BoardRule).where(BoardRule.board == str(board)))
        if rule.to_column == code or code in (rule.from_columns or [])
    ]
    return sending, using


def removal_view(db: Session, *, board: Board, code: str) -> dict[str, Any]:
    """What taking a column off the board touches, for the question asked
    before it: the cards standing in it and where they may go, the buttons
    that send cards to it and the rules that use it."""
    from app.modules.boards import buttons, rules
    from app.modules.boards.constants import CardAction

    rows = list(db.scalars(select(BoardColumn).where(BoardColumn.board == str(board))))
    found = _custom(rows, code)
    names = {row.code: row.name for row in rows}
    sending, using = _attached(db, board=board, code=code)

    def label(button: Any) -> str:
        own = button.label or (
            buttons.default_label(board, CardAction(button.action))
            if button.action in CardAction.values
            else button.action
        )
        return f"«{names.get(button.column_code, button.column_code)}»: {own}"

    def rule_name(rule: Any) -> str:
        spec = rules.SPEC_BY_CODE.get(rule.code)
        return spec.name if spec is not None else rule.name

    return {
        "code": found.code,
        "name": found.name,
        "cards": _cards_in(db, board=board, code=code),
        "targets": [
            {"code": row.code, "name": row.name}
            for row in _move_targets(db, board=board, code=code)
        ],
        "buttons": [label(button) for button in sending],
        "rules": [rule_name(rule) for rule in using],
    }


def _detach(db: Session, *, board: Board, code: str, now: datetime) -> None:
    """Nothing points at a column that left the board. A button of the
    superuser's own that sent cards there goes with it, and a button of the
    code goes back to its own column. A rule of the code's reads and sends
    as the code has it again; one of the superuser's own that needs the
    column is switched off, and one that only also read from it reads the
    rest."""
    from app.modules.boards import buttons, rules

    sending, using = _attached(db, board=board, code=code)
    for button in sending:
        if button.action == buttons.GO_ACTION:
            db.delete(button)
        else:
            button.to_column = ""
            button.updated_at = now
    for rule in using:
        spec = rules.SPEC_BY_CODE.get(rule.code)
        rest = [item for item in (rule.from_columns or []) if item != code]
        if spec is not None:
            if rule.to_column == code:
                rule.to_column = spec.to_column
            rule.from_columns = rest or list(spec.from_columns)
        elif rule.to_column == code or not rest:
            rule.is_enabled = False
        else:
            rule.from_columns = rest
        rule.updated_at = now


def remove_column(
    db: Session,
    *,
    board: Board,
    code: str,
    actor: Any,
    now: datetime,
    move_to: str = "",
) -> int:
    """One of the superuser's own columns off the board. Hidden, not
    deleted: the cards' history names it, and it may be put back. The cards
    standing in it go to ``move_to`` first (asked for while there are any),
    each with a line saying why; the buttons and rules that used the column
    are let go of it (``_detach``). How many cards moved."""
    from app.modules.boards.constants import EventKind
    from app.modules.boards.exceptions import ColumnHasCards, MoveTargetInvalid
    from app.modules.boards.services import move

    rows = _locked_rows(db, board)
    found = _custom(rows, code)
    if not found.is_visible:
        return 0
    moved = 0
    if _cards_in(db, board=board, code=code):
        if not move_to:
            raise ColumnHasCards(_cards_in(db, board=board, code=code))
        if move_to not in {
            row.code for row in _move_targets(db, board=board, code=code)
        }:
            raise MoveTargetInvalid
        cards = list(
            db.scalars(
                select(BoardCard)
                .where(BoardCard.board == str(board), BoardCard.column_code == code)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        for card in cards:
            move(
                db,
                card=card,
                to=move_to,
                kind=EventKind.MOVED,
                now=now,
                actor=actor,
                body=f"«{found.name}» ustuni doskadan olib tashlandi.",
            )
        moved = len(cards)
    _detach(db, board=board, code=code, now=now)
    found.is_visible = False
    found.is_talked = False
    found.updated_by_id = actor.id
    found.updated_at = now
    _renumber([row for row in rows if row.is_visible], rows)
    db.commit()
    return moved


def restore_column(
    db: Session, *, board: Board, code: str, actor_id: uuid.UUID, now: datetime
) -> None:
    """A removed column back on the board, before the final columns."""
    rows = _locked_rows(db, board)
    found = _custom(rows, code)
    if found.is_visible:
        return
    shown = [row for row in rows if row.is_visible]
    _room_for_one(shown, found.name)
    found.is_visible = True
    found.updated_by_id = actor_id
    found.updated_at = now
    _place(shown, found, None)
    _renumber(shown, rows)
    db.commit()


def rename_and_order(
    db: Session,
    *,
    board: Board,
    columns: list[tuple[str, str]],
    actor_id: object,
    now: datetime,
) -> None:
    """The visible columns in their new order, each with its name. Hidden
    columns keep their order after them. Codes never change."""
    from app.modules.boards.exceptions import ColumnNameRequired, ColumnsMismatch

    rows = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board == str(board))
            .order_by(BoardColumn.position, BoardColumn.code)
            .with_for_update()
        )
    )
    visible = {row.code: row for row in rows if row.is_visible}
    codes = [code for code, _ in columns]
    if sorted(codes) != sorted(visible) or len(set(codes)) != len(codes):
        raise ColumnsMismatch
    cleaned = [(code, " ".join(name.split())) for code, name in columns]
    if any(not name for _, name in cleaned):
        raise ColumnNameRequired
    position = 0
    for code, name in cleaned:
        position += 1
        row = visible[code]
        row.position = position
        row.name = name[:COLUMN_NAME_MAX]
        row.updated_by_id = actor_id  # type: ignore[assignment]
        row.updated_at = now
    for row in rows:
        if not row.is_visible:
            position += 1
            row.position = position
    db.commit()


def talk_fixed(board: Board, code: str) -> bool:
    """Columns whose «gaplashilgan» mark is the code's: Bog'lanildi and the
    discount columns."""
    return board == Board.SALES and code in START_TALKED_COLUMNS


def may_mark_talked(board: Board, row: BoardColumn) -> bool:
    """A Sales column the superuser may mark as talked to: one a person
    works, that does not close a card and is not the queue."""
    return (
        board == Board.SALES
        and row.is_visible
        and not row.is_final
        and row.kind == str(ColumnKind.MANUAL)
        and (board, row.code) not in QUEUE_COLUMNS
        and not talk_fixed(board, row.code)
    )


def markable_columns(db: Session, *, board: Board) -> frozenset[str]:
    if board != Board.SALES:
        return frozenset()
    return frozenset(
        row.code
        for row in db.scalars(
            select(BoardColumn).where(BoardColumn.board == str(board))
        )
        if may_mark_talked(board, row)
    )


def talked_columns(db: Session) -> frozenset[str]:
    """The Sales columns where a card counts as talked to."""
    return frozenset(
        db.scalars(
            select(BoardColumn.code).where(
                BoardColumn.board == str(Board.SALES),
                BoardColumn.is_talked.is_(True),
                BoardColumn.is_visible.is_(True),
            )
        )
    ) | frozenset(START_TALKED_COLUMNS)


def mark_talked(
    db: Session,
    *,
    board: Board,
    code: str,
    talked: bool,
    actor_id: uuid.UUID,
    now: datetime,
) -> None:
    from app.modules.boards.exceptions import ColumnMarkFixed, NoSuchColumn

    row = db.scalar(
        select(BoardColumn).where(
            BoardColumn.board == str(board), BoardColumn.code == code
        )
    )
    if row is None or not row.is_visible:
        raise NoSuchColumn
    if not may_mark_talked(board, row):
        raise ColumnMarkFixed
    row.is_talked = talked
    row.updated_by_id = actor_id
    row.updated_at = now
    db.commit()
