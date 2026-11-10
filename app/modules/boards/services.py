"""What people do to cards: take a lead, press a button, give a card to a
manager, write a note. Each change is one transaction with its history line."""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.boards.access import Access, works_on
from app.modules.boards.constants import (
    NOTE_MAX,
    SALES_ACTIONS,
    SUPPORT_ACTIONS,
    Board,
    CardAction,
    CloseReason,
    EventKind,
    SalesColumn,
    SupportColumn,
)
from app.modules.boards.exceptions import (
    ActionNotHere,
    CardClosed,
    CardNotFound,
    NoteRequired,
    NothingToTake,
    NotOnBoard,
    ReasonRequired,
    TicketHeld,
)
from app.modules.boards.models import BoardCard, BoardCardEvent


def record(
    db: Session,
    *,
    card: BoardCard,
    kind: EventKind,
    now: datetime,
    actor: User | None = None,
    from_column: str = "",
    to_column: str = "",
    body: str = "",
    ref: str = "",
) -> None:
    db.add(
        BoardCardEvent(
            card_id=card.id,
            owner_id=card.owner_id,
            kind=str(kind),
            from_column=from_column,
            to_column=to_column,
            actor_id=actor.id if actor else None,
            body=body,
            ref=ref,
            created_at=now,
        )
    )


def move(
    db: Session,
    *,
    card: BoardCard,
    to: str,
    kind: EventKind,
    now: datetime,
    actor: User | None = None,
    body: str = "",
    ref: str = "",
) -> None:
    """The card into ``to``, with the line that says so."""
    before = card.column_code
    card.column_code = to
    card.column_since = now
    record(
        db,
        card=card,
        kind=kind,
        now=now,
        actor=actor,
        from_column=before,
        to_column=to,
        body=body,
        ref=ref,
    )


def may_see(card: BoardCard, *, user: User, access: Access) -> bool:
    """A board's lead sees every card on it; a sales manager only their own;
    Support sees the whole Support board."""
    board = Board(card.board)
    if not access.sees(board):
        return False
    if access.leads_board(board) or board == Board.SUPPORT:
        return True
    return card.manager_id == user.id


def card_for(
    db: Session, *, card_id: uuid.UUID, user: User, access: Access, lock: bool = False
) -> BoardCard:
    query = select(BoardCard).where(BoardCard.id == card_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    card = db.scalar(query)
    if card is None or not may_see(card, user=user, access=access):
        raise CardNotFound
    return card


def take_lead(db: Session, *, manager: User, now: datetime) -> BoardCard:
    """The oldest lead nobody works yet, now this manager's. Two managers
    pressing at once get two different leads."""
    card = db.scalar(
        select(BoardCard)
        .where(
            BoardCard.board == str(Board.SALES),
            BoardCard.column_code == str(SalesColumn.UNWORKED),
            BoardCard.closed_at.is_(None),
        )
        .order_by(BoardCard.opened_at, BoardCard.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if card is None:
        raise NothingToTake
    card.manager_id = manager.id
    move(
        db,
        card=card,
        to=str(SalesColumn.NEW_LEAD),
        kind=EventKind.TAKEN,
        now=now,
        actor=manager,
    )
    db.commit()
    return card


def act(
    db: Session,
    *,
    card_id: uuid.UUID,
    user: User,
    access: Access,
    action: CardAction,
    now: datetime,
    on: bool = True,
    reason: str = "",
    note: str = "",
) -> BoardCard:
    """One button of a card, if its column has it."""
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    if card.board == str(Board.SUPPORT):
        return _support_act(
            db, card=card, user=user, access=access, action=action, note=note, now=now
        )
    if card.closed_at is not None:
        raise CardClosed
    if action not in SALES_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    text = note.strip()[:NOTE_MAX]
    if action == CardAction.CONTACTED:
        card.contact_mark = str(CardAction.CONTACTED)
        move(
            db,
            card=card,
            to=str(SalesColumn.CONTACTED),
            kind=EventKind.CONTACTED,
            now=now,
            actor=user,
            body=text,
        )
    elif action == CardAction.NO_CONTACT:
        card.contact_mark = str(CardAction.NO_CONTACT)
        move(
            db,
            card=card,
            to=str(SalesColumn.NO_CONTACT),
            kind=EventKind.NO_CONTACT,
            now=now,
            actor=user,
            body=text,
        )
    elif action == CardAction.NEEDS_SUPPORT:
        if card.needs_support != on:
            card.needs_support = on
            record(
                db,
                card=card,
                kind=EventKind.SUPPORT_ON if on else EventKind.SUPPORT_OFF,
                now=now,
                actor=user,
                body=text,
            )
    else:
        if reason not in CloseReason.values:
            raise ReasonRequired
        if reason == CloseReason.OTHER and not text:
            raise NoteRequired
        card.close_reason = reason
        card.close_note = text
        card.closed_at = now
        move(
            db,
            card=card,
            to=str(SalesColumn.CLOSED),
            kind=EventKind.CLOSED,
            now=now,
            actor=user,
            body=text,
        )
    db.commit()
    return card


def _support_act(
    db: Session,
    *,
    card: BoardCard,
    user: User,
    access: Access,
    action: CardAction,
    note: str,
    now: datetime,
) -> BoardCard:
    """«Ishlayapman» makes the first Support member who presses it the
    client's person for good; «Hal qilindi» is theirs to press. The
    superuser and the Owner may press either."""
    if action not in SUPPORT_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    if card.manager_id not in (None, user.id) and not access.full:
        raise TicketHeld
    text = note.strip()[:NOTE_MAX]
    if action == CardAction.START:
        if card.manager_id is None:
            card.manager_id = user.id
        move(
            db,
            card=card,
            to=str(SupportColumn.IN_PROGRESS),
            kind=EventKind.STARTED,
            now=now,
            actor=user,
            body=text,
        )
    else:
        card.closed_at = now
        move(
            db,
            card=card,
            to=str(SupportColumn.RESOLVED),
            kind=EventKind.RESOLVED,
            now=now,
            actor=user,
            body=text,
        )
    db.commit()
    return card


def assign(
    db: Session,
    *,
    card_id: uuid.UUID,
    user: User,
    access: Access,
    to_id: uuid.UUID | None,
    now: datetime,
) -> BoardCard:
    """The board's lead gives a card to somebody on that board, or takes it
    back when ``to_id`` is empty: a lead to Ishlanmagan, a ticket to Yangi.
    Support's lead is the superuser or the Owner."""
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    board = Board(card.board)
    if not access.leads_board(board):
        raise CardNotFound
    if board == Board.SALES and card.closed_at is not None:
        raise CardClosed
    if to_id is None:
        if card.manager_id is None:
            return card
        card.manager_id = None
        if board == Board.SALES:
            back = str(SalesColumn.UNWORKED)
        elif card.column_code == SupportColumn.RESOLVED:
            back = card.column_code
        else:
            back = str(SupportColumn.NEW)
        move(db, card=card, to=back, kind=EventKind.RETURNED, now=now, actor=user)
        db.commit()
        return card
    manager = db.get(User, to_id)
    if manager is None or not works_on(db, manager, board):
        raise NotOnBoard
    if card.manager_id == manager.id:
        return card
    card.manager_id = manager.id
    to = card.column_code
    if board == Board.SALES and card.column_code == SalesColumn.UNWORKED:
        to = str(SalesColumn.NEW_LEAD)
    move(
        db,
        card=card,
        to=to,
        kind=EventKind.ASSIGNED,
        now=now,
        actor=user,
        body=manager.full_name or manager.email,
    )
    db.commit()
    return card


def add_note(
    db: Session,
    *,
    card_id: uuid.UUID,
    user: User,
    access: Access,
    body: str,
    now: datetime,
) -> BoardCard:
    text = body.strip()[:NOTE_MAX]
    if not text:
        raise NoteRequired
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    record(db, card=card, kind=EventKind.NOTE, now=now, actor=user, body=text)
    db.commit()
    return card


def move_by_hand(
    db: Session,
    *,
    card_id: uuid.UUID,
    user: User,
    access: Access,
    to: str,
    reason: str,
    now: datetime,
) -> BoardCard:
    """The superuser or the Owner puts a card in any visible column of its
    board, saying why. A final column closes the card; leaving one opens it.
    Ishlanmagan has nobody on the card."""
    from app.modules.boards.exceptions import MoveReasonRequired, NoSuchColumn
    from app.modules.boards.models import BoardColumn

    if not access.full:
        raise CardNotFound
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    why = reason.strip()[:NOTE_MAX]
    if not why:
        raise MoveReasonRequired
    column = db.scalar(
        select(BoardColumn).where(
            BoardColumn.board == card.board,
            BoardColumn.code == to,
            BoardColumn.is_visible.is_(True),
        )
    )
    if column is None:
        raise NoSuchColumn
    if column.code == card.column_code:
        return card
    card.closed_at = now if column.is_final else None
    if column.code == SalesColumn.UNWORKED:
        card.manager_id = None
    move(
        db,
        card=card,
        to=column.code,
        kind=EventKind.MOVED,
        now=now,
        actor=user,
        body=why,
    )
    db.commit()
    return card
