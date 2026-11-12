"""What people do to cards: take a lead, press a button, give a card to a
manager, write a note. Each change is one transaction with its history line."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.dates import localtime
from app.modules.accounts.models import User
from app.modules.boards.access import Access, works_on
from app.modules.boards.constants import (
    ACTION_DUE_OPTIONAL,
    ACTION_DUE_REQUIRED,
    ACTION_NOTE_REQUIRED,
    ATTEMPTS_MAX,
    DUE_MAX_DAYS,
    DUE_PAST_SLACK_SECONDS,
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
    CardExists,
    CardNotFound,
    ClientNotFound,
    ClientPaid,
    DueInvalid,
    DuePast,
    DueRequired,
    NoteRequired,
    NothingToTake,
    NotOnBoard,
    OfferGiven,
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
    """The newest lead nobody works yet, now this manager's: a fresh sign-up
    is called first. Two managers pressing at once get two different leads."""
    card = db.scalar(
        select(BoardCard)
        .where(
            BoardCard.board == str(Board.SALES),
            BoardCard.column_code == str(SalesColumn.UNWORKED),
            BoardCard.closed_at.is_(None),
        )
        .order_by(BoardCard.opened_at.desc(), BoardCard.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if card is None:
        raise NothingToTake
    card.manager_id = manager.id
    card.due_at = None
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


def due_words(due_at: datetime) -> str:
    """A deadline as the office reads it in a card's history."""
    return localtime(due_at).strftime("%d.%m.%Y %H:%M")


def checked_due(due_at: datetime | None, *, now: datetime) -> datetime | None:
    """A deadline that may be kept: it names its zone, is not behind us and
    is not years away."""
    if due_at is None:
        return None
    if due_at.tzinfo is None:
        raise DueInvalid
    if due_at < now - timedelta(seconds=DUE_PAST_SLACK_SECONDS):
        raise DuePast
    if due_at > now + timedelta(days=DUE_MAX_DAYS):
        raise DueInvalid
    return due_at


def _said(note: str, due_at: datetime | None) -> str:
    """The history line of a button pressed with a deadline."""
    if due_at is None:
        return note
    head = f"Muddat: {due_words(due_at)}"
    return f"{head}. {note}" if note else head


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
    due_at: datetime | None = None,
) -> BoardCard:
    """One button of a card, if its column has it. A button that moves the
    card ends its deadline, unless it sets a new one."""
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    text = note.strip()[:NOTE_MAX]
    due = checked_due(due_at, now=now)
    if action in ACTION_DUE_REQUIRED and due is None:
        raise DueRequired
    if action not in ACTION_DUE_REQUIRED and action not in ACTION_DUE_OPTIONAL:
        due = None
    if card.board == str(Board.SUPPORT):
        return _support_act(
            db,
            card=card,
            user=user,
            access=access,
            action=action,
            note=text,
            due=due,
            now=now,
        )
    if card.closed_at is not None:
        raise CardClosed
    if action not in SALES_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    if action in ACTION_NOTE_REQUIRED and not text:
        raise NoteRequired
    if action == CardAction.NEEDS_SUPPORT:
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
        db.commit()
        return card
    if action == CardAction.OFFER:
        # The discount's own clock is the card's deadline now.
        _offer(db, card=card, user=user, note=text, now=now)
        card.due_at = None
        db.commit()
        return card
    if action == CardAction.CLOSE:
        if reason not in CloseReason.values:
            raise ReasonRequired
        if reason == CloseReason.OTHER and not text:
            raise NoteRequired
        card.close_reason = reason
        card.close_note = text
        card.closed_at = now
    elif action == CardAction.CONTACTED:
        card.contact_mark = str(CardAction.CONTACTED)
    elif action == CardAction.NO_CONTACT:
        card.contact_mark = str(CardAction.NO_CONTACT)
        card.attempts = min(card.attempts + 1, ATTEMPTS_MAX)
    elif action == CardAction.RELEASE:
        card.manager_id = None
    to, kind = _SALES_MOVES[action]
    card.due_at = due
    move(
        db,
        card=card,
        to=str(to),
        kind=kind,
        now=now,
        actor=user,
        body=_said(text, due),
    )
    db.commit()
    return card


# Where a Sales button puts the card, and the line it writes.
_SALES_MOVES: dict[CardAction, tuple[SalesColumn, EventKind]] = {
    CardAction.CONTACTED: (SalesColumn.CONTACTED, EventKind.CONTACTED),
    CardAction.NO_CONTACT: (SalesColumn.NO_CONTACT, EventKind.NO_CONTACT),
    CardAction.CALLBACK: (SalesColumn.CALLBACK, EventKind.CALLBACK),
    CardAction.WILL_PAY: (SalesColumn.AWAITING, EventKind.WILL_PAY),
    CardAction.CLOSE: (SalesColumn.CLOSED, EventKind.CLOSED),
    CardAction.RELEASE: (SalesColumn.UNWORKED, EventKind.RELEASED),
}


def _offer(
    db: Session, *, card: BoardCard, user: User, note: str, now: datetime
) -> None:
    """«Chegirma berish»: the card goes to 20%, and the offer's clock starts.
    Once per client, even if the card is later moved back by hand."""
    from app.modules.boards.offer import OFFERED_REF, offered_at

    if offered_at(db, card_id=card.id) is not None:
        raise OfferGiven
    move(
        db,
        card=card,
        to=str(SalesColumn.DISCOUNT_20),
        kind=EventKind.OFFERED,
        now=now,
        actor=user,
        body=note,
        ref=OFFERED_REF,
    )


def held_by_another(card: BoardCard, *, user: User, access: Access) -> bool:
    """A ticket somebody else works: only they, the superuser and the Owner
    press its buttons."""
    return card.manager_id not in (None, user.id) and not access.full


def _support_act(
    db: Session,
    *,
    card: BoardCard,
    user: User,
    access: Access,
    action: CardAction,
    note: str,
    due: datetime | None,
    now: datetime,
) -> BoardCard:
    """«Ishlayapman» makes the first Support member who presses it the
    client's person; the ticket's buttons are theirs from then on, and the
    superuser's and the Owner's. «Qayta ochish» is anybody's on the board:
    the ticket goes back to its person, or to who pressed if it had none."""
    if action not in SUPPORT_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    if action != CardAction.REOPEN and held_by_another(card, user=user, access=access):
        raise TicketHeld
    if action in ACTION_NOTE_REQUIRED and not note:
        raise NoteRequired
    if action == CardAction.START:
        if card.manager_id is None:
            card.manager_id = user.id
        to, kind = SupportColumn.IN_PROGRESS, EventKind.STARTED
    elif action == CardAction.WAIT:
        to, kind = SupportColumn.WAITING, EventKind.WAITING
    elif action == CardAction.RELEASE:
        card.manager_id = None
        to, kind = SupportColumn.NEW, EventKind.RELEASED
    elif action == CardAction.REOPEN:
        card.closed_at = None
        if card.manager_id is None:
            card.manager_id = user.id
        to, kind = SupportColumn.IN_PROGRESS, EventKind.REOPENED
    else:
        card.closed_at = now
        to, kind = SupportColumn.RESOLVED, EventKind.RESOLVED
    card.due_at = due
    move(
        db,
        card=card,
        to=str(to),
        kind=kind,
        now=now,
        actor=user,
        body=_said(note, due),
    )
    db.commit()
    return card


def set_due(
    db: Session,
    *,
    card_id: uuid.UUID,
    user: User,
    access: Access,
    due_at: datetime | None,
    note: str,
    now: datetime,
) -> BoardCard:
    """The card's deadline, set or taken off by who works it. The card
    stays in its column."""
    card = card_for(db, card_id=card_id, user=user, access=access, lock=True)
    if card.closed_at is not None:
        raise CardClosed
    if card.board == str(Board.SUPPORT) and held_by_another(
        card, user=user, access=access
    ):
        raise TicketHeld
    due = checked_due(due_at, now=now)
    if due == card.due_at:
        return card
    card.due_at = due
    text = note.strip()[:NOTE_MAX]
    if due is None:
        record(
            db, card=card, kind=EventKind.DUE_CLEARED, now=now, actor=user, body=text
        )
    else:
        body = f"{due_words(due)}. {text}" if text else due_words(due)
        record(db, card=card, kind=EventKind.DUE_SET, now=now, actor=user, body=body)
    db.commit()
    return card


def client_for(db: Session, client_id: uuid.UUID) -> User:
    """An account a card may be opened for: a customer's own, not staff's
    and not a CRM login's (that one belongs to its owner's business)."""
    client = db.get(User, client_id)
    if (
        client is None
        or not client.is_active
        or client.is_staff
        or client.is_superuser
        or client.crm_owner_id is not None
    ):
        raise ClientNotFound
    return client


def add_lead(
    db: Session,
    *,
    client_id: uuid.UUID,
    user: User,
    access: Access,
    note: str,
    to_id: uuid.UUID | None,
    now: datetime,
) -> BoardCard:
    """The Sales lead puts a signed-up client on the board by hand: into
    Ishlanmagan, or straight to a manager. A client who paid a plan is not
    a lead; one whose card was closed gets that card back, with its history."""
    from app.modules.billing.constants import InvoiceKind, InvoiceStatus
    from app.modules.billing.models import Invoice
    from app.modules.boards.access import may_take

    if not access.leads_board(Board.SALES):
        raise CardNotFound
    client = client_for(db, client_id)
    manager = None
    if to_id is not None:
        manager = db.get(User, to_id)
        if manager is None or not may_take(db, manager):
            raise NotOnBoard
    paid = db.scalar(
        select(Invoice.id)
        .where(
            Invoice.owner_id == client.id,
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.status == str(InvoiceStatus.PAID),
        )
        .limit(1)
    )
    if paid is not None:
        raise ClientPaid
    text = note.strip()[:NOTE_MAX]
    to = str(SalesColumn.NEW_LEAD if manager else SalesColumn.UNWORKED)
    card = db.scalar(
        select(BoardCard)
        .where(BoardCard.board == str(Board.SALES), BoardCard.owner_id == client.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if card is not None:
        if card.closed_at is None:
            raise CardExists
        if card.column_code == SalesColumn.SOLD:
            raise ClientPaid
        card.closed_at = None
        card.close_reason = ""
        card.close_note = ""
        card.manager_id = manager.id if manager else None
        card.due_at = None
        move(
            db,
            card=card,
            to=to,
            kind=EventKind.REOPENED,
            now=now,
            actor=user,
            body=text,
        )
        db.commit()
        return card
    card = BoardCard(
        board=str(Board.SALES),
        owner_id=client.id,
        manager_id=manager.id if manager else None,
        column_code=to,
        opened_at=now,
        column_since=now,
        reasons=[],
    )
    try:
        with db.begin_nested():
            db.add(card)
            db.flush()
    except IntegrityError:
        # The minute's sweep opened this client's card a moment ago.
        raise CardExists from None
    record(
        db,
        card=card,
        kind=EventKind.ADDED,
        now=now,
        actor=user,
        to_column=to,
        body=text,
        ref="opened",
    )
    db.commit()
    return card


def add_ticket(
    db: Session,
    *,
    client_id: uuid.UUID,
    user: User,
    access: Access,
    note: str,
    now: datetime,
) -> BoardCard:
    """Anybody on the Support board opens a client's ticket by hand, saying
    why. The client's one ticket takes it as one more reason: a solved one
    is reopened, an open one gets the line."""
    from app.modules.boards.constants import TicketReason
    from app.modules.boards.tickets import raise_ticket

    if not access.sees(Board.SUPPORT):
        raise CardNotFound
    text = note.strip()[:NOTE_MAX]
    if not text:
        raise NoteRequired
    client = client_for(db, client_id)
    raise_ticket(
        db,
        owner_id=client.id,
        reason=TicketReason.MANUAL,
        ref=f"manual:{uuid.uuid4()}",
        now=now,
        detail=text,
        actor=user,
    )
    db.commit()
    card = db.scalar(
        select(BoardCard).where(
            BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == client.id
        )
    )
    assert card is not None
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
        card.due_at = None
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
    if column.is_final:
        card.due_at = None
    if column.code == SalesColumn.UNWORKED:
        card.manager_id = None
        card.due_at = None
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
