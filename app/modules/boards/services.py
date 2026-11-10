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
    Board,
    CardAction,
    CloseReason,
    EventKind,
    SalesColumn,
)
from app.modules.boards.exceptions import (
    ActionNotHere,
    CardClosed,
    CardNotFound,
    NoteRequired,
    NothingToTake,
    NotOnBoard,
    ReasonRequired,
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
        query = query.with_for_update()
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
    """One button of a Sales card, if that column has it."""
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    if card.board != str(Board.SALES) or card.closed_at is not None:
        raise CardClosed if card.closed_at is not None else ActionNotHere
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


def assign(
    db: Session,
    *,
    card_id: uuid.UUID,
    user: User,
    access: Access,
    to_id: uuid.UUID | None,
    now: datetime,
) -> BoardCard:
    """The lead gives a Sales card to a manager, or takes it back to
    Ishlanmagan when ``to_id`` is empty."""
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    if card.board != str(Board.SALES) or not access.leads_board(Board.SALES):
        raise CardNotFound
    if card.closed_at is not None:
        raise CardClosed
    if to_id is None:
        if card.manager_id is None:
            return card
        card.manager_id = None
        move(
            db,
            card=card,
            to=str(SalesColumn.UNWORKED),
            kind=EventKind.RETURNED,
            now=now,
            actor=user,
        )
        db.commit()
        return card
    manager = db.get(User, to_id)
    if manager is None or not works_on(db, manager, Board.SALES):
        raise NotOnBoard
    if card.manager_id == manager.id:
        return card
    card.manager_id = manager.id
    to = (
        str(SalesColumn.NEW_LEAD)
        if card.column_code == SalesColumn.UNWORKED
        else card.column_code
    )
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
