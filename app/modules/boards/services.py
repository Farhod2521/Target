"""What people do to cards: take a lead, press a button, give a card to a
manager, write a note. Each change is one transaction with its history line."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
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
    OFFER_COLUMNS,
    OFFER_STEPS,
    SALES_ACTIONS,
    SUPPORT_ACTIONS,
    TICKET_TAKE_LIMIT,
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
    NoTicketToTake,
    NotOnBoard,
    ReasonRequired,
    TakeLimit,
    TicketHeld,
)
from app.modules.boards.models import BoardCard, BoardCardEvent
from app.modules.boards.offer import OFFERED_REF


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
    """A board's lead sees every card on it; a sales manager and a Support
    member only their own. Support's lead is the superuser or the Owner."""
    board = Board(card.board)
    if not access.sees(board):
        return False
    if access.leads_board(board):
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
    """The next lead nobody works yet, now this manager's. A client whose
    discount is running (they paid Start) comes first, the 20% ones before
    the 10% ones: their time is going. Then the newest sign-up. Two managers
    pressing at once get two different leads."""
    waiting = (
        select(BoardCard)
        .where(BoardCard.board == str(Board.SALES), BoardCard.closed_at.is_(None))
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    card = None
    for _percent, _hours, column in OFFER_STEPS:
        card = db.scalar(
            waiting.where(
                BoardCard.column_code == str(column), BoardCard.manager_id.is_(None)
            ).order_by(BoardCard.column_since.desc(), BoardCard.id)
        )
        if card is not None:
            break
    if card is not None:
        # The card stays in its discount column; only its person changes.
        card.manager_id = manager.id
        record(db, card=card, kind=EventKind.TAKEN, now=now, actor=manager)
        db.commit()
        return card
    card = db.scalar(
        waiting.where(BoardCard.column_code == str(SalesColumn.UNWORKED)).order_by(
            BoardCard.opened_at.desc(), BoardCard.id
        )
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


def working_count(db: Session, *, user_id: uuid.UUID) -> int:
    """How many tickets this person has in Ishlanmoqda."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(BoardCard)
            .where(
                BoardCard.board == str(Board.SUPPORT),
                BoardCard.manager_id == user_id,
                BoardCard.column_code == str(SupportColumn.IN_PROGRESS),
            )
        )
        or 0
    )


def _room_to_take(db: Session, *, user: User) -> None:
    """Refuse a sixth ticket. The person's own row is locked first, so two
    presses at once are counted one after the other."""
    db.execute(select(User.id).where(User.id == user.id).with_for_update())
    if working_count(db, user_id=user.id) >= TICKET_TAKE_LIMIT:
        raise TakeLimit(TICKET_TAKE_LIMIT)


def take_ticket(db: Session, *, member: User, now: datetime) -> BoardCard:
    """«Zayavka olish»: the ticket that waited longest in Yangi with nobody
    on it, now this person's and in Ishlanmoqda. One a press, and none while
    they have the limit in Ishlanmoqda."""
    _room_to_take(db, user=member)
    card = db.scalar(
        select(BoardCard)
        .where(
            BoardCard.board == str(Board.SUPPORT),
            BoardCard.column_code == str(SupportColumn.NEW),
            BoardCard.manager_id.is_(None),
        )
        .order_by(BoardCard.column_since, BoardCard.id)
        .limit(1)
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if card is None:
        raise NoTicketToTake
    card.manager_id = member.id
    card.due_at = None
    move(
        db,
        card=card,
        to=str(SupportColumn.IN_PROGRESS),
        kind=EventKind.TICKET_TAKEN,
        now=now,
        actor=member,
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
    if card.board == str(Board.RENEWAL):
        from app.modules.boards import renewal

        return renewal.act(
            db,
            card=card,
            user=user,
            action=action,
            reason=reason,
            note=text,
            due=due,
            said=_said(text, due),
            now=now,
        )
    if card.closed_at is not None:
        raise CardClosed
    if action not in SALES_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    if action == CardAction.NEEDS_SUPPORT:
        # Support reads why: the mark is set with its reason written.
        if on and not text:
            raise NoteRequired
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
    if action in ACTION_NOTE_REQUIRED and not text:
        raise NoteRequired
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
    said = _said(text, due)
    if action != CardAction.CLOSE and card.column_code in OFFER_COLUMNS:
        # The discount's clock owns this column: the call leaves its mark.
        record(db, card=card, kind=kind, now=now, actor=user, body=said)
    elif action == CardAction.CONTACTED and _starts_offer(db, card=card):
        # The talk itself starts the lead's discount: 20% from this minute.
        # Its own line a moment earlier, so the history reads in order.
        talked = now - timedelta(microseconds=1)
        record(db, card=card, kind=kind, now=talked, actor=user, body=said)
        move(
            db,
            card=card,
            to=str(OFFER_STEPS[0][2]),
            kind=EventKind.OFFERED,
            now=now,
            actor=user,
            ref=OFFERED_REF,
        )
    else:
        move(db, card=card, to=str(to), kind=kind, now=now, actor=user, body=said)
    db.commit()
    return card


def _starts_offer(db: Session, *, card: BoardCard) -> bool:
    """Whether «Gaplashildi» starts this lead's discount: once per client,
    and not for one whose Start payment started it, or who paid a full plan."""
    from app.modules.boards.offer import bought_full_plan, clocks_for

    if clocks_for(db, [card]):
        return False
    return not bought_full_plan(db, owner_id=card.owner_id)


# Where a Sales button puts the card, and the line it writes.
_SALES_MOVES: dict[CardAction, tuple[SalesColumn, EventKind]] = {
    CardAction.CONTACTED: (SalesColumn.CONTACTED, EventKind.CONTACTED),
    CardAction.NO_CONTACT: (SalesColumn.NO_CONTACT, EventKind.NO_CONTACT),
    CardAction.CALLBACK: (SalesColumn.CALLBACK, EventKind.CALLBACK),
    CardAction.WILL_PAY: (SalesColumn.AWAITING, EventKind.WILL_PAY),
    CardAction.CLOSE: (SalesColumn.CLOSED, EventKind.CLOSED),
    CardAction.RELEASE: (SalesColumn.UNWORKED, EventKind.RELEASED),
}


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
    """A ticket's buttons are its person's, and the superuser's and the
    Owner's. «Ishlayapman» on a ticket with nobody makes who pressed its
    person. «Hal qilindi» does not close it: the client is asked first, and
    the ticket waits in Tasdiq kutilmoqda for their answer."""
    if action not in SUPPORT_ACTIONS.get(card.column_code, ()):
        raise ActionNotHere
    if held_by_another(card, user=user, access=access):
        raise TicketHeld
    if action in ACTION_NOTE_REQUIRED and not note:
        raise NoteRequired
    if action == CardAction.START:
        if card.manager_id is None:
            card.manager_id = user.id
        to, kind = SupportColumn.IN_PROGRESS, EventKind.STARTED
    elif action == CardAction.WAIT:
        to, kind = SupportColumn.WAITING, EventKind.WAITING
    elif action == CardAction.TO_DEVELOPER:
        to, kind = SupportColumn.DEVELOPER, EventKind.DEVELOPER
    elif action == CardAction.RELEASE:
        card.manager_id = None
        to, kind = SupportColumn.NEW, EventKind.RELEASED
    elif action == CardAction.REOPEN:
        card.closed_at = None
        if card.manager_id is None:
            card.manager_id = user.id
        to, kind = SupportColumn.IN_PROGRESS, EventKind.REOPENED
    else:
        to, kind = SupportColumn.CONFIRMING, EventKind.RESOLVED
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
    Ishlanmagan, or straight to a manager. A client who paid a full plan is
    not a lead (one who paid only Start is); one whose card was closed gets that card back, with its history."""
    from app.modules.boards.access import may_take
    from app.modules.boards.offer import bought_full_plan

    if not access.leads_board(Board.SALES):
        raise CardNotFound
    client = client_for(db, client_id)
    manager = None
    if to_id is not None:
        manager = db.get(User, to_id)
        if manager is None or not may_take(db, manager):
            raise NotOnBoard
    if bought_full_plan(db, owner_id=client.id):
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
    to_id: uuid.UUID | None = None,
    now: datetime,
) -> BoardCard:
    """A client's ticket opened by hand, saying why. The client's one
    ticket takes it as one more reason: a closed one is reopened, an open
    one gets the line.

    The superuser and the Owner may name the Support member it goes to
    (``to_id``), whatever that person holds already. A Support member opens
    it for themselves: it is theirs and in Ishlanmoqda, so it needs room
    under the limit, and a client another member works is not theirs to
    open."""
    from app.modules.boards.constants import TicketReason
    from app.modules.boards.tickets import raise_ticket

    if not access.sees(Board.SUPPORT):
        raise CardNotFound
    text = note.strip()[:NOTE_MAX]
    if not text:
        raise NoteRequired
    client = client_for(db, client_id)
    lead = access.leads_board(Board.SUPPORT)
    member: User | None = None
    if lead:
        if to_id is not None:
            member = db.get(User, to_id)
            if member is None or not works_on(db, member, Board.SUPPORT):
                raise NotOnBoard
    else:
        member = user
        held = db.scalar(
            select(BoardCard.manager_id).where(
                BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == client.id
            )
        )
        if held not in (None, user.id):
            raise TicketHeld
        # Their own ticket coming back is not a new one taken.
        if held is None:
            _room_to_take(db, user=user)
    raise_ticket(
        db,
        owner_id=client.id,
        reason=TicketReason.MANUAL,
        ref=f"manual:{uuid.uuid4()}",
        now=now,
        detail=text,
        actor=user,
    )
    card = db.scalar(
        select(BoardCard)
        .where(BoardCard.board == str(Board.SUPPORT), BoardCard.owner_id == client.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    assert card is not None
    if member is not None and card.manager_id != member.id:
        card.manager_id = member.id
        if lead:
            record(
                db,
                card=card,
                kind=EventKind.ASSIGNED,
                now=now,
                actor=user,
                body=member.full_name or member.email,
            )
    if not lead and card.column_code != SupportColumn.IN_PROGRESS:
        card.due_at = None
        move(
            db,
            card=card,
            to=str(SupportColumn.IN_PROGRESS),
            kind=EventKind.STARTED,
            now=now,
            actor=user,
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
    if board != Board.SUPPORT and card.closed_at is not None:
        raise CardClosed
    if to_id is None:
        if card.manager_id is None:
            return card
        card.manager_id = None
        card.due_at = None
        if board == Board.SALES and card.column_code in OFFER_COLUMNS:
            # The discount's clock owns the column; «Lid olish» gives it out.
            back = card.column_code
        elif board == Board.SALES:
            back = str(SalesColumn.UNWORKED)
        elif board == Board.RENEWAL or card.closed_at is not None:
            # A renewal card stands where the term put it, with nobody on it.
            back = card.column_code
        else:
            back = str(SupportColumn.NEW)
        if back == card.column_code:
            record(db, card=card, kind=EventKind.RETURNED, now=now, actor=user)
        else:
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
    if to == card.column_code and board == Board.RENEWAL:
        # The card stays in its column; only its person changes.
        record(
            db,
            card=card,
            kind=EventKind.ASSIGNED,
            now=now,
            actor=user,
            body=manager.full_name or manager.email,
        )
        db.commit()
        return card
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
