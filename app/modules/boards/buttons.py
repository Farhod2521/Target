"""The buttons a column's cards show, kept by the superuser: which of the
code's buttons a column has, where the movable ones put the card, and
buttons of the superuser's own that only move a card (``go``).

What a button of the code does besides moving (a close with its reason, the
discount's clock, the question to the client, a fault for the developer) is
the code's and stays so. The queues (Ishlanmagan, Support's Yangi) and the
columns that close a card keep the buttons the code gives them."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.boards.constants import (
    ACTION_DUE_OPTIONAL,
    ACTION_DUE_REQUIRED,
    ACTION_NOTE_REQUIRED,
    BOARD_BUTTON_ACTIONS,
    BUTTON_DEFAULT_TO,
    BUTTON_DUE_CHOICES,
    BUTTON_LABEL_MAX,
    BUTTON_MOVABLE,
    BUTTON_RULE_NOTES,
    BUTTONS_PER_COLUMN_MAX,
    CARD_ACTION_LABELS,
    CUSTOM_BUTTON_PREFIX,
    FINAL_SEED_COLUMNS,
    GO_ACTION,
    GO_ACTION_LABEL,
    OFFER_COLUMNS,
    QUEUE_COLUMNS,
    RENEWAL_ACTIONS,
    SALES_ACTIONS,
    SUPPORT_ACTION_LABELS,
    SUPPORT_ACTIONS,
    SUPPORT_DONE_COLUMNS,
    Board,
    CardAction,
    ColumnKind,
)
from app.modules.boards.exceptions import (
    ButtonColumnFixed,
    ButtonExists,
    ButtonLabelRequired,
    ButtonTargetFixed,
    ButtonTargetInvalid,
    NoSuchButton,
    NoSuchColumn,
    TooManyButtons,
    UnknownButton,
)
from app.modules.boards.models import BoardButton, BoardCard, BoardColumn

# The buttons the code gives each column: what the table is seeded with,
# and what a column the superuser does not set keeps.
CODE_BUTTONS: dict[Board, dict[str, tuple[CardAction, ...]]] = {
    Board.SALES: SALES_ACTIONS,
    Board.SUPPORT: SUPPORT_ACTIONS,
    Board.RENEWAL: RENEWAL_ACTIONS,
}


@dataclass(frozen=True, slots=True)
class Button:
    """A button as a card shows it and as a press reads it."""

    code: str
    # None: one of the superuser's own, which only moves the card.
    action: CardAction | None
    label: str
    is_default_label: bool
    # Where the superuser sends the card; empty: the action's own rule.
    to_column: str
    due: str
    note_required: bool


def configurable(board: Board, column_code: str) -> bool:
    """Whether the superuser sets this column's buttons: not the queues, not
    the columns that close a card, not a solved ticket's."""
    if (board, column_code) in QUEUE_COLUMNS or (board, column_code) in (
        FINAL_SEED_COLUMNS
    ):
        return False
    return not (board == Board.SUPPORT and column_code in SUPPORT_DONE_COLUMNS)


def marks_only(board: Board, column_code: str) -> bool:
    """A discount column: its clock owns the card, a button leaves a mark."""
    return board == Board.SALES and column_code in OFFER_COLUMNS


def default_label(board: Board, action: CardAction) -> str:
    labels = SUPPORT_ACTION_LABELS if board == Board.SUPPORT else {}
    return str(labels.get(action, CARD_ACTION_LABELS[action]))


def asks_due(action: CardAction) -> str:
    if action in ACTION_DUE_REQUIRED:
        return "required"
    return "optional" if action in ACTION_DUE_OPTIONAL else ""


def _seeds(board: Board, column_code: str) -> tuple[CardAction, ...]:
    if not configurable(board, column_code):
        return ()
    return CODE_BUTTONS[board].get(column_code, ())


def _seed_rows(board: Board, column_code: str, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "id": uuid.uuid4(),
            "board": str(board),
            "column_code": column_code,
            "code": str(action),
            "action": str(action),
            "label": "",
            "to_column": "",
            "due": "",
            "note_required": False,
            "position": index,
            "is_default": True,
            "created_at": now,
            "updated_at": now,
        }
        for index, action in enumerate(_seeds(board, column_code), start=1)
    ]


def ensure(db: Session, *, now: datetime) -> None:
    """The buttons the columns came with, written once. The migration
    writes them at deploy; this covers a database built without it."""
    if db.scalar(select(BoardButton.id).limit(1)) is not None:
        return
    rows = [
        row
        for board, columns in CODE_BUTTONS.items()
        for column_code in columns
        for row in _seed_rows(board, column_code, now)
    ]
    if rows:
        db.execute(
            insert(BoardButton)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["board", "column_code", "code"])
        )
    db.flush()


def _rows(db: Session, *, board: Board, column_code: str) -> list[BoardButton]:
    return list(
        db.scalars(
            select(BoardButton)
            .where(
                BoardButton.board == str(board),
                BoardButton.column_code == column_code,
            )
            .order_by(BoardButton.position, BoardButton.created_at, BoardButton.code)
        )
    )


def _button(board: Board, row: BoardButton) -> Button:
    if row.action == GO_ACTION:
        return Button(
            code=row.code,
            action=None,
            label=row.label,
            is_default_label=False,
            to_column=row.to_column,
            due=row.due,
            note_required=row.note_required,
        )
    action = CardAction(row.action)
    return Button(
        code=row.code,
        action=action,
        label=row.label or default_label(board, action),
        is_default_label=not row.label,
        to_column=row.to_column if action in BUTTON_MOVABLE[board] else "",
        due=asks_due(action),
        note_required=action in ACTION_NOTE_REQUIRED,
    )


def _of_the_code(board: Board, action: CardAction) -> Button:
    return Button(
        code=str(action),
        action=action,
        label=default_label(board, action),
        is_default_label=True,
        to_column="",
        due=asks_due(action),
        note_required=action in ACTION_NOTE_REQUIRED,
    )


def offered(db: Session, card: BoardCard) -> list[Button]:
    """The buttons the card shows where it stands. A closed lead or renewal
    card shows none."""
    board = Board(card.board)
    if board != Board.SUPPORT and card.closed_at is not None:
        return []
    if not configurable(board, card.column_code):
        return [
            _of_the_code(board, action)
            for action in CODE_BUTTONS[board].get(card.column_code, ())
        ]
    ensure(db, now=utcnow())
    return [
        _button(board, row)
        for row in _rows(db, board=board, column_code=card.column_code)
        if row.action == GO_ACTION or row.action in CardAction.values
    ]


def pressed(db: Session, card: BoardCard, code: str) -> Button | None:
    """The card's button with this code, if its column has it."""
    return next((item for item in offered(db, card) if item.code == code), None)


def go_target(db: Session, *, board: Board, code: str) -> BoardColumn | None:
    """A column one of the superuser's buttons may send a card to: visible,
    worked by hand, and not one that closes a card."""
    return db.scalar(
        select(BoardColumn).where(
            BoardColumn.board == str(board),
            BoardColumn.code == code,
            BoardColumn.is_visible.is_(True),
            BoardColumn.is_final.is_(False),
            BoardColumn.kind == str(ColumnKind.MANUAL),
        )
    )


def pointing_at(db: Session, *, board: Board, column_code: str) -> int:
    """How many buttons send cards to this column."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(BoardButton)
            .where(
                BoardButton.board == str(board), BoardButton.to_column == column_code
            )
        )
        or 0
    )


# -- the superuser's changes --------------------------------------------------


def _column(db: Session, *, board: Board, code: str) -> BoardColumn:
    found = db.scalar(
        select(BoardColumn).where(
            BoardColumn.board == str(board),
            BoardColumn.code == code,
            BoardColumn.is_visible.is_(True),
        )
    )
    if found is None:
        raise NoSuchColumn
    if not configurable(board, code):
        raise ButtonColumnFixed
    return found


def _checked_target(
    db: Session, *, board: Board, column_code: str, to: str, required: bool
) -> str:
    if not to:
        if required:
            raise ButtonTargetInvalid
        return ""
    if marks_only(board, column_code):
        raise ButtonTargetFixed
    if to == column_code or go_target(db, board=board, code=to) is None:
        raise ButtonTargetInvalid
    return to


def _clean_label(label: str, *, required: bool) -> str:
    cleaned = " ".join(label.split())[:BUTTON_LABEL_MAX]
    if required and not cleaned:
        raise ButtonLabelRequired
    return cleaned


def _checked_due(due: str) -> str:
    if due not in BUTTON_DUE_CHOICES:
        raise UnknownButton
    return due


def add(
    db: Session,
    *,
    board: Board,
    column_code: str,
    action: str,
    label: str,
    to_column: str,
    due: str,
    note_required: bool,
    actor_id: uuid.UUID,
    now: datetime,
) -> BoardButton:
    """One more button on a column: one of the code's the column lacks, or
    one of the superuser's own (``go``) with its words and its column."""
    ensure(db, now=now)
    _column(db, board=board, code=column_code)
    have = _rows(db, board=board, column_code=column_code)
    if len(have) >= BUTTONS_PER_COLUMN_MAX:
        raise TooManyButtons(BUTTONS_PER_COLUMN_MAX)
    position = max((row.position for row in have), default=0) + 1
    if action == GO_ACTION:
        row = BoardButton(
            code=f"{CUSTOM_BUTTON_PREFIX}{uuid.uuid4().hex[:10]}",
            action=GO_ACTION,
            label=_clean_label(label, required=True),
            to_column=_checked_target(
                db, board=board, column_code=column_code, to=to_column, required=True
            ),
            due=_checked_due(due),
            note_required=note_required,
        )
    else:
        if action not in {str(item) for item in BOARD_BUTTON_ACTIONS[board]}:
            raise UnknownButton
        if any(item.code == action for item in have):
            raise ButtonExists
        movable = CardAction(action) in BUTTON_MOVABLE[board]
        if to_column and not movable:
            raise ButtonTargetFixed
        row = BoardButton(
            code=action,
            action=action,
            label=_clean_label(label, required=False),
            to_column=_checked_target(
                db, board=board, column_code=column_code, to=to_column, required=False
            ),
        )
    row.board = str(board)
    row.column_code = column_code
    row.position = position
    row.created_by_id = actor_id
    row.created_at = now
    row.updated_at = now
    db.add(row)
    db.commit()
    return row


def _own(db: Session, *, board: Board, button_id: uuid.UUID) -> BoardButton:
    found = db.get(BoardButton, button_id)
    if found is None or found.board != str(board):
        raise NoSuchButton
    return found


def edit(
    db: Session,
    *,
    board: Board,
    button_id: uuid.UUID,
    label: str,
    to_column: str,
    due: str,
    note_required: bool,
    position: int,
    now: datetime,
) -> BoardButton:
    """A button's words, its column, its place among the column's buttons;
    for one of the superuser's own also what it asks for."""
    row = _own(db, board=board, button_id=button_id)
    own = row.action == GO_ACTION
    if not own and to_column and CardAction(row.action) not in BUTTON_MOVABLE[board]:
        raise ButtonTargetFixed
    row.label = _clean_label(label, required=own)
    row.to_column = _checked_target(
        db, board=board, column_code=row.column_code, to=to_column, required=own
    )
    if own:
        row.due = _checked_due(due)
        row.note_required = note_required
    row.position = position
    row.updated_at = now
    db.commit()
    return row


def remove(db: Session, *, board: Board, button_id: uuid.UUID) -> str:
    """The button off its column. One the column came with returns with
    «Standartga qaytarish». The column it stood on."""
    row = _own(db, board=board, button_id=button_id)
    column_code = row.column_code
    db.delete(row)
    db.commit()
    return column_code


def reset(db: Session, *, board: Board, column_code: str, now: datetime) -> None:
    """The column's buttons as the code gives them: the superuser's changes
    to it are dropped. A column of the superuser's own is left with none."""
    ensure(db, now=now)
    _column(db, board=board, code=column_code)
    db.execute(
        delete(BoardButton).where(
            BoardButton.board == str(board), BoardButton.column_code == column_code
        )
    )
    rows = _seed_rows(board, column_code, now)
    if rows:
        db.execute(insert(BoardButton).values(rows))
    db.commit()


# -- the settings' view --------------------------------------------------------


def _row_out(board: Board, row: BoardButton, names: dict[str, str]) -> dict[str, Any]:
    own = row.action == GO_ACTION
    action = None if own else CardAction(row.action)
    movable = own or (action in BUTTON_MOVABLE[board])
    default_to = "" if action is None else BUTTON_DEFAULT_TO[board].get(action, "")
    shown = _button(board, row)
    return {
        "id": str(row.id),
        "code": row.code,
        "action": row.action,
        "is_custom": own,
        "label": shown.label,
        "is_default_label": shown.is_default_label,
        "default_label": "" if action is None else default_label(board, action),
        "to_column": row.to_column if movable else "",
        "default_to": default_to,
        "movable": movable,
        "rule_note": ""
        if action is None
        else BUTTON_RULE_NOTES.get((board, action), ""),
        # The column it sends cards to was taken off the board.
        "to_missing": bool(row.to_column) and row.to_column not in names,
        "due": shown.due,
        "note_required": shown.note_required,
        "position": row.position,
        "is_default": row.is_default,
    }


def settings_view(db: Session, *, board: Board, may_edit: bool) -> dict[str, Any]:
    """Every visible column with its buttons, the buttons the board has to
    offer, and the columns a button may send a card to."""
    ensure(db, now=utcnow())
    columns = list(
        db.scalars(
            select(BoardColumn)
            .where(BoardColumn.board == str(board), BoardColumn.is_visible.is_(True))
            .order_by(BoardColumn.position, BoardColumn.code)
        )
    )
    names = {column.code: column.name for column in columns}
    by_column: dict[str, list[BoardButton]] = {}
    for row in db.scalars(
        select(BoardButton)
        .where(BoardButton.board == str(board))
        .order_by(BoardButton.position, BoardButton.created_at, BoardButton.code)
    ):
        by_column.setdefault(row.column_code, []).append(row)

    def column_out(column: BoardColumn) -> dict[str, Any]:
        open_to = configurable(board, column.code)
        rows = by_column.get(column.code, []) if open_to else []
        seeds = [str(action) for action in _seeds(board, column.code)]
        return {
            "code": column.code,
            "name": column.name,
            "is_custom": column.is_custom,
            "configurable": open_to,
            "marks_only": marks_only(board, column.code),
            "is_changed": open_to
            and (
                [row.code for row in rows] != seeds
                or any(row.label or row.to_column for row in rows)
            ),
            "buttons": [
                _row_out(board, row, names)
                for row in rows
                if row.action == GO_ACTION or row.action in CardAction.values
            ],
            # What the code gives a column the superuser does not set.
            "fixed": []
            if open_to
            else [
                default_label(board, action)
                for action in CODE_BUTTONS[board].get(column.code, ())
            ],
        }

    return {
        "board": str(board),
        "may_edit": may_edit,
        "max_per_column": BUTTONS_PER_COLUMN_MAX,
        "columns": [column_out(column) for column in columns],
        "catalog": [
            {
                "action": str(action),
                "label": default_label(board, action),
                "due": asks_due(action),
                "note_required": action in ACTION_NOTE_REQUIRED,
                "movable": action in BUTTON_MOVABLE[board],
                "default_to": BUTTON_DEFAULT_TO[board].get(action, ""),
                "rule_note": BUTTON_RULE_NOTES.get((board, action), ""),
            }
            for action in BOARD_BUTTON_ACTIONS[board]
        ]
        + [
            {
                "action": GO_ACTION,
                "label": GO_ACTION_LABEL,
                "due": "",
                "note_required": False,
                "movable": True,
                "default_to": "",
                "rule_note": "",
            }
        ],
        "targets": [
            {"code": column.code, "name": column.name}
            for column in columns
            if not column.is_final and column.kind == str(ColumnKind.MANUAL)
        ],
    }
